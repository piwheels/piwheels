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
import signal
from collections import OrderedDict
from threading import Thread, main_thread
from datetime import timedelta
from functools import partial
from time import sleep

from pisense import SenseHAT, StickEvent, array
from colorzero import Color
from dateutil import tz

from piwheels import terminal, const, protocols, transport, tasks
from .renderers import MainRenderer, HelpRenderer, QuitRenderer


LOCAL = tz.tzlocal()


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
            '--status-queue', metavar='ADDR', default=const.STATUS_QUEUE,
            help="The address of the queue used to report status to monitors "
            "(default: %(default)s)")
        parser.add_argument(
            '--control-queue', metavar='ADDR', default=const.CONTROL_QUEUE,
            dest='master_queue',
            help="The address of the queue a monitor can use to control the "
            "master (default: %(default)s)")
        parser.add_argument(
            '-r', '--rotate', metavar='DEGREES', default=0, type=int,
            help="The rotation of the HAT in degrees; must be 0 (the default) "
            "90, 180, or 270")
        try:
            config = parser.parse_args(args)
            config.control_queue = 'inproc://quit'
        except:  # pylint: disable=bare-except
            return terminal.error_handler(*sys.exc_info())

        with SenseHAT() as hat:
            hat.rotation = config.rotate
            ctx = transport.Context()
            quit_queue = ctx.socket(transport.PULL,
                                    protocol=protocols.task_control)
            quit_queue.bind(config.control_queue)
            try:
                stick = StickTask(config, hat)
                stick.start()
                screen = ScreenTask(config, hat)
                screen.start()
                msg, data = quit_queue.recv_msg()
                assert msg == 'QUIT'
                #signal.sigwait({signal.SIGINT, signal.SIGTERM})
            except KeyboardInterrupt:
                pass
            finally:
                screen.quit()
                screen.join()
                stick.quit()
                stick.join()
                ctx.close()
                hat.screen.fade_to(array(Color('black')))


class StickTask(Thread):
    def __init__(self, config, hat):
        super().__init__()
        self._quit = False
        self.stick = hat.stick
        self.ctx = transport.Context()
        self.stick_queue = self.ctx.socket(
            transport.PUSH, protocol=protocols.sense_stick)
        self.stick_queue.hwm = 10
        self.stick_queue.bind('inproc://stick')

    def quit(self):
        self._quit = True

    def run(self):
        try:
            while not self._quit:
                event = self.stick.read(0.1)
                if event is not None and event.pressed:
                    self.stick_queue.send_msg('EVENT', (
                        event.timestamp.replace(tzinfo=LOCAL),
                        event.direction,
                        event.pressed,
                        event.held,
                    ))

        finally:
            self.stick_queue.close()


class ScreenTask(tasks.Task):
    name = "screen"

    def __init__(self, config, hat):
        super().__init__(config)
        self._renderer = None
        self._screen = hat.screen
        self._screen_iter = None
        self._transition = self._screen.fade_to
        self.renderers = {}
        self.renderers['main'] = MainRenderer()
        self.renderers['help'] = HelpRenderer()
        self.renderers['quit'] = QuitRenderer()
        self.switch_to(self.renderers['main'], transition='fade')
        stick_queue = self.ctx.socket(
            transport.PULL, protocol=reversed(protocols.sense_stick))
        stick_queue.hwm = 10
        stick_queue.connect('inproc://stick')
        status_queue = self.ctx.socket(
            transport.SUB, protocol=reversed(protocols.monitor_stats))
        status_queue.hwm = 10
        status_queue.connect(config.status_queue)
        status_queue.subscribe('')
        self.register(stick_queue, self.handle_stick)
        self.register(status_queue, self.handle_status)
        self.every(timedelta(seconds=1/15), self.refresh)
        # NOTE: The following sleep seems to help the SUB socket get set up
        # before we ping the control socket with HELLO and get a flood of
        # data from the master
        sleep(1)
        self.ctrl_queue = self.ctx.socket(
            transport.PUSH, protocol=reversed(protocols.master_control))
        self.ctrl_queue.connect(config.master_queue)
        self.ctrl_queue.send_msg('HELLO')

    def refresh(self):
        self._transition(next(self._screen_iter))
        self._transition = self._screen.draw

    def poll(self):
        super().poll(1 / 30)

    @property
    def renderer(self):
        return self._renderer

    def handle_stick(self, queue):
        msg, event = queue.recv_msg()
        self.renderer.move(StickEvent._make(event), self)

    def handle_status(self, queue):
        """
        Handler for messages received from the PUB/SUB external status queue.
        """
        self.renderers['main'].message(*queue.recv_msg())

    def send_control(self, msg, data=transport.NoData):
        """
        Send *msg* with optional *data* to the master's control queue.
        """
        self.ctrl_queue.send_msg(msg, data)

    def switch_to(self, renderer, *, transition, **kwargs):
        """
        Switch the active renderer to *renderer*, with the specified
        *transition* (one of the strings, "slide", "zoom", "fade", or "draw")
        which will be performed with any given keyword args.
        """
        self._transition = partial({
            'slide': self._screen.slide_to,
            'zoom': self._screen.zoom_to,
            'fade': self._screen.fade_to,
            'draw': self._screen.draw,
        }[transition], **kwargs)
        self._renderer = renderer
        self._screen_iter = iter(renderer)


main = PiWheelsSense()  # pylint: disable=invalid-name

if __name__ == '__main__':
    main()
