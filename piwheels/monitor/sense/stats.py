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

.. autoclass:: Stat
    :members:

.. autoclass:: MasterStat
    :members:

.. autoclass:: LastSeenStat
    :members:

.. autoclass:: DiskStat
    :members:

.. autoclass:: SwapStat
    :members:

.. autoclass:: MemStat
    :members:

.. autoclass:: CPUTempStat
    :members:

.. autoclass:: LoadAvgStat
    :members:

.. autoclass:: BuildsQueueStat
    :members:

.. autoclass:: BuildsDoneStat
    :members:

.. autofunction:: slave_stats

.. autofunction:: master_stats

.. autofunction:: clamp

.. autofunction:: gradient
"""

from datetime import datetime, timedelta, timezone

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


class Stat:
    """
    Represents one of the mini statistics bars at the top of the monitor
    screen.

    The parameters (*okay*, *warn*, and *fail*) are used to construct a
    gradient for the bar with the :func:`gradient` function. Descendents must
    override the :meth:`calc` method to fill out the instance attributes.
    """
    def __init__(self, okay=0.25, warn=0.75, fail=1.0):
        self._state = None
        self._value = None
        self._label = None
        self._color = None
        self.gradient = list(gradient(okay, warn, fail))
        assert len(self.gradient) == 32

    def calc(self, state):
        self._state = state
        if self._value is None:
            self._color = Color('#333')
        else:
            self._color = self.gradient[
                int((len(self.gradient) - 1) * self._value)]

    @property
    def value(self):
        return 1 if self._value is None else self._value

    @property
    def color(self):
        return self._color

    @property
    def label(self):
        return self._label


class NullStat(Stat):
    "Placeholder for no stats."
    def calc(self, state):
        self._label = '?'
        self._value = None
        super().calc(state)


class LastSeenStat(Stat):
    "Represents the time since the last message."
    def calc(self, state):
        if state.last_seen is None:
            self._value = 1
            self._label = 'Last Seen: ?'
        else:
            last_seen = datetime.now(tz=UTC) - state.last_seen
            self._value = clamp(last_seen / timedelta(seconds=30))
            self._label = 'Last Seen: {:.1f}s'.format(last_seen.total_seconds())
        super().calc(state)


class DiskStat(Stat):
    "Represents the disk usage."
    def __init__(self):
        super().__init__(okay=0.5, fail=0.9)

    def calc(self, state):
        if state.stats and state.stats[-1].disk_size:
            self._value = (
                1 - (state.stats[-1].disk_free /
                     state.stats[-1].disk_size))
            self._label = 'Disk Used: {:.1f}%'.format(self._value * 100)
        else:
            self._value = None
            self._label = 'Disk Used: ?'
        super().calc(state)


class SwapStat(Stat):
    "Represents the swap usage."
    def __init__(self):
        super().__init__(okay=0.0, warn=0.25, fail=0.5)

    def calc(self, state):
        if state.stats and state.stats[-1].swap_free:
            self._value = (
                1 - (state.stats[-1].swap_free /
                     state.stats[-1].swap_free))
            self._label = 'Swap Used: {:.1f}%'.format(self._value * 100)
        else:
            self._value = None
            self._label = 'Swap Used: ?'
        super().calc(state)


class MemStat(Stat):
    "Represents the RAM usage."
    def calc(self, state):
        if state.stats and state.stats[-1].mem_free:
            self._value = (
                1 - (state.stats[-1].mem_free /
                     state.stats[-1].mem_free))
            self._label = 'Mem Used: {:.1f}%'.format(self._value * 100)
        else:
            self._value = None
            self._label = 'Mem Used: ?'
        super().calc(state)


class CPUTempStat(Stat):
    "Represents the CPU temperature."
    def __init__(self):
        super().__init__(okay=0.6, warn=0.7, fail=0.8)

    def calc(self, state):
        if state.stats:
            self._value = clamp(state.stats[-1].cpu_temp / 100)
            self._label = 'CPU Temp.: {:.1f}°C'.format(state.stats[-1].cpu_temp)
        else:
            self._value = None
            self._label = 'CPU Temp: ?'
        super().calc(state)


class LoadAvgStat(Stat):
    "Represents the 1-minute load average."
    def calc(self, state):
        if state.stats:
            self._value = clamp(state.stats[-1].load_average / 4.0)
            self._label = 'Load Avg: {:.1f}'.format(state.stats[-1].load_average)
        else:
            self._value = None
            self._label = 'Load Avg: ?'
        super().calc(state)


class ClockSkewStat(Stat):
    "Represents the node's clock delta to the master."
    def calc(self, state):
        if state.clock_skew:
            self._value = clamp(state.clock_skew / timedelta(seconds=4))
            self._label = 'Clock Skew: {}'.format(
                format_timedelta(state.clock_skew))
        else:
            self._value = None
            self._label = 'Clock Skew: ?'
        super().calc(state)


class BuildTimeStat(Stat):
    "Represents the node's build duration."
    def __init__(self):
        super().__init__(okay=0.08, warn=0.33)

    def calc(self, state):
        if state.build_start:
            build_time = datetime.now(tz=UTC) - state.build_start
            self._value = clamp(build_time / timedelta(hours=3))
            self._label = 'Build Time: {}'.format(format_timedelta(build_time))
        else:
            self._value = None
            self._label = 'No build'
        super().calc(state)


class BuildsQueueStat(Stat):
    "Represents the size of the pending build queue."
    def calc(self, state):
        if state.stats:
            pending = sum(state.stats[-1].builds_pending.values())
            self._value = clamp(pending / 100)
            self._label = 'Pending: {:d}'.format(pending)
        else:
            self._value = None
            self._label = 'Pending: ?'
        super().calc(state)


class BuildsDoneStat(Stat):
    "Represents the number of builds produced in the last hour."
    def calc(self, state):
        if state.stats:
            built = sum(state.stats[-1].builds_last_hour.values())
            self._value = clamp((100 - built) / 100)
            self._label = 'Built/Hr: {:d}'.format(built)
        else:
            self._value = None
            self._label = 'Built/Hr: ?'
        super().calc(state)


class ActivityStat(Stat):
    "Represents the current activity of the node."
    def calc(self, state):
        super().calc(state)
        self._label = state.status
        self._color = state.color


class HostStat(Stat):
    "Represents the node's hostname."
    def calc(self, state):
        super().calc(state)
        self._label = state.label
        self._color = Color('darkblue')


class ABIStat(Stat):
    "Represents the node's ABI and CPython version."
    def calc(self, state):
        super().calc(state)
        self._label = '{} ({})'.format(state.abi, state.py_version)
        self._color = Color('darkblue')


class BoardStat(Stat):
    "Represents the node's board revision and serial #."
    def calc(self, state):
        super().calc(state)
        self._label = state.board_revision
        self._color = Color('darkblue')


class SerialStat(Stat):
    "Represents the node's serial #."
    def calc(self, state):
        super().calc(state)
        self._label = 'S#: {}'.format(state.board_serial)
        self._color = Color('darkblue')


class OSStat(Stat):
    "Represents the node's OS name and version."
    def calc(self, state):
        super().calc(state)
        self._label = '{} {}'.format(state.os_name, state.os_version)
        self._color = Color('darkblue')


class UpTimeStat(Stat):
    "Represents the node's uptime."
    def calc(self, state):
        super().calc(state)
        self._label = 'Uptime: {}'.format(
            format_timedelta(datetime.now(tz=UTC) - state.first_seen))
        self._color = Color('darkblue')
