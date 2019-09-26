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
import signal
from time import time
from bisect import bisect
from itertools import count, cycle
from datetime import datetime, timedelta
from collections import namedtuple
from operator import attrgetter

# This module is a one-stop shop for all the monitor's widget needs, hence all
# the unused imports
# pylint: disable=unused-import

from urwid import (
    connect_signal,
    apply_target_encoding,
    Widget,
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
    SolidFill,
    ListBox,
    Overlay,
    ProgressBar,
    ListWalker,
    MainLoop,
    ExitMainLoop,
    SolidCanvas,
    TextCanvas,
    FLOW,
)

try:
    from urwid import EventLoop
except ImportError:
    # Use a compatbile EventLoop base class with urwid <2.x
    class EventLoop:
        def alarm(self, seconds, callback):
            raise NotImplementedError()

        def enter_idle(self, callback):
            raise NotImplementedError()

        def remove_alarm(self, handler):
            raise NotImplementedError()

        def remove_enter_idle(self, handle):
            raise NotImplementedError()

        def remove_watch_file(self, handle):
            raise NotImplementedError()

        def run(self):
            raise NotImplementedError()

        def watch_file(self, fd, callback):
            raise NotImplementedError()

        def set_signal_handler(self, signum, handler):
            return signal.signal(signum, handler)

from .. import transport
from ..format import format_size, format_timedelta


# Stop the relentless march against nicely aligned code
# pylint: disable=bad-whitespace

PALETTE = [
    ('idle',        'dark gray',       'default'),
    ('building',    'light green',     'default'),
    ('sending',     'light blue',      'default'),
    ('cleaning',    'light magenta',   'default'),
    ('silent',      'yellow',          'default'),
    ('dead',        'light red',       'default'),

    ('time',        'light gray',      'default'),
    ('status',      'light gray',      'default'),
    ('hotkey',      'light cyan',      'dark blue'),
    ('normal',      'light gray',      'default'),
    ('todo',        'white',           'dark blue'),
    ('done',        'black',           'light gray'),
    ('todo_smooth', 'dark blue',       'light gray'),
    ('header',      'light gray',      'dark blue'),
    ('footer',      'dark blue',       'default'),

    ('dialog',      'light gray',      'dark blue'),
    ('button',      'light gray',      'dark blue'),
    ('coltrans',    'dark cyan',       'dark blue'),
    ('colheader',   'black',           'dark cyan'),
    ('inv_dialog',  'dark blue',       'light gray'),
    ('inv_normal',  'black',           'light gray'),
    ('inv_hotkey',  'dark cyan',       'light gray'),
    ('inv_button',  'black',           'light gray'),
    ('inv_status',  'black',           'light gray'),
]


AlarmTask = namedtuple('AlarmTask', ('due', 'tie_break', 'callback'))


class ZMQEventLoop(EventLoop):
    """
    This class is an urwid event loop for zmq applications. It supports the
    usual alarm events and file watching capabilities, but also incorporates
    the ability to watch zmq queues for events.
    """
    _alarm_break = count()

    def __init__(self):
        self._did_something = True
        self._alarms = []
        self._poller = transport.Poller()
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

    def watch_queue(self, queue, callback, flags=transport.POLLIN):
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

    def watch_file(self, fd, callback, flags=transport.POLLIN):
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
                except transport.Error as exc:
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
            ready = self._poller.poll(timeout)
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

        for queue, _ in ready.items():
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


