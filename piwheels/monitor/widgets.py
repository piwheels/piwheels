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

"Defines an urwid event loop for zmq applications and some simple widgets"

import os
import errno
import heapq
from time import time
from itertools import count
from collections import namedtuple

import zmq

# This module is a one-stop shop for all the monitor's widget needs, hence all
# the unused imports
# pylint: disable=unused-import

from urwid import (  # noqa: F401
    connect_signal,
    AttrMap,
    Button,
    Text,
    SelectableIcon,
    WidgetWrap,
    Pile,
    Columns,
    Filler,
    Divider,
    Frame,
    LineBox,
    ListBox,
    Overlay,
    ProgressBar,
    ListWalker,
    MainLoop,
    ExitMainLoop,
)


# Stop the relentless march against nicely aligned code
# pylint: disable=bad-whitespace

PALETTE = [
    ('idle',        'light red',       'default'),        # noqa: E241
    ('silent',      'yellow',          'default'),        # noqa: E241
    ('busy',        'light green',     'default'),        # noqa: E241
    ('time',        'light gray',      'default'),        # noqa: E241
    ('status',      'light gray',      'default'),        # noqa: E241
    ('hotkey',      'light cyan',      'dark blue'),      # noqa: E241
    ('normal',      'light gray',      'default'),        # noqa: E241
    ('todo',        'white',           'dark blue'),      # noqa: E241
    ('done',        'black',           'light gray'),     # noqa: E241
    ('todo_smooth', 'dark blue',       'light gray'),     # noqa: E241
    ('header',      'light gray',      'dark blue'),      # noqa: E241
    ('footer',      'light gray',      'dark blue'),      # noqa: E241
    ('dialog',      'light gray',      'dark blue'),      # noqa: E241
    ('button',      'light gray',      'dark blue'),      # noqa: E241
    ('coltrans',    'dark cyan',       'dark blue'),      # noqa: E241
    ('colheader',   'black',           'dark cyan'),      # noqa: E241
    ('inv_dialog',  'dark blue',       'light gray'),     # noqa: E241
    ('inv_normal',  'black',           'light gray'),     # noqa: E241
    ('inv_hotkey',  'dark cyan',       'light gray'),     # noqa: E241
    ('inv_button',  'black',           'light gray'),     # noqa: E241
    ('inv_status',  'black',           'light gray'),     # noqa: E241
]


AlarmTask = namedtuple('AlarmTask', ('due', 'tie_break', 'callback'))


