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
Implements the screen rendering classes for the Sense HAT monitor.

.. autoclass:: Renderer
    :members:

.. autoclass:: MainRenderer
    :members:

.. autoclass:: MasterRenderer
    :members:

.. autoclass:: SlaveRenderer
    :members:

.. autoclass:: QuitRenderer
    :members:

.. autofunction:: bounce
"""

import signal
import subprocess
from datetime import datetime, timedelta, timezone
from itertools import cycle, chain
from threading import main_thread
from contextlib import contextmanager

import numpy as np
from pisense import array, draw_text
from colorzero import Color, Lightness, ease_out

from piwheels.format import format_size
from .states import SlaveList, MasterState, SlaveState
from . import stats


UTC = timezone.utc


def bounce(it):
    # bounce('ABC') -> A B C C B A A B C ...
    return cycle(chain(it, reversed(it)))


class Renderer:
    """
    Base class for all renderers. A renderer acts as an iterator, yielding
    images (or arrays, or anything that can be passed to one of the screen
    methods). Renderers also have a :meth:`move` method which is used by the
    owning task to pass along joystick events to the renderer.

    The base implementation provides a simple joystick-based navigation
    implementation, and limits its coordinates to a specified boundary.
    """
    def __init__(self):
        self.position = (0, 0)
        self.limits = (0, 0, 7, 7)

    def __iter__(self):
        pass

    def move(self, event, task):
        x, y = self.position
        x_min, y_min, x_max, y_max = self.limits
        if event.direction == 'up':
            x, y = (x, max(y_min, y - 1))
        elif event.direction == 'down':
            x, y = (x, min(y_max, y + 1))
        elif event.direction == 'left':
            x, y = (max(x_min, x - 1), y)
        elif event.direction == 'right':
            x, y = (min(x_max, x + 1), y)
        delta = (x - self.position[0], y - self.position[1])
        self.position = x, y
        return delta


class MainRenderer(Renderer):
    """
    The :class:`MainRenderer` is responsible for rendering the main screen in
    the application (the first screen shown on start).

    It consists of eight small horizontally arranged bar charts at the top of
    the screen. These indicate, in order: time since last ping, disk used, swap
    used, memory used, SoC temperature, load average, queue size, and inverted
    build rate.

    The status of each slave is depicted as a single pixel below these three
    rows.
    """
    def __init__(self):
        super().__init__()
        self.connected = False
        self.position = (0, 3)
        self.limits = (0, 3, 7, 7)
        self.slaves = SlaveList()
        self.stats = None
        self._make_stats(self.selected)

    @staticmethod
    def _slave_coords(index):
        return (index // 5, 3 + index % 5)

    @staticmethod
    def _slave_index(x, y):
        return (x * 5) + (y - 3)

    @property
    def selected(self):
        try:
            return self.slaves[self._slave_index(*self.position)]
        except IndexError:
            return None

    @contextmanager
    def watch_selection(self):
        before = self.selected
        yield
        after = self.selected
        if before != after:
            self._make_stats(after)

    def _make_stats(self, state):
        if isinstance(state, MasterState):
            self.stats = [
                stats.LastSeenStat(),
                stats.BuildsQueueStat(),
                stats.DiskStat(),
                stats.SwapStat(),
                stats.MemStat(),
                stats.CPUTempStat(),
                stats.LoadAvgStat(),
                stats.BuildsDoneStat(),
            ]
        elif isinstance(state, SlaveState):
            self.stats = [
                stats.LastSeenStat(),
                stats.BuildTimeStat(),
                stats.DiskStat(),
                stats.SwapStat(),
                stats.MemStat(),
                stats.CPUTempStat(),
                stats.LoadAvgStat(),
                stats.ClockSkewStat(),
            ]
        else:
            assert state is None
            self.stats = [stats.NullStat()] * 8
        self._refresh_stats(state)

    def _refresh_stats(self, state):
        for stat in self.stats:
            stat.calc(state)

    def message(self, msg, data):
        if msg in ('HELLO', 'STATS'):
            slave_id = None
            timestamp = datetime.now(tz=UTC)
            if msg == 'HELLO':
                self.connected = True
        elif msg == 'SLAVE':
            slave_id, timestamp, msg, data = data
        with self.watch_selection():
            self.slaves.message(slave_id, timestamp, msg, data)
        if self.selected is not None and self.selected.slave_id == slave_id:
            self._refresh_stats(self.selected)

    def move(self, event, task):
        if not self.connected:
            return (0, 0)
        elif event.direction == 'up' and self.position[1] == 3:
            # Go to HelpRenderer
            return (0, 0)
        elif event.direction == 'down' and self.position[1] == 7:
            task.switch_to(task.renderers['quit'], transition='slide',
                           direction='up', duration=0.5)
            return (0, 0)
        else:
            with self.watch_selection():
                delta = super().move(event, task)
            if event.direction == 'enter' and self.selected is not None:
                if isinstance(self.selected, MasterState):
                    task.switch_to(MasterRenderer(self.selected),
                                   transition='slide', direction='right',
                                   cover=True, duration=0.5)
                else:
                    task.switch_to(SlaveRenderer(self.selected),
                                   transition='slide', direction='right',
                                   cover=True, duration=0.5)
            return delta

    def _render_stats(self, buf):
        for x, stat in enumerate(self.stats):
            # Scale the value to a range of 2, with an offset of 1
            # to ensure that the status line is never black
            value = (stat.value * 2) + 1
            buf[0:3, x] = [
                stat.color if y < int(value) else
                stat.color * Lightness(value - int(value)) if y < value else
                Color('black')
                for y in range(3)
            ][::-1]

    def _render_slaves(self, buf, pulse):
        for index, slave in enumerate(self.slaves):
            x, y = self._slave_coords(index)
            if 0 <= x < 8 and 0 <= y < 8:
                buf[y, x] = slave.color
        x, y = self.position
        base = Color(*buf[y, x])
        grad = list(base.gradient(Color('white'), steps=15))
        buf[y, x] = grad[pulse]

    def __iter__(self):
        waiting = array(
            draw_text('Waiting for connection', padding=(8, 0, 8, 1)))
        for offset in cycle(range(waiting.shape[1] - 8)):
            if self.connected:
                break
            yield waiting[:, offset:offset + 8]

        buf = array(Color('black'))
        pulse = iter(bounce(range(15)))
        while True:
            x, y = self.position
            with self.watch_selection():
                self.slaves.prune()
            buf[:] = Color('black')
            self._render_stats(buf)
            self._render_slaves(buf, next(pulse))
            yield buf


class MasterRenderer(Renderer):
    """
    The :class:`MasterRenderer` is used to render the full-screen status of the
    master node (when selected from the main menu). Various screens are
    included, detailing the master's statistics, and providing rudimentary
    control actions.
    """
    def __init__(self, master):
        super().__init__()
        self.updated = master.last_seen
        self.master = master
        self.position = (0, 1)
        self.limits = (0, 0, 7, 2)
        self.text = None
        self.offset = None
        self.stats = {
            (x, y): item
            for y, row in enumerate([
                [
                    stats.NullStat(),
                    stats.NullStat(),
                    stats.ActionStat('Pause'),
                    stats.ActionStat('Halt'),
                    stats.ActionStat('Resume'),
                    stats.ActionStat('Stop Slaves'),
                    stats.ActionStat('Kill Slaves'),
                    stats.ActionStat('Stop Master'),
                ],
                [
                    stats.ActivityStat(),
                    stats.HostStat(),
                    stats.BoardStat(),
                    stats.SerialStat(),
                    stats.OSStat(),
                    stats.UpTimeStat(),
                    stats.NullStat(),
                    stats.NullStat(),
                ],
                [
                    stats.LastSeenStat(),
                    stats.BuildsQueueStat(),
                    stats.DiskStat(),
                    stats.SwapStat(),
                    stats.MemStat(),
                    stats.CPUTempStat(),
                    stats.LoadAvgStat(),
                    stats.BuildsDoneStat(),
                ],
            ])
            for x, item in enumerate(row)
        }
        self._update_text()

    def move(self, event, task):
        if event.direction == 'down' and self.position[1] == 2:
            task.switch_to(task.renderers['main'], transition='slide',
                           direction='left', duration=0.5)
            return (0, 0)
        delta = super().move(event, task)
        if delta != (0, 0):
            self._update_text()
        return delta

    def _update_text(self, restart=True):
        stat = self.stats[self.position]
        self.text = array(
            draw_text(stat.label,
                      font='small.pil',
                      foreground=stat.color
                                 if isinstance(stat, stats.ActionStat) else
                                 Color('white'),
                      background=Color('black'),
                      padding=(8, 3, 8, 0)))
        if restart:
            last = 0
        else:
            # Ensure the text doesn't "skip" while we're rendering it by
            # starting the offset cycle at the current position of the offset
            # cycle (unless it's out of range)
            last = next(self.offset)
            if last >= self.text.shape[1] - 8:
                last = 0
        self.offset = iter(cycle(chain(
            range(last, self.text.shape[1] - 8), range(last)
        )))

    def _render_stats(self, buf, pulse):
        for (x, y), stat in self.stats.items():
            buf[y, x] = stat.color
        x, y = self.position
        base = Color(*buf[y, x])
        grad = list(base.gradient(Color('white'), steps=15))
        buf[y, x] = grad[pulse]

    def _render_text(self, buf):
        offset = next(self.offset)
        buf += self.text[:, offset:offset + 8]

    def __iter__(self):
        buf = array(Color('black'))
        pulse = iter(bounce(range(15)))
        while True:
            x, y = self.position
            buf[:] = Color('black')
            if self.updated < self.master.last_seen:
                for stat in self.stats.values():
                    stat.calc(self.master)
                self._update_text(restart=False)
                self.updated = self.master.last_seen
            self._render_stats(buf, next(pulse))
            self._render_text(buf)
            yield buf.clip(0, 1)


class SlaveRenderer(Renderer):
    """
    The :class:`SlaveRenderer` is used to render the full-screen status of
    a build slave (when selected from the main menu). Various screens are
    included, detailing the slave's statistics, and providing rudimentary
    control actions.
    """
    def __init__(self, slave):
        super().__init__()
        self.slave = slave
        self.limits = (0, 0, 3, 0)
        self.text = None
        self.status = slave_stats()
        self.update_text()

    def move(self, event, task):
        if event.direction == 'enter' and self.position[0] == 3:
            task.ctrl_queue.send_pyobj(['KILL', self.slave.slave_id])
        delta = super().move(event, task)
        if event.direction == 'enter':
            task.switch_to(
                task.renderers['main'], transition='zoom',
                direction='out', center=task.renderers['main'].position,
                duration=0.5)
        elif delta != (0, 0):
            self.update_text()
            task.switch_to(
                self, transition='slide',
                direction='left' if delta == (1, 0) else 'right',
                duration=0.5)
        return delta

    def update_text(self):
        x, y = self.position
        text, fg, bg = {
            0: (self.slave.label,        'white',  None),
            1: ('ABI:' + self.slave.abi, 'white',  None),
            2: (self.slave.status,       'white',  None),
            3: ('Kill?',                 'red',    'black'),
        }[x]
        self.text = array(
            draw_text(text, foreground=Color(fg),
                      background=self.slave.color if bg is None else Color(bg),
                      padding=(8, 0, 8, 1)))
        self.offset = iter(cycle(chain(
            range(8, self.text.shape[1] - 8), range(8)
        )))

    def __iter__(self):
        while True:
            offset = next(self.offset)
            yield self.text[:, offset:offset + 8]


class StatusRenderer(Renderer):
    """
    The :class:`StatusRenderer` class is responsible for rendering the overall
    master status when the user moves "up" to it from the main screen. It
    includes several horizontally scrolled menus displaying several statistics.
    """
    def __init__(self, master):
        super().__init__()
        self.limits = (0, 0, 5, 0)
        self.back = None
        self.text = None
        self.ping_grad = list(
            Color('green').gradient(Color('red'), steps=64))
        self.disk_grad = list(
            Color('red').gradient(Color('green'), steps=64, easing=ease_out))
        self.offset = cycle([8])
        #self.update_back()
        #self.update_text()

    def move(self, event, task):
        delta = super().move(event, task)
        if event.direction == 'down':
            task.switch_to(task.renderers['main'], transition='slide',
                           direction='up', duration=0.5)
        elif delta != (0, 0):
            self.offset = cycle([8])
            self.update_back()
            self.update_text()
            task.switch_to(self, transition='slide',
                           direction='left' if delta == (1, 0) else 'right',
                           duration=0.5)
        return delta

    def update_back(self):
        x, y = self.position
        if x == 0:
            ping = 64 * max(timedelta(0), min(timedelta(seconds=30),
                datetime.now(tz=UTC) - self.main.last_message)).total_seconds() / 30
            self.back = array([
                c if i <= ping else Color('black')
                for i in range(64)
                for c in (self.ping_grad[min(63, int(ping))],)
            ])
            self.back = np.flipud(self.back)
        elif x == 1:
            disk = (
                64 * self.main.status.get('disk_free', 0) /
                self.main.status.get('disk_size', 1))
            self.back = array([
                c if i < int(disk) else
                c * Lightness(disk - int(disk)) if i < disk else
                Color('black')
                for i in range(64)
                for c in (self.disk_grad[min(63, int(disk))],)
            ])
            self.back = np.flipud(self.back)
        elif x == 2:
            pkgs = min(
                64, self.main.status.get('builds_pending', 0))
            self.back = array([
                Color('blue') if i < pkgs else
                Color('black')
                for i in range(64)
            ])
            self.back = np.flipud(self.back)
        elif x == 3:
            bph = (
                64 * self.main.status.get('builds_last_hour', 0) /
                1000)
            self.back = array([
                Color('blue') if i < int(bph) else
                Color('blue') * Lightness(bph - int(bph)) if i < bph else
                Color('black')
                for i in range(64)
            ])
            self.back = np.flipud(self.back)
        else:
            self.back = array(Color('black'))

    def update_text(self):
        x, y = self.position
        time = self.main.status.get('builds_time', timedelta(0))
        time -= timedelta(microseconds=time.microseconds)
        ping = datetime.now(tz=UTC) - self.main.last_message
        ping -= timedelta(microseconds=ping.microseconds)
        text = [
            'Last Ping: {}s'.format(int(ping.total_seconds())),
            'Disk Free: {}%'.format(
             100 * self.main.status.get('disk_free', 0) //
             self.main.status.get('disk_size', 1)),
            'Queue Size: {}'.format(
             self.main.status.get('builds_pending', 0)),
            'Builds/Hour: {}'.format(
             self.main.status.get('builds_last_hour', 0)),
            'Build Time: {}'.format(time),
            'Build Size: {}'.format(format_size(
             self.main.status.get('builds_size', 0))),
        ][x]
        self.text = array(
            draw_text(text, foreground=Color('gray'), padding=(8, 0, 8, 1)))
        # Ensure the text doesn't "skip" while we're rendering it by starting
        # the offset cycle at the current position of the offset cycle (unless
        # it's out of range)
        last = next(self.offset)
        if last >= self.text.shape[1] - 8:
            last = 0
        self.offset = iter(cycle(chain(
            range(last, self.text.shape[1] - 8), range(last)
        )))

    def __iter__(self):
        now = datetime.now(tz=UTC)
        while True:
            if datetime.now(tz=UTC) - now > timedelta(seconds=1):
                now = datetime.now(tz=UTC)
                self.update_back()
                self.update_text()
            offset = next(self.offset)
            buf = self.back.copy()
            buf[:self.text.shape[0], :] += self.text[:, offset:offset + 8]
            yield buf.clip(0, 1)


class QuitRenderer(Renderer):
    """
    The :class:`QuitRenderer` is responsible for rendering the Quit? and
    Terminate? options which are "below" the main screen.
    """
    def __init__(self):
        super().__init__()
        self.limits = (0, 0, 2, 0)
        self.text = None
        self.update_text()

    def move(self, event, task):
        x, y = self.position
        if event.direction == 'enter':
            if x == 1:
                subprocess.call(['sudo', '-n', 'reboot'])
            elif x == 2:
                subprocess.call(['sudo', '-n', 'poweroff'])
            signal.pthread_kill(main_thread().ident, signal.SIGINT)
        delta = super().move(event, task)
        if event.direction == 'up':
            task.switch_to(task.renderers['main'], transition='slide',
                           direction='down', duration=0.5)
        elif delta != (0, 0):
            self.update_text()
        return delta

    def update_text(self):
        x, y = self.position
        text = {
            0: 'Quit?',
            1: 'Reboot?',
            2: 'Off?',
        }[x]
        self.text = array(
            draw_text(text, foreground=Color('red'), padding=(8, 0, 8, 1)))
        self.offset = iter(cycle(range(self.text.shape[1] - 8)))

    def __iter__(self):
        buf = array(Color('black'))
        while True:
            offset = next(self.offset)
            yield self.text[:, offset:offset + 8]
