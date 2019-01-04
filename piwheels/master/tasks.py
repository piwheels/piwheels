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
Implements the base classes (:class:`Task` and its derivative
:class:`PauseableTask`) which form the basis of all the tasks in the piwheels
master.

.. autoexception:: TaskQuit

.. autoclass:: Task
    :members:

.. autoclass:: PauseableTask
    :members:
"""

import logging
from threading import Thread

import zmq

from .. import transport, protocols


class TaskQuit(Exception):
    """
    Exception raised when the "QUIT" message is received by the internal
    control queue.
    """


class Task(Thread):
    """
    The :class:`Task` class is a :class:`~threading.Thread` derivative which is
    the base for all tasks in the piwheels master. The :meth:`run` method is
    overridden to perform a simple task loop which calls :meth:`loop` once a
    cycle, and :meth:`poll` to react to any messages arriving into queues.
    Queues are associated with handlers via the :meth:`register` method.
    """
    name = 'Task'

    def __init__(self, config, control_protocol=protocols.task_control):
        super().__init__()
        self.ctx = transport.Context.instance()
        self.handlers = {}
        self.poller = zmq.Poller()
        self.logger = logging.getLogger(self.name)
        self.control_protocol = control_protocol
        control_queue = self.ctx.socket(zmq.PULL, protocol=control_protocol)
        control_queue.hwm = 10
        control_queue.bind('inproc://ctrl-%s' % self.name)
        self.quit_queue = self.ctx.socket(
            zmq.PUSH, protocol=protocols.master_control)
        self.quit_queue.hwm = 1
        self.quit_queue.connect(config.control_queue)
        self.register(control_queue, self.handle_control)

    def close(self):
        """
        Close all registered queues. This should be overridden to close any
        additional queues the task holds which aren't registered.
        """
        for queue in self.handlers:
            queue.close()
        self.quit_queue.close()

    def register(self, queue, handler, flags=zmq.POLLIN):
        """
        Register *queue* to be polled on each cycle of the task. Any messages
        with the relevant *flags* (defaults to ``POLLIN``) will trigger the
        specified *handler* method which is expected to take a single argument
        which will be *queue*.

        :param zmq.Socket queue:
            The queue to poll.

        :param handler:
            The function or method to call when a message with matching *flags*
            arrives in *queue*.

        :param int flags:
            The flags to match in the queue poller (defaults to ``POLLIN``).
        """
        self.poller.register(queue, flags)
        self.handlers[queue] = handler

    def _ctrl(self, msg, data=None):
        queue = self.ctx.socket(zmq.PUSH, protocol=self.control_protocol)
        try:
            queue.connect('inproc://ctrl-%s' % self.name)
            queue.send_msg(msg, data)
        finally:
            queue.close()

    def pause(self):
        """
        Requests that the task pause itself. This is an idempotent method; it's
        always safe to call repeatedly and even if the task isn't pauseable
        it'll simply be ignored.
        """
        self._ctrl('PAUSE')

    def resume(self):
        """
        Requests that the task resume itself. This is an idempotent method;
        it's safe to call repeatedly and even if the task isn't pauseable it'll
        simply be ignored.
        """
        self._ctrl('RESUME')

    def quit(self):
        """
        Requests that the task terminate at its earliest convenience. To wait
        until the task has actually closed, call :meth:`join` afterwards.
        """
        self._ctrl('QUIT')

    def handle_control(self, queue):
        """
        Default handler for the internal control queue. In this base
        implementation it simply handles the "QUIT" message by raising TaskQuit
        (which the :meth:`run` method will catch and use as a signal to end).
        """
        # pylint: disable=no-self-use,unused-variable
        try:
            msg, data = queue.recv_msg()
        except IOError as e:
            self.logger.exception(e)
        else:
            if msg == 'QUIT':
                raise TaskQuit
            else:
                self.logger.error('invalid control message: %s', msg)

    def once(self):
        """
        This method is called once before the task loop starts. It the task
        needs to do some initialization or setup within the task thread, this
        is the place to do it.
        """
        pass

    def loop(self):
        """
        This method is called once per loop of the task's :meth:`run` method.
        If the task needs to do some work periodically, this is the place to do
        it.
        """
        pass

    def poll(self, timeout=1):
        """
        This method is called once per loop of the task's :meth:`run` method.
        It polls all registered queues and calls their associated handlers if
        the poll is successful.
        """
        while True:
            socks = dict(self.poller.poll(timeout * 1000))
            try:
                for queue in socks:
                    self.handlers[queue](queue)
            except zmq.error.Again:
                continue  # pragma: no cover
            break

    def run(self):
        """
        This method is the main task loop. Override this to perform one-off
        startup processing within the task's background thread, and to perform
        any finalization required.
        """
        self.logger.info('starting')
        try:
            self.once()
            while True:
                self.loop()
                self.poll()
        except TaskQuit:
            self.logger.info('stopping')
        except:
            self.quit_queue.send_msg('QUIT')
            self.logger.exception('unhandled exception')
        finally:
            self.close()
            self.logger.info('stopped')


class PauseableTask(Task):
    """
    Derivative of :class:`Task` that implements a rudimentary pausing
    mechanism.  When the "PAUSE" message is received on the internal control
    queue, the task will enter a loop which simply polls the control queue
    waiting for "RESUME" or "QUIT". No other work will be done
    (:meth:`Task.loop` and :meth:`Task.poll` will not be called) until the task
    is resumed (or terminated).
    """
    def handle_control(self, queue):
        # pylint: disable=unused-variable
        try:
            msg, data = queue.recv_msg()
        except IOError as e:
            self.logger.exception(e)
        else:
            if msg == 'QUIT':
                raise TaskQuit
            elif msg == 'PAUSE':
                while True:
                    msg, data = queue.recv_msg()
                    if msg == 'QUIT':
                        raise TaskQuit
                    elif msg == 'RESUME':
                        break
                    else:
                        self.logger.error('invalid control message: %s', msg)
            else:
                self.logger.error('invalid control message: %s', msg)
