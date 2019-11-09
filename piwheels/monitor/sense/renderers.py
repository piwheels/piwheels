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
from piwheels.transport import NoData
from .states import SlaveList, MasterState, SlaveState
from . import controls


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
        self._limits = (0, 0, 7, 7)
        self._position = (0, 0)

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        x, y = value
        min_x, min_y, max_x, max_y = self.limits
        x = max(min_x, min(max_x, x))
        y = max(min_y, min(max_y, y))
        self._position = x, y

    @property
    def limits(self):
        return self._limits

    @limits.setter
    def limits(self, value):
        if value != self._limits:
            self._limits = value
            # Re-calculate position for new limits
            self.position = self.position

    def __iter__(self):
        pass

    def move(self, event, task):
        if event.pressed:
            x, y = self.position
            try:
                dx, dy = {
                    'up':    (0, -1),
                    'down':  (0, 1),
                    'left':  (-1, 0),
                    'right': (1, 0),
                }[event.direction]
            except KeyError:
                pass
            else:
                self.position = x + dx, y + dy
                nx, ny = self.position
                return nx - x, ny - y
        return (0, 0)


class HelpRenderer(Renderer):
    """
    The :class:`HelpRenderer` is responsible for rendering help notes for
    the graphs at the top of the main page. It consists of eight small
    horizontally arranged blocks at the top of the screen. Each can be
    individually selected to display a scrolling description below.
    """
    def __init__(self):
        super().__init__()
        self.offset = None
        self.text = None
        self.limits = (0, 0, 7, 0)
        self.position = (0, 0)
        self._update_text()

    @property
    def position(self):
        return super().position

    @position.setter
    def position(self, value):
        with self.watch_selection():
            # Fugly super-call for property setters...
            super(HelpRenderer, self.__class__).position.fset(self, value)

    @contextmanager
    def watch_selection(self):
        before = self.position
        yield
        after = self.position
        if before != after:
            self._update_text()

    def _update_text(self):
        label = [
            'Last Seen',
            'Builds Queue/Build Time',
            'Disk Used',
            'Swap Used',
            'Mem Used',
            'CPU Temperature',
            'Load Avg',
            'Builds Done/Clock Skew',
        ][self.position[0]]
        self.text = array(
            draw_text(label,
                      font='small.pil',
                      foreground=Color('white'),
                      background=Color('black'),
                      padding=(8, 3, 8, 0)))
        self.offset = iter(cycle(range(self.text.shape[1] - 8)))

    def move(self, event, task):
        if event.direction == 'down':
            task.renderers['main'].position = self.position[0], 3
            task.switch_to(task.renderers['main'], transition='draw')
            return (0, 0)
        else:
            return super().move(event, task)

    def __iter__(self):
        buf = array(Color('black'))
        grad = list(Color('darkblue').gradient(Color('white'), steps=15))
        pulse = iter(bounce(range(len(grad))))
        while True:
            offset = next(self.offset)
            buf[:, :] = self.text[:, offset:offset + 8]
            buf[:3, :] = Color('darkblue')
            x, y = self.position
            buf[:3, x] = grad[next(pulse)]
            yield buf


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
        self.slaves = SlaveList()
        self.controls = None
        self.connected = False
        self.limits = (0, 3, 7, 7)
        self.position = (0, 3)
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

    @property
    def position(self):
        return super().position

    @position.setter
    def position(self, value):
        with self.watch_selection():
            # ... and again
            super(MainRenderer, self.__class__).position.fset(self, value)

    @contextmanager
    def watch_selection(self):
        before = self.selected
        yield
        after = self.selected
        if before != after:
            self._make_stats(after)

    def _make_stats(self, state):
        if isinstance(state, MasterState):
            self.controls = [
                controls.LastSeen(),
                controls.BuildsQueue(),
                controls.Disk(),
                controls.Swap(),
                controls.Mem(),
                controls.CPUTemp(),
                controls.LoadAvg(),
                controls.BuildsDone(),
            ]
        elif isinstance(state, SlaveState):
            self.controls = [
                controls.LastSeen(),
                controls.BuildTime(),
                controls.Disk(),
                controls.Swap(),
                controls.Mem(),
                controls.CPUTemp(),
                controls.LoadAvg(),
                controls.ClockSkew(),
            ]
        else:
            assert state is None
            self.controls = [controls.Placeholder()] * 8
        self._refresh_stats(state)

    def _refresh_stats(self, state):
        for control in self.controls:
            control.update(state)

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
            task.renderers['help'].position = self.position[0], 0
            task.switch_to(task.renderers['help'], transition='draw')
            return (0, 0)
        elif event.direction == 'down' and self.position[1] == 7:
            task.switch_to(task.renderers['quit'], transition='slide',
                           direction='up', duration=0.5)
            return (0, 0)
        else:
            delta = super().move(event, task)
            if event.direction == 'enter' and self.selected is not None:
                if isinstance(self.selected, MasterState):
                    task.switch_to(MasterRenderer(self.selected),
                                   transition='zoom', direction='in',
                                   center=self.position, duration=0.5)
                else:
                    task.switch_to(SlaveRenderer(self.selected),
                                   transition='zoom', direction='in',
                                   center=self.position, duration=0.5)
            return delta

    def _render_stats(self, buf):
        for x, stat in enumerate(self.controls):
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


