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
Implements the classes for rendering statistics from master/slave states.

.. autoclass:: Control
    :members:

.. autoclass:: MasterControl
    :members:

.. autoclass:: LastSeenControl
    :members:

.. autoclass:: DiskControl
    :members:

.. autoclass:: SwapControl
    :members:

.. autoclass:: MemControl
    :members:

.. autoclass:: CPUTempControl
    :members:

.. autoclass:: LoadAvgControl
    :members:

.. autoclass:: BuildsQueueControl
    :members:

.. autoclass:: BuildsDoneControl
    :members:

.. autofunction:: slave_stats

.. autofunction:: master_stats

.. autofunction:: clamp

.. autofunction:: gradient
"""

from bisect import bisect
from operator import attrgetter
from datetime import datetime, timedelta, timezone
from itertools import islice

from colorzero import Color

from piwheels.format import format_timedelta


UTC = timezone.utc


def clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def gradient(okay=0.25, warn=0.75, fail=1.0, count=32):
    """
    Generate a gradient of *count* steps representing values between 0.0 and
    1.0. Until the *okay* value, the gradient is pure green. Until the *warn*
    value it gradually fades to orange. As the value approaches *fail*, it
    fades to red, and above *fail* it remains red until the value 1.0.
    """
    warn_gradient = list(Color('green').gradient(Color('orange'), steps=count))
    fail_gradient = list(Color('orange').gradient(Color('red'), steps=count))
    for step in range(count):
        value = step / count
        if value < okay:
            yield Color('green')
        elif value < warn:
            yield warn_gradient[int(count * (value - okay) / (warn - okay))]
        elif value < fail:
            yield fail_gradient[int(count * (value - warn) / (fail - warn))]
        else:
            yield Color('red')


def extract(stats, attr, size_attr=None):
    """
    Extract the named *attr* from *stats*, a sequence of :class:`MasterStats`
    or :class:`SlaveStats` instances returning a generator of ``(timestamp,
    attr)`` pairs. If *size_attr* is specified, returns a generator of
    ``(timestamp, attr/size_attr)`` pairs.
    """
    value = attrgetter(attr)
    if size_attr is None:
        return ((s.timestamp, value(s)) for s in stats)
    else:
        size = attrgetter(size_attr)
        return ((s.timestamp, value(s) / size(s)) for s in stats)


class Control:
    """
    Represents one of the mini stats bars at the top of the main monitor
    screen, or one of the mini controls at the top of the detail screen for
    master or slave nodes.

    All controls have a :attr:`value` (between 0 and 1), a :attr:`color` (used
    to render the control on the SenseHAT pixels), and a :attr:`label`
    (sometimes rendered, depending on context). These attributes are all
    managed by the :meth:`update` method.
    """
    def __init__(self):
        self._state = None
        self._value = None
        self._label = None
        self._color = None

    def activate(self):
        """
        Returns a sequence of actions to carry out when the control is
        activated.
        """
        return ('BACK',)

    def update(self, state):
        """
        Given a *state* which is a :class:`SlaveState` or :class:`MasterState`
        instance, update all the instance attributes.
        """
        pass

    def history(self):
        """
        Yields copies of the control showing its state over successive minutes.

        Note that this method actually just yields the instance with modified
        attributes. Hence, caching the instances yielded will not provide the
        expected result; cache the attributes required instead.
        """
        yield self

    @property
    def value(self):
        """
        The current value of the stat as a floating-point number between 0 and
        1. Note that this is *never* permitted to be :data:`None`.
        """
        return self._value

    @property
    def color(self):
        """
        A color representing the state of the stat (e.g. green for okay, yellow
        for warning, red for a problem).
        """
        return self._color

    @property
    def label(self):
        """
        A textual label representing the value of the stat.
        """
        return self._label


class Label(Control):
    """
    Control with no action or variable color; typically used to display an
    attribute of a node (hostname, OS, etc.)
    """
    def __init__(self, label=''):
        super().__init__()
        self._label = label
        self._color = Color('darkblue')
        self._value = 1


class Action(Control):
    """
    Control for user-executable actions. These controls have a fixed color and
    label; they merely exist to provide controls that the user can activate for
    an effect.
    """
    def __init__(self, label='Action', actions=()):
        super().__init__()
        self._label = label
        self._color = Color('red')
        self._value = 1
        self._actions = tuple(actions)

    def activate(self):
        return self._actions


class Stat(Control):
    """
    Control representing a statistic of a node.

    The parameters (*okay*, *warn*, and *fail*) are used to construct a
    gradient for the stat with the :func:`gradient` function where lower values
    are considered "better" (green) and higher values are "worse" (red).

    Descendents must override :meth:`update` to update :attr:`value`.
    """
    def __init__(self, template='Stat: {}', format='{:.1f}', unknown='?',
                 okay=0.25, warn=0.75, fail=1.0):
        super().__init__()
        self._template = template
        self._format = format
        self._unknown = unknown
        self._gradient = list(gradient(okay, warn, fail))
        assert len(self._gradient) == 32

    def activate(self):
        return ()

    def update(self, state):
        self._state = state
        self.update_from_stat(state.stats[-1] if state.stats else None)

    def update_from_stat(self, stat):
        raw = self.stat_raw(stat)
        self._value = self.stat_value(stat, raw)
        self._label = self.stat_label(stat, raw)
        self._color = self.stat_color(stat, raw)

    def stat_raw(self, stat):
        """
        Stub to be overridden by descendents. Determines the :attr:`raw`
        value of the given *stat*, a :class:`SlaveStat` or :class:`MasterStat`
        instance.
        """
        return 0

    def stat_value(self, stat, raw):
        """
        Determines the :attr:`value` of the given *stat*, a :class:`SlaveStat`
        or :class:`MasterStat` instance.
        """
        return 1 if raw is None else clamp(raw)

    def stat_color(self, stat, raw):
        """
        Determines the :attr:`color` of the given *stat*, a :class:`SlaveStat`
        or :class:`MasterStat` instance.
        """
        if raw is None:
            return Color('#333')
        else:
            return self._gradient[
                int((len(self._gradient) - 1) * self.stat_value(stat, raw))]

    def stat_label(self, stat, raw):
        """
        Determines the :attr:`label` of the given *stat*, a :class:`SlaveStat`
        or :class:`MasterStat` instance.
        """
        if raw is None:
            return self._template.format(self._unknown)
        else:
            return self._template.format(self._format.format(raw))

    @property
    def gradient(self):
        return self._gradient


class HistoryStat(Stat):
    """
    Derivative of :class:`Stat` that provides a history. Descendents must
    override :meth:`stat_value`.
    """
    def activate(self):
        return ('SWITCH',)

    def history(self):
        last = len(self._state.stats)
        timestamps = [s.timestamp for s in self._state.stats]
        latest = timestamps[-1]
        offset = timedelta(0)
        try:
            while True:
                offset += timedelta(minutes=1)
                index = bisect(timestamps[:last], latest - offset)
                if index == last:
                    break
                # Can't slice a deque; use rotate instead
                self._state.stats.rotate(-index)
                stats = sorted(islice(self._state.stats, last - index),
                               key=lambda stat:
                               self.stat_value(stat, self.stat_raw(stat)))
                self.update_from_stat(stats[len(stats) // 2])
                self._state.stats.rotate(index)
                yield self
                last = index
        finally:
            self.update_from_stat(
                self._state.stats[-1] if self._state.stats else None)


class Skip(Action):
    def __init__(self):
        super().__init__('Skip', actions=['SKIP', 'BACK'])


class Pause(Action):
    def __init__(self):
        super().__init__('Pause', actions=['SLEEP', 'BACK'])


class Halt(Action):
    def __init__(self):
        super().__init__('Halt', actions=['SLEEP', 'SKIP', 'BACK'])


class Resume(Action):
    def __init__(self):
        super().__init__('Resume', actions=['WAKE', 'BACK'])


class StopSlave(Action):
    def __init__(self):
        super().__init__('Stop Slave', actions=['KILL', 'BACK'])


class StopSlaves(Action):
    def __init__(self):
        super().__init__('Stop Slaves', actions=['KILL', 'BACK'])


class KillSlave(Action):
    def __init__(self):
        super().__init__('Kill Slave', actions=['KILL', 'SKIP', 'BACK'])


class KillSlaves(Action):
    def __init__(self):
        super().__init__('Kill Slaves', actions=['KILL', 'SKIP', 'BACK'])


class StopMaster(Action):
    def __init__(self):
        super().__init__('Stop Master', actions=['QUIT', 'BACK'])


class Placeholder(Label):
    """
    Placeholder control. This is used when no node is selected, or as a filler
    control in the stats-bar at the top of the screen.
    """
    def __init__(self):
        super().__init__('')
        self._color = Color('#333')


class LastSeen(Stat):
    "Represents the time since the last message."
    def __init__(self):
        super().__init__(template='Last Seen: {}', format='{:.1f}s')

    def stat_raw(self, stat):
        if self._state.last_seen is not None:
            last_seen = datetime.now(tz=UTC) - self._state.last_seen
            return last_seen.total_seconds()

    def stat_value(self, stat, raw):
        return 1 if raw is None else clamp(raw / 30)


class Disk(HistoryStat):
    "Represents the disk usage."
    def __init__(self):
        super().__init__(template='Disk: {}', format='{:.1f}% full',
                         okay=0.5, fail=0.9)

    def stat_raw(self, stat):
        if stat and stat.disk_size:
            return 1 - (stat.disk_free / stat.disk_size)

    def stat_label(self, stat, raw):
        return super().stat_label(stat, None if raw is None else raw * 100)


class Swap(HistoryStat):
    "Represents the swap usage."
    def __init__(self):
        super().__init__(template='Swap: {}', format='{:.1f}% full',
                         okay=0.0, warn=0.25, fail=0.5)

    def stat_raw(self, stat):
        if stat and stat.swap_size:
            return 1 - (stat.swap_free / stat.swap_size)

    def stat_label(self, stat, raw):
        return super().stat_label(stat, None if raw is None else raw * 100)


class Mem(HistoryStat):
    "Represents the RAM usage."
    def __init__(self):
        super().__init__(template='Mem: {}', format='{:.1f}% full')

    def stat_raw(self, stat):
        if stat and stat.mem_size:
            return 1 - (stat.mem_free / stat.mem_size)

    def stat_label(self, stat, raw):
        return super().stat_label(stat, None if raw is None else raw * 100)


class CPUTemp(HistoryStat):
    "Represents the CPU temperature."
    def __init__(self):
        super().__init__(template='CPU: {}', format='{:.1f}°C',
                         okay=0.6, warn=0.7, fail=0.8)

    def stat_raw(self, stat):
        if stat:
            return stat.cpu_temp / 100


class LoadAvg(HistoryStat):
    "Represents the 1-minute load average."
    def __init__(self):
        super().__init__(template='Load: {}')

    def stat_raw(self, stat):
        # XXX Hard-coded 4...
        if stat:
            return stat.load_average / 4.0


class ClockSkew(Stat):
    "Represents the node's clock delta to the master."
    def stat_raw(self, stat):
        if self._state.clock_skew is not None:
            return self._state.clock_skew

    def stat_value(self, stat, raw):
        return 1 if raw is None else clamp(raw / timedelta(seconds=4))

    def stat_label(self, stat, raw):
        if raw is None:
            return 'Time Skew: ?'
        else:
            return 'Time Skew: {}'.format(format_timedelta(raw))


class BuildTime(Stat):
    "Represents the node's build duration."
    def __init__(self):
        super().__init__(okay=0.08, warn=0.33)

    def stat_raw(self, stat):
        if self._state.build_start is not None:
            return datetime.now(tz=UTC) - self._state.build_start

    def stat_value(self, stat, raw):
        return 1 if raw is None else clamp(raw / timedelta(hours=3))

    def stat_label(self, stat, raw):
        if raw is None:
            return 'No build'
        else:
            return 'Build Time: {}'.format(format_timedelta(raw))


class BuildsQueue(HistoryStat):
    "Represents the size of the pending build queue."
    def __init__(self):
        super().__init__(template='Pending: {}', format='{:d}')

    def stat_raw(self, stat):
        if stat is not None:
            return sum(stat.builds_pending.values())

    def stat_value(self, stat, raw):
        return 1 if raw is None else clamp(raw / 100)


class BuildsDone(Stat):
    "Represents the number of builds produced in the last hour."
    def __init__(self):
        super().__init__(template='Built/Hr: {}', format='{:d}')

    def stat_raw(self, stat):
        if stat:
            return sum(stat.builds_last_hour.values())

    def stat_value(self, stat, raw):
        return 1 if raw is None else clamp((100 - raw) / 100)


class Activity(Label):
    "Represents the current activity of the node."
    def update(self, state):
        super().update(state)
        self._label = state.status
        self._color = state.color


class Host(Label):
    "Represents the node's hostname."
    def update(self, state):
        super().update(state)
        self._label = 'Label: {}'.format(state.label)


class ABI(Label):
    "Represents the node's ABI and CPython version."
    def update(self, state):
        super().update(state)
        self._label = 'ABI: {}'.format(state.abi)


class Board(Label):
    "Represents the node's board revision and serial #."
    def update(self, state):
        super().update(state)
        self._label = 'Board: {}'.format(state.board_revision)


class Serial(Label):
    "Represents the node's serial #."
    def update(self, state):
        super().update(state)
        self._label = 'Serial: {}'.format(state.board_serial)


class OS(Label):
    "Represents the node's OS name and version."
    def update(self, state):
        super().update(state)
        self._label = 'OS: {} {}'.format(state.os_name, state.os_version)


class UpTime(Label):
    "Represents the node's uptime."
    def update(self, state):
        super().update(state)
        self._label = 'Uptime: {}'.format(
            format_timedelta(datetime.now(tz=UTC) - state.first_seen))