class RatioBar(Widget):
    """
    A variable sized 1-dimensional ratio chart plotting the differing sizes of
    ABI build queues and results. ABIs are displayed in ascending alphabetic
    order with the relative size of each section indicating the proportion of
    that ABI for the metric measured. The overall size is given in absolute
    terms to the right of the chart.
    """
    _sizing = frozenset([FLOW])
    ignore_focus = True

    def __init__(self, left='[', right='] ', bar='=', sep='/'):
        super().__init__()
        self.left = left
        self.right = right
        self.bar = bar
        self.sep = sep
        self._parts = None
        self._total = None

    def rows(self, size, focus=False):
        return 1

    def update(self, stats):
        """
        Update the chart with current *stats* which is assumed to be a dict
        mapping ABI names to their absolute size.
        """
        self._total = sum(stats.values())
        self._parts = [(abi, n) for abi, n in sorted(stats.items())]
        self._invalidate()

    def render(self, size, focus=False):
        (maxcol,) = size
        if not self._total:
            return SolidCanvas('-', maxcol, 1)
        total_label = str(self._total)

        bar_len = maxcol - sum(
            len(s) for s in (self.left, self.right, total_label))
        bar_len -= len(self._parts) - 1  # separators
        if bar_len < len(self._parts):
            # Bar is too short to be useful; just display >>>>
            return SolidCanvas('>', maxcol, 1)

        part_lens = [round(bar_len * n / self._total) for abi, n in self._parts]
        if sum(part_lens) > bar_len:
            longest_ix = part_lens.index(max(part_lens))
            part_lens[longest_ix] -= 1
        assert sum(part_lens) == bar_len

        bar = self.sep.join(
            '{0:{fill}^{width}}'.format(abi, fill=bar_char, width=part_len)
            if len(abi) + 2 <= part_len else bar_char * part_len
            for (abi, count), part_len, bar_char
            in zip(self._parts, part_lens, cycle(self.bar))
        )
        s = ''.join((self.left, bar, self.right, total_label))
        text, cs = apply_target_encoding(s)
        return TextCanvas([text], [cs], maxcol=maxcol)