class NodeRenderer(Renderer):
    """
    The :class:`NodeRenderer` is used to render the full-screen status of the
    master or slave nodes (when selected from the main menu). Various screens
    are included, detailing the node's statistics, and providing rudimentary
    control actions. This is effectively an abstract base class, with
    :class:`SlaveRenderer` and :class:`MasterRenderer` filling in the
    :attr:`stats` dictionary.
    """
    def __init__(self, node):
        super().__init__()
        self.updated = datetime(1970, 1, 1, tzinfo=UTC)
        self.node = node
        self.text = None
        self.offset = None
        self.graph = None
        self._mode = 'text'
        self.limits = (0, 0, 7, 2)
        self.position = (0, 1)
        self.controls = {}

    @property
    def selected(self):
        try:
            return self.controls[self.position]
        except KeyError:
            return None

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, value):
        assert value in {'text', 'graph'}
        if self._mode != value:
            self._mode = value
            {
                'text': self._update_text,
                'graph': self._update_graph,
            }[value]()

    def move(self, event, task):
        if event.pressed and event.direction == 'enter':
            self._run_actions(self.selected.activate(), task)
            return (0, 0)
        delta = super().move(event, task)
        if delta != (0, 0):
            if not isinstance(self.selected, controls.HistoryStat):
                self._mode = 'text'
            {
                'text': self._update_text,
                'graph': self._update_graph,
            }[self.mode]()
        return delta

    def _run_actions(self, actions, task):
        data = self.node.slave_id
        if data is None:
            data = NoData
        for action in actions:
            if action == 'SWITCH':
                self.mode = {
                    'text': 'graph',
                    'graph': 'text',
                }[self.mode]
            elif action == 'BACK':
                task.switch_to(
                    task.renderers['main'], transition='zoom',
                    direction='out', duration=0.5,
                    center=task.renderers['main'].position)
                break
            else:
                task.send_control(action, data)

    def _update_text(self, *, restart=True):
        self.text = array(
            draw_text(self.selected.label,
                      font='small.pil',
                      padding=(8, 3, 8, 0)))
        if restart or self.offset is None:
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

    def _update_graph(self):
        self.graph = array(shape=(5, 8))
        for x, stat in zip(reversed(range(8)), self.selected.history()):
            # Scale the value to the vertical size
            value = stat.value * self.graph.shape[0]
            for y in range(5):
                self.graph[4 - y, x] = (
                    stat.color if y < int(value) else
                    stat.color * Lightness(value - int(value)) if y < value else
                    Color('black')
                )

    def _update_stats(self):
        if self.updated < self.node.last_seen:
            for control in self.controls.values():
                control.update(self.node)
            self._update_text(restart=False)
            self._update_graph()
            self.updated = self.node.last_seen

    def _render_stats(self, buf, pulse):
        for (x, y), stat in self.controls.items():
            buf[y, x] = stat.color
        x, y = self.position
        base = Color(*buf[y, x])
        grad = list(base.gradient(Color('white'), steps=15))
        buf[y, x] = grad[pulse]

    def _render_text(self, buf):
        offset = next(self.offset)
        buf += self.text[:, offset:offset + 8]

    def _render_graph(self, buf):
        buf[3:8, :] += self.graph

    def __iter__(self):
        buf = array(Color('black'))
        pulse = iter(bounce(range(15)))
        render_mode = {
            'text': self._render_text,
            'graph': self._render_graph,
        }
        while True:
            x, y = self.position
            buf[:] = Color('black')
            self._update_stats()
            self._render_stats(buf, next(pulse))
            render_mode[self.mode](buf)
            yield buf.clip(0, 1)