class ZMQEventLoop:
    """
    This class is an urwid event loop for zmq applications. It supports the
    usual alarm events and file watching capabilities, but also incorporates
    the ability to watch zmq queues for events.
    """
    _alarm_break = count()

    def __init__(self):
        self._did_something = True
        self._alarms = []
        self._poller = zmq.Poller()
        self._queue_callbacks = {}
        self._idle_handle = 0
        self._idle_callbacks = {}

    def alarm(self, seconds, callback):
        """
        Call *callback* a given time from now. No parameters are passed to
        callback. Returns a handle that may be passed to :meth:`remove_alarm`.

        :param float seconds:
            floating point time to wait before calling callback.

        :param callback:
            function to call from event loop.
        """
        handle = AlarmTask(time() + seconds, next(self._alarm_break), callback)
        heapq.heappush(self._alarms, handle)
        return handle

    def remove_alarm(self, handle):
        """
        Remove an alarm. Returns ``True`` if the alarm exists, ``False``
        otherwise.
        """
        try:
            self._alarms.remove(handle)
            heapq.heapify(self._alarms)
            return True
        except ValueError:
            return False

    def watch_queue(self, queue, callback, flags=zmq.POLLIN):
        """
        Call *callback* when zmq *queue* has something to read (when *flags* is
        set to ``POLLIN``, the default) or is available to write (when *flags*
        is set to ``POLLOUT``). No parameters are passed to the callback.

        :param queue:
            The zmq queue to poll.

        :param callback:
            The function to call when the poll is successful.

        :param int flags:
            The condition to monitor on the queue (defaults to ``POLLIN``).
        """
        if queue in self._queue_callbacks:
            raise ValueError('already watching %r' % queue)
        self._poller.register(queue, flags)
        self._queue_callbacks[queue] = callback
        return queue

    def watch_file(self, fd, callback, flags=zmq.POLLIN):
        """
        Call *callback* when *fd* has some data to read. No parameters are
        passed to the callback. The *flags* are as for :meth:`watch_queue`.

        :param fd:
            The file-like object, or fileno to monitor.

        :param callback:
            The function to call when the file has data available.

        :param int flags:
            The condition to monitor on the file (defaults to ``POLLIN``).
        """
        if isinstance(fd, int):
            fd = os.fdopen(fd)
        self._poller.register(fd, flags)
        self._queue_callbacks[fd.fileno()] = callback
        return fd

    def remove_watch_queue(self, handle):
        """
        Remove a queue from background polling. Returns ``True`` if the queue
        was being monitored, ``False`` otherwise.
        """
        try:
            try:
                self._poller.unregister(handle)
            finally:
                self._queue_callbacks.pop(handle, None)
            return True
        except KeyError:
            return False

    def remove_watch_file(self, handle):
        """
        Remove a file from background polling. Returns ``True`` if the file was
        being monitored, ``False`` otherwise.
        """
        try:
            try:
                self._poller.unregister(handle)
            finally:
                self._queue_callbacks.pop(handle.fileno(), None)
            return True
        except KeyError:
            return False

    def enter_idle(self, callback):
        """
        Add a *callback* to be executed when the event loop detects it is idle.
        Returns a handle that may be passed to :meth:`remove_enter_idle`.
        """
        self._idle_handle += 1
        self._idle_callbacks[self._idle_handle] = callback
        return self._idle_handle

    def remove_enter_idle(self, handle):
        """
        Remove an idle callback. Returns ``True`` if *handle* was removed,
        ``False`` otherwise.
        """
        try:
            del self._idle_callbacks[handle]
            return True
        except KeyError:
            return False

    def _entering_idle(self):
        for callback in list(self._idle_callbacks.values()):
            callback()

    def run(self):
        """
        Start the event loop. Exit the loop when any callback raises an
        exception. If :exc:`ExitMainLoop` is raised, exit cleanly.
        """
        try:
            while True:
                try:
                    self._loop()
                except zmq.ZMQError as exc:
                    if exc.errno != errno.EINTR:
                        raise
        except ExitMainLoop:
            pass

    def _loop(self):
        """
        A single iteration of the event loop.
        """
        if self._alarms or self._did_something:
            if self._alarms:
                state = 'alarm'
                timeout = max(0, self._alarms[0][0] - time())
            if self._did_something and (not self._alarms or
                                        (self._alarms and timeout > 0)):
                state = 'idle'
                timeout = 0
            ready = self._poller.poll(timeout * 1000)  # ms
        else:
            state = 'wait'
            ready = self._poller.poll()

        if not ready:
            if state == 'idle':
                self._entering_idle()
                self._did_something = False
            elif state == 'alarm':
                task = heapq.heappop(self._alarms)
                task.callback()
                self._did_something = True

        for queue, _ in ready:
            self._queue_callbacks[queue]()
            self._did_something = True


class SimpleButton(Button):
    """
    Overrides :class:`Button` to enclose the label in [square brackets].
    """
    button_left = Text("[")
    button_right = Text("]")


class FixedButton(SimpleButton):
    """
    A fixed sized, one-line button derived from :class:`SimpleButton`.
    """
    def sizing(self):
        return frozenset(['fixed'])

    def pack(self, size, focus=False):
        # pylint: disable=unused-argument
        return (len(self.get_label()) + 4, 1)


class YesNoDialog(WidgetWrap):
    """
    Wraps a box and buttons to form a simple Yes/No modal dialog. The dialog
    emits signals "yes" and "no" when either button is clicked or when "y" or
    "n" are pressed on the keyboard.
    """
    signals = ['yes', 'no']

    def __init__(self, title, message):
        yes_button = FixedButton('Yes')
        no_button = FixedButton('No')
        connect_signal(yes_button, 'click', lambda btn: self._emit('yes'))
        connect_signal(no_button, 'click', lambda btn: self._emit('no'))
        super().__init__(
            LineBox(
                Pile([
                    ('pack', Text(message)),
                    Filler(
                        Columns([
                            ('pack', AttrMap(yes_button, 'button', 'inv_button')),  # noqa: E501
                            ('pack', AttrMap(no_button, 'button', 'inv_button')),   # noqa: E501
                        ], dividechars=2),
                        valign='bottom'
                    )
                ]),
                title
            )
        )

    def keypress(self, size, key):
        """
        Respond to "y" or "n" on the keyboard as a short-cut to selecting and
        clicking the actual buttons.
        """
        # Urwid does some amusing things with its widget classes which fools
        # pylint's static analysis. The super-method *is* callable here.
        # pylint: disable=not-callable
        key = super().keypress(size, key)
        if isinstance(key, str):
            if key.lower() == 'y':
                self._emit('yes')
            elif key.lower() == 'n':
                self._emit('no')
        return key

    def _get_title(self):
        return self._w.title_widget.text.strip()

    def _set_title(self, value):
        self._w.set_title(value)

    title = property(_get_title, _set_title)