class TrendBar(Widget):
    """
    A variable sized 1-dimensional bar-chart plotting the 1-minute median of a
    metric against its 5-minute median (to indicate direction of movement)
    within a scale either fixed or calculated from the minimum and maximum of
    the data given.
    """
    _sizing = frozenset([FLOW])
    ignore_focus = True

    def __init__(self, minimum=None, maximum=None, format=str, left=' [',
                 right='] ', back=' ', fore='=', rising='>', falling='<',
                 current='.', show_current=False,
                 recent_period=timedelta(minutes=1),
                 history_period=timedelta(minutes=5)):
        if not (len(back) == len(fore) == len(rising) == len(falling) == len(current)):
            raise ValueError('back, fore, rising, falling, and current must '
                             'have equal length')
        super().__init__()
        self.minimum = minimum
        self.maximum = maximum
        self.left = left
        self.right = right
        self.back = back
        self.fore = fore
        self.rising = rising
        self.falling = falling
        self.current = current
        self.show_current = show_current
        self.recent_period = recent_period
        self.history_period = history_period
        self._format = format
        self._minimum = None
        self._maximum = None
        self._history = None
        self._recent = None
        self._latest = None

    def rows(self, size, focus=False):
        return 1

    def update(self, stats):
        """
        Update the graph with current *stats* which is assumed to be a list
        of (timestamp, reading) tuples in ascending timestamp order.
        """
        if stats:
            # Calculate the overall minimum and maximum of all available stats,
            # then the median of the history range (e.g. last 5 minutes) and
            # the median of the recent range (e.g. last minute)
            timestamps, readings = zip(*stats)
            self._latest = readings[-1]
            values = sorted(readings)
            self._minimum = values[0]  if self.minimum is None else self.minimum
            self._maximum = values[-1] if self.maximum is None else self.maximum
            assert self._maximum >= self._minimum
            values = sorted(
                readings[bisect(timestamps, timestamps[-1] - self.history_period):])
            # Okay, the median_high really ... good enough
            self._history = values[len(values) // 2]
            values = sorted(
                readings[bisect(timestamps, timestamps[-1] - self.recent_period):])
            self._recent = values[len(values) // 2]
        else:
            self._minimum = self._maximum = self._history = self._recent = None
        self._invalidate()

    def render(self, size, focus=False):
        clamp = lambda _min, _max, v: min(_max, max(_min, v))

        (maxcol,) = size
        if self._recent is None:
            # No data; display nothing
            return SolidCanvas('-', maxcol, 1)
        min_label = self._format(self._minimum)
        max_label = self._format(self._maximum)

        bar_range = self._maximum - self._minimum
        if not bar_range:
            # Minimum and maximum are equal; display nothing
            return SolidCanvas('-', maxcol, 1)

        while True:
            bar_len = maxcol - sum(
                len(s) for s in (min_label, self.left, self.right, max_label))
            bar_len //= len(self.back)
            if bar_len > 4:
                break
            else:
                # Bar is too short to be useful; if the minimum and maximum are
                # trivial attempt to eliminate their labels and if this isn't
                # enough just display >>>>
                if self._minimum == 0:
                    if min_label != '':
                        min_label = ''
                        continue
                    elif self._maximum in (1, 100) and max_label != '':
                        max_label = ''
                        continue
                return SolidCanvas('>', maxcol, 1)

        pre_len = clamp(0, bar_len, round(bar_len * (
            (min(self._recent, self._history) - self._minimum) / bar_range)))
        post_len = clamp(0, bar_len, round(bar_len * (
            (self._maximum - max(self._recent, self._history)) / bar_range)))
        trend_len = bar_len - (pre_len + post_len)
        assert trend_len >= 0

        s = ''.join((
            self.fore * pre_len,
            (
                self.falling if self._recent < self._history else
                self.rising if self._recent > self._history else
                self.fore) * trend_len,
            self.back * post_len,
        ))
        if self.show_current:
            latest_pos = clamp(0, bar_len - 1, round(bar_len * (
                (self._latest - self._minimum) / bar_range)))
            s = s[:latest_pos] + self.current + s[latest_pos + 1:]
        s = ''.join((min_label, self.left, s, self.right, max_label))
        text, cs = apply_target_encoding(s)
        return TextCanvas([text], [cs], maxcol=maxcol)


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
                            ('pack', AttrMap(yes_button, 'button', 'inv_button')),
                            ('pack', AttrMap(no_button, 'button', 'inv_button')),
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


class MasterStatsBox(WidgetWrap):
    def __init__(self):
        self.board_label = Text('-')
        self.serial_label = Text('-')
        self.os_label = Text('-')
        self.load_bar = TrendBar(
            minimum=0.0, format=lambda x: '{:.3g}'.format(x))
        self.temperature_bar = TrendBar(
            minimum=40, maximum=100, format=lambda x: '{:.3g}°C'.format(x),
            show_current=True)
        self.disk_bar = TrendBar(minimum=0, format=format_size)
        self.swap_bar = TrendBar(minimum=0, format=format_size)
        self.memory_bar = TrendBar(minimum=0, format=format_size)
        self.builds_bar = RatioBar()
        self.queue_bar = RatioBar()
        self.downloads_bar = TrendBar(minimum=0)
        self.builds_size_label = Text('-')
        self.builds_time_label = Text('-')
        self.files_count_label = Text('-')
        super().__init__(
            AttrMap(
                LineBox(
                    Columns([
                        (12, Pile([
                            Text('Board'),
                            Text('Serial #'),
                            Text('OS'),
                            Text('Build Size'),
                            Text('Build Time'),
                            Text('File Count'),
                            Text('Queue'),
                        ])),
                        Pile([
                            self.board_label,
                            self.serial_label,
                            self.os_label,
                            self.builds_size_label,
                            self.builds_time_label,
                            self.files_count_label,
                            self.queue_bar,
                        ]),
                        (12, Pile([
                            Text('Temperature'),
                            Text('Load Avg'),
                            Text('Disk'),
                            Text('Swap'),
                            Text('Memory'),
                            Text('Downloads/hr'),
                            Text('Builds/hr'),
                        ])),
                        Pile([
                            self.temperature_bar,
                            self.load_bar,
                            self.disk_bar,
                            self.swap_bar,
                            self.memory_bar,
                            self.downloads_bar,
                            self.builds_bar,
                        ]),
                    ], dividechars=1),
                ),
                'header',
            )
        )

    def update(self, state):
        self.board_label.set_text(state.board_revision)
        self.serial_label.set_text(state.board_serial)
        self.os_label.set_text('{} {}'.format(state.os_name, state.os_version))
        if not state.stats:
            self.disk_bar.update(())
            self.swap_bar.update(())
            self.memory_bar.update(())
            self.queue_bar.update({})
            self.builds_bar.update({})
            self.downloads_bar.update(())
            self.load_bar.update(())
            self.temperature_bar.update(())
            self.builds_size_label.set_text('-')
            self.builds_time_label.set_text('-')
            self.files_count_label.set_text('-')
        else:
            latest = state.stats[-1]
            self.disk_bar.maximum = latest.disk_size
            self.swap_bar.maximum = latest.swap_size
            self.memory_bar.maximum = latest.mem_size
            self.disk_bar.update(invert(state.stats, 'disk_free', 'disk_size'))
            self.swap_bar.update(invert(state.stats, 'swap_free', 'swap_size'))
            self.memory_bar.update(invert(state.stats, 'mem_free', 'mem_size'))
            self.queue_bar.update(state.stats[-1].builds_pending)
            self.builds_bar.update(state.stats[-1].builds_last_hour)
            self.downloads_bar.update(extract(state.stats, 'downloads_last_hour'))
            self.load_bar.update(extract(state.stats, 'load_average'))
            self.temperature_bar.update(extract(state.stats, 'cpu_temp'))
            self.builds_size_label.set_text(format_size(latest.builds_size))
            self.builds_time_label.set_text(format_timedelta(latest.builds_time))
            self.files_count_label.set_text('{:,}'.format(latest.files_count))


class SlaveStatsBox(WidgetWrap):
    def __init__(self):
        self.board_label = Text('-')
        self.serial_label = Text('-')
        self.python_label = Text('-')
        self.os_label = Text('-')
        self.clock_label = Text('-')
        self.load_bar = TrendBar(
            minimum=0.0, format=lambda x: '{:.3g}'.format(x))
        self.temperature_bar = TrendBar(
            minimum=40, maximum=100, format=lambda x: '{:.3g}°C'.format(x),
            show_current=True)
        self.disk_bar = TrendBar(minimum=0, format=format_size)
        self.swap_bar = TrendBar(minimum=0, format=format_size)
        self.memory_bar = TrendBar(minimum=0, format=format_size)
        super().__init__(
            AttrMap(
                LineBox(
                    Columns([
                        (11, Pile([
                            Text('Board'),
                            Text('Serial #'),
                            Text('OS'),
                            Text('Python'),
                            Text('Clock Delta'),
                        ])),
                        Pile([
                            self.board_label,
                            self.serial_label,
                            self.os_label,
                            self.python_label,
                            self.clock_label,
                        ]),
                        (11, Pile([
                            Text('Temperature'),
                            Text('Load Avg'),
                            Text('Disk'),
                            Text('Swap'),
                            Text('Memory'),
                        ])),
                        Pile([
                            self.temperature_bar,
                            self.load_bar,
                            self.disk_bar,
                            self.swap_bar,
                            self.memory_bar,
                        ]),
                    ], dividechars=1)
                ),
                'header'
            )
        )

    def update(self, state):
        self.board_label.set_text(state.board_revision)
        self.serial_label.set_text(state.board_serial)
        self.os_label.set_text('{} {}'.format(state.os_name, state.os_version))
        self.python_label.set_text('{} (on {})'.format(
            state.py_version, state.platform))
        if not state.stats:
            self.clock_label.set_text('-')
            self.disk_bar.update(())
            self.swap_bar.update(())
            self.memory_bar.update(())
            self.load_bar.update(())
            self.temperature_bar.update(())
        else:
            self.clock_label.set_text(format_timedelta(state.clock_skew))
            latest = state.stats[-1]
            self.disk_bar.maximum = latest.disk_size
            self.swap_bar.maximum = latest.swap_size
            self.memory_bar.maximum = latest.mem_size
            self.disk_bar.update(invert(state.stats, 'disk_free', 'disk_size'))
            self.swap_bar.update(invert(state.stats, 'swap_free', 'swap_size'))
            self.memory_bar.update(invert(state.stats, 'mem_free', 'mem_size'))
            self.load_bar.update(extract(state.stats, 'load_average'))
            self.temperature_bar.update(extract(state.stats, 'cpu_temp'))


def extract(stats, attr):
    """
    Extract the named *attr* from *stats*, a sequence of :class:`MasterStats`
    or :class:`SlaveStats` instances returning a generator of ``(timestamp,
    attr)`` pairs.
    """
    value = attrgetter(attr)
    return ((s.timestamp, value(s)) for s in stats)


def invert(stats, attr, size_attr):
    """
    Similar to :func:`extract` this returns the named *attr* from *stats*, a
    sequence of :class:`MasterStats` or :class:`SlaveStats` instances. However,
    rather than returning the value of *attr* verbatim, it returns the result
    of subtracting *attr* from *size_attr*. This can be used to return usage of
    a resource from its free value, for instance.
    """
    value = attrgetter(attr)
    size = attrgetter(size_attr)
    return ((s.timestamp, size(s) - value(s)) for s in stats)
