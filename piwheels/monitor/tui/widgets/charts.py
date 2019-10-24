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

"Defines some simple bar-chart widgets"

from bisect import bisect
from itertools import cycle
from datetime import timedelta

import urwid as ur

from piwheels.format import format_size, format_timedelta


class RatioBar(ur.Widget):
    """
    A variable sized 1-dimensional ratio chart plotting the differing sizes of
    ABI build queues and results. ABIs are displayed in ascending alphabetic
    order with the relative size of each section indicating the proportion of
    that ABI for the metric measured. The overall size is given in absolute
    terms to the right of the chart.
    """
    _sizing = frozenset([ur.FLOW])
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
            return ur.SolidCanvas('-', maxcol, 1)
        total_label = str(self._total)

        bar_len = maxcol - sum(
            len(s) for s in (self.left, self.right, total_label))
        bar_len -= len(self._parts) - 1  # separators
        if bar_len < len(self._parts):
            # Bar is too short to be useful; just display >>>>
            return ur.SolidCanvas('>', maxcol, 1)

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
        text, cs = ur.apply_target_encoding(s)
        return ur.TextCanvas([text], [cs], maxcol=maxcol)


class TrendBar(ur.Widget):
    """
    A variable sized 1-dimensional bar-chart plotting the 1-minute median of a
    metric against its 5-minute median (to indicate direction of movement)
    within a scale either fixed or calculated from the minimum and maximum of
    the data given.
    """
    _sizing = frozenset([ur.FLOW])
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
            return ur.SolidCanvas('-', maxcol, 1)
        min_label = self._format(self._minimum)
        max_label = self._format(self._maximum)

        bar_range = self._maximum - self._minimum
        if not bar_range:
            # Minimum and maximum are equal; display nothing
            return ur.SolidCanvas('-', maxcol, 1)

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
                return ur.SolidCanvas('>', maxcol, 1)

        pre_len = clamp(0, bar_len, round(bar_len * (
            (min(self._recent, self._history) - self._minimum) / bar_range)))
        post_len = clamp(0, bar_len, round(bar_len * (
            (self._maximum - max(self._recent, self._history)) / bar_range)))
        trend_len = bar_len - (pre_len + post_len)
        while trend_len < 0:
            # Can happen by rounding; knock 1 off the first largest value.
            trend_len += 1
            if pre_len >= post_len:
                pre_len -= 1
            else:
                post_len -= 1

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
        text, cs = ur.apply_target_encoding(s)
        return ur.TextCanvas([text], [cs], maxcol=maxcol)