class MasterRenderer(NodeRenderer):
    """
    The :class:`MasterRenderer` is used to render the full-screen status of the
    master node (when selected from the main menu). Various screens are
    included, detailing the master's statistics, and providing rudimentary
    control actions.
    """
    def __init__(self, master):
        super().__init__(master)
        self.controls = {
            (x, y): item
            for y, row in enumerate([
                [
                    controls.Pause(),
                    controls.Halt(),
                    controls.Resume(),
                    controls.StopSlaves(),
                    controls.KillSlaves(),
                    controls.StopMaster(),
                    controls.Placeholder(),
                    controls.Placeholder(),
                ],
                [
                    controls.Activity(),
                    controls.Host(),
                    controls.Board(),
                    controls.Serial(),
                    controls.OS(),
                    controls.UpTime(),
                    controls.Placeholder(),
                    controls.Placeholder(),
                ],
                [
                    controls.LastSeen(),
                    controls.BuildsQueue(),
                    controls.Disk(),
                    controls.Swap(),
                    controls.Mem(),
                    controls.CPUTemp(),
                    controls.LoadAvg(),
                    controls.BuildsDone(),
                ],
            ])
            for x, item in enumerate(row)
        }

    def _update_stats(self):
        self.controls[0, 1].update(self.node)
        self.controls[0, 2].update(self.node)
        super()._update_stats()


class SlaveRenderer(NodeRenderer):
    """
    The :class:`SlaveRenderer` is used to render the full-screen status of
    a build slave (when selected from the main menu). Various screens are
    included, detailing the slave's statistics, and providing rudimentary
    control actions.
    """
    def __init__(self, slave):
        super().__init__(slave)
        self.controls = {
            (x, y): item
            for y, row in enumerate([
                [
                    controls.Skip(),
                    controls.Pause(),
                    controls.Halt(),
                    controls.Resume(),
                    controls.StopSlave(),
                    controls.KillSlave(),
                    controls.Placeholder(),
                    controls.Placeholder(),
                ],
                [
                    controls.Activity(),
                    controls.Host(),
                    controls.Board(),
                    controls.Serial(),
                    controls.OS(),
                    controls.UpTime(),
                    controls.ABI(),
                    controls.Placeholder(),
                ],
                [
                    controls.LastSeen(),
                    controls.BuildTime(),
                    controls.Disk(),
                    controls.Swap(),
                    controls.Mem(),
                    controls.CPUTemp(),
                    controls.LoadAvg(),
                    controls.ClockSkew(),
                ],
            ])
            for x, item in enumerate(row)
        }

    def _update_stats(self):
        self.controls[0, 2].update(self.node)
        super()._update_stats()


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
