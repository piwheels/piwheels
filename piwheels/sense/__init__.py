#!/usr/bin/env python

# The piwheels project
#   Copyright (c) 2017 Ben Nuttall <https://github.com/bennuttall>
#   Copyright (c) 2017 Dave Jones <dave@waveform.org.uk>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
The piw-sense application is a fun version of the monitor that uses a Raspberry
Pi Sense HAT to provide a "physical" interface for monitoring and controlling
the master node.
"""

import sys
from collections import OrderedDict
from datetime import datetime, timedelta
from threading import Thread
from itertools import cycle
from signal import pause

import zmq
import numpy as np
from colorzero import Color, Saturation

from .. import terminal, const
from .tasks import Task
from .pisense.stick import SenseStick
from .pisense.screen import SenseScreen


class PiWheelsSense:
    """
    This is the main class for the :program:`piw-sense` script. It
    connects to the :program:`piw-master` script via the control and external
    status queues, and displays the real-time status of the master on the
    attached Raspberry Pi Sense HAT.
    """

    def __init__(self):
        self.hat = None
        self.status_queue = None
        self.ctrl_queue = None

    def __call__(self, args=None):
        parser = terminal.configure_parser(__doc__, log_params=False)
        parser.add_argument(
            '--status-queue', metavar='ADDR',
            default=const.STATUS_QUEUE,
            help="The address of the queue used to report status to monitors "
            "(default: %(default)s)")
        parser.add_argument(
            '--control-queue', metavar='ADDR',
            default=const.CONTROL_QUEUE,
            help="The address of the queue a monitor can use to control the "
            "master (default: %(default)s)")
        try:
            config = parser.parse_args(args)
        except:  # pylint: disable=bare-except
            return terminal.error_handler(*sys.exc_info())

        ctx = zmq.Context()
        try:
            screen = ScreenTask(config.status_queue)
            ui = UITask(config.ctrl_queue)
            pause()
        finally:
            ui.quit()
            ui.join()
            screen.quit()
            screen.join()
            ctx.destroy(linger=1000)
            ctx.term()


class ScreenTask(Task):
    name = "screen"

    def __init__(self, status_queue):
        self.slaves = SlaveList()
        self.screen = SenseScreen()
        self.buffer = self.screen.pixels.copy()
        pulse = [i / 10 for i in range(10)]
        pulse += list(reversed(pulse))
        self.pulse = iter(cycle(pulse))
        self.position = (0, 0)
        ctx = zmq.Context()
        stick_queue = ctx.socket(zmq.PULL)
        stick_queue.hwm = 10
        stick_queue.bind('inproc://stick')
        status_queue = ctx.socket(zmq.SUB)
        status_queue.hwm = 10
        status_queue.connect(status_queue)
        status_queue.setsockopt_string(zmq.SUBSCRIBE, '')
        self.register(stick_queue, handle_stick)
        self.register(status_queue, handle_status)

    def run(self):
        self.screen.marquee('piwheels')
        super().run()

    def poll(self):
        super().poll(0.1)

    def loop(self):
        self.buffer[:] = Color('black').rgb_bytes
        for index, slave in enumerate(self.slaves):
            y, x = divmod(index, 8)
            self.buffer[y, x] = {
                'okay':   Color('green'),
                'silent': Color('yellow'),
                'dead':   Color('red'),
            }[slave.state].rgb_bytes
        self.buffer[self.position] = Color('white').rgb_bytes
        self.screen.pixels = self.buffer

    def handle_stick(self, queue):
        event = queue.recv_pyobj()
        if event.state in ('pressed', 'held'):
            y, x = self.position
            if event.direction == 'up':
                self.position = (max(0, y - 1), x)
            elif event.direction == 'down':
                self.position = (min(7, y + 1), x)
            elif event.direction == 'left':
                self.position = (y, max(0, x - 1))
            elif event.direction == 'right':
                self.position = (y, min(7, x + 1))

    def handle_status(self, queue):
        """
        Handler for messages received from the PUB/SUB external status queue.
        As usual, messages are a list of python objects. In this case messages
        always have at least 3 elements:

        * The slave id that the message relates to (this will be -1 in the case
          of messages that don't relate to a specific build slave)
        * The timestamp when the message was sent
        * The message itself
        """
        slave_id, timestamp, msg, *args = queue.recv_pyobj()
        if msg == 'STATUS':
            self.update_status(args[0])
        else:
            self.slaves.message(slave_id, timestamp, msg, *args)


class StickTask(Thread):
    def __init__(self, ctrl_queue):
        super().__init__()
        self._quit = False
        self.ctrl_queue = ctx.socket(zmq.PUSH)
        self.ctrl_queue.connect(ctrl_queue)
        self.ctrl_queue.send_pyobj(['HELLO'])
        self.stick_queue = ctx.socket(zmq.PUSH)
        self.stick_queue.hwm = 10
        self.stick_queue.connect('inproc://stick')

    def quit(self):
        self._quit = True

    def run(self):
        try:
            with SenseStick() as stick:
                while not self._quit:
                    event = stick.read(0.1)
                    if event is not None:
                        self.stick_queue.send_pyobj(event)
        finally:
            self.ctrl_queue.close()
            self.stick_queue.close()


class SlaveList:
    """
    Tracks the active set of build slaves currently known by the master.
    Provides methods to update the state of the list based on messages received
    on the external status queue.
    """
    def __init__(self):
        self.slaves = OrderedDict()

    def __len__(self):
        return len(self.slaves)

    def __iter__(self):
        for slave in self.slaves.values():
            yield slave

    def message(self, slave_id, timestamp, msg, *args):
        """
        Update the list with a message from the external status queue.

        :param int slave_id:
            The id of the slave the message was originally sent to.

        :param datetime.datetime timestamp:
            The timestamp when the message was originally sent.

        :param str msg:
            The reply that was sent to the build slave.

        :param *args:
            Any arguments that went with the message.
        """
        try:
            state = self.slaves[slave_id]
        except KeyError:
            state = SlaveState(slave_id)
            self.slaves[slave_id] = state
        state.update(timestamp, msg, *args)
        # TODO refresh display


class SlaveState:
    """
    Class for tracking the state of a single build slave.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, slave_id):
        self.terminated = False
        self.slave_id = slave_id
        self.last_msg = ''
        self.py_version = '-'
        self.timeout = None
        self.abi = '-'
        self.platform = '-'
        self.first_seen = None
        self.last_seen = None
        self.status = ''
        self.label = ''

    def update(self, timestamp, msg, *args):
        """
        Update the slave's state from an incoming reply message.

        :param datetime.datetime timestamp:
            The time at which the message was originally sent.

        :param str msg:
            The message itself.

        :param *args:
            Any arguments sent with the message.
        """
        self.last_msg = msg
        self.last_seen = timestamp
        if msg == 'HELLO':
            self.status = 'Initializing'
            self.first_seen = timestamp
            (
                self.timeout,
                self.py_version,
                self.abi,
                self.platform,
                self.label
            ) = args
        elif msg == 'SLEEP':
            self.status = 'Waiting for jobs'
        elif msg == 'BYE':
            self.terminated = True
            self.status = 'Terminating'
        elif msg == 'BUILD':
            self.status = 'Building {} {}'.format(args[0], args[1])
        elif msg == 'SEND':
            self.status = 'Transferring file'
        elif msg == 'DONE':
            self.status = 'Cleaning up after build'

    @property
    def state(self):
        """
        Calculate a simple state indicator for the slave, used to color the
        initial "*" on the entry.
        """
        if self.first_seen is not None:
            if datetime.utcnow() - self.last_seen > timedelta(minutes=15):
                return 'silent'
            elif datetime.utcnow() - self.last_seen > self.timeout:
                return 'dead'
        if self.terminated:
            return 'dead'
        return 'okay'

    @property
    def columns(self):
        """
        Calculates the state of all columns for the slave's entry. Returns a
        list of (style, content) tuples. Note that the content is *not* padded
        for width. The :class:`SlaveListWalker` class handles this.
        """
        return [
            (self.state, '*'),
            ('status', str(self.slave_id)),
            ('status', self.label),
            ('status', since(self.first_seen)),
            ('status', since(self.last_seen)),
            ('status', self.abi),
            ('status', self.status),
        ]


main = PiWheelsSense()  # pylint: disable=invalid-name

if __name__ == '__main__':
    main()
