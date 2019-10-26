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

.. autoclass:: MainRenderer

.. autoclass:: StatusRenderer

.. autoclass:: SlaveRenderer
"""

import signal
from datetime import datetime, timedelta, timezone
from itertools import cycle, chain
from threading import main_thread

import numpy as np
from pisense import array, draw_text
from colorzero import Color, Lightness, ease_out

from piwheels.format import format_size
from .states import SlaveList, MasterState


UTC = timezone.utc


def bounce(it):
    # bounce('ABC') -> A B C C B A A B C ...
    return cycle(chain(it, reversed(it)))


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


def last_ping(state):
    """
    Return the time since the last message as a value between 0.0 (recent) and
    1.0 (ancient).
    """
    return (datetime.now(tz=UTC) - state.last_seen) / timedelta(seconds=30)


def disk_stat(state):
    """
    Return the disk status in *state* as a value between 0.0 (empty) and 1.0
    (full).
    """
    return (
        1 - (state.stats[-1].disk_free / state.stats[-1].disk_size)
        if state.stats and state.stats[-1].disk_size else None
    )


def swap_stat(state):
    """
    Returns the swap status in *state* as a value between 0.0 (empty) and 1.0
    (full).

    """
    return (
        1 - (state.stats[-1].swap_free / state.stats[-1].swap_free)
        if state.stats and state.stats[-1].swap_free else None
    )


def mem_stat(state):
    """
    Returns the RAM status in *state* as a value between 0.0 (empty) and 1.0
    (full).

    """
    return (
        1 - (state.stats[-1].mem_free / state.stats[-1].mem_free)
        if state.stats and state.stats[-1].mem_free else None
    )


def cpu_temp(state):
    """
    Returns the CPU temperature as value between 0 (°C) and 1 (equating to
    100°C, although it's worth noting all extant Pi models should throttle
    speed at 85°C to avoid damage to the SoC).
    """
    return state.stats[-1].cpu_temp / 100 if state.stats else None


def load_avg(state):
    """
    Returns the load average of the node between (0.0) idle, and 4.0 (full
    loaded).
    """
    return state.stats[-1].load_average / 4.0 if state.stats else None


def builds_queue(state):
    """
    Returns the pending builds queue size as a value between 0 (empty queue,
    good), and 1 (queue of at least 100 items, bad).
    """
    return (
        sum(state.stats[-1].builds_pending.values()) / 100
        if state.stats else None
    )


def builds_done(state):
    """
    Returns the number of builds performed in the last hour as a value
    btween 0 (>100 builds per hour) and 1 (0 builds); note the inverted scale
    so that the graph implies "bad behaviour" if it fills "red".
    """
    return (
        (100 - sum(state.stats[-1].builds_last_hour.values())) / 100
        if state.stats else None
    )



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
        self.slaves = SlaveList()
        self.position = (0, 3)
        self.limits = (0, 3, 7, 7)
        self.status_bars = [
            MainStatBar(last_ping),
            MainStatBar(disk_stat, okay=0.5, fail=0.9),
            MainStatBar(swap_stat, okay=0.0, warn=0.25, fail=0.5),
            MainStatBar(mem_stat),
            MainStatBar(cpu_temp, okay=0.6, warn=0.7, fail=0.8),
            MainStatBar(load_avg),
            MainMasterBar(builds_queue),
            MainMasterBar(builds_done),
        ]

    def message(self, msg, data):
        if msg in ('HELLO', 'STATS'):
            slave_id = None
            timestamp = datetime.now(tz=UTC)
            if msg == 'HELLO':
                self.connected = True
        elif msg == 'SLAVE':
            slave_id, timestamp, msg, data = data
        self.slaves.message(slave_id, timestamp, msg, data)

    @staticmethod
    def _slave_coords(index):
        return (index // 5, 3 + index % 5)

    @staticmethod
    def _slave_index(x, y):
        return (x * 5) + (y - 3)

    @property
    def selected(self):
        x, y = self.position
        if y > 1:
            try:
                return self.slaves[self._slave_index(x, y)]
            except IndexError:
                return None
        else:
            return None

    def move(self, event, task):
        if event.direction == 'up' and self.position[1] == 3:
            task.switch_to(task.renderers['status'], transition='slide',
                           direction='down', duration=0.5)
        elif event.direction == 'down' and self.position[1] == 7:
            task.switch_to(task.renderers['quit'], transition='slide',
                           direction='up', duration=0.5)
        delta = super().move(event, task)
        if event.direction == 'enter' and self.selected is not None:
            task.switch_to(SlaveRenderer(self.selected), transition='zoom',
                           direction='in', center=self.position, duration=0.5)
        return delta

    def _render_status(self, buf):
        for x, bar in enumerate(self.status_bars):
            buf[0:3, x] = bar.render(self.selected)

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
            self.slaves.prune()
            buf[:] = Color('black')
            self._render_status(buf)
            self._render_slaves(buf, next(pulse))
            yield buf


class MainStatBar:
    """
    Represents one of the mini statistics bars at the top of the main screen.

    *calc* is the function which will convert the state of the selected node to
    a value between 0.0 (empty) and 1.0 (full). The function may also return
    ``None`` for unknown, or values outside the range of 0.0 to 1.0 (but such
    values will be clamped before use).

    The remaining parameters (*okay*, *warn*, and *fail*) are used to construct
    a gradient for the bar with the :func:`gradient` function.
    """
    def __init__(self, calc, okay=0.25, warn=0.75, fail=1.0):
        self.calc = calc
        self.gradient = list(gradient(okay, warn, fail))
        assert len(self.gradient) == 32

    def render(self, state):
        if state is None:
            return [Color('#333')] * 3
        else:
            value = self.calc(state)
            if value is None:
                return [Color('#533')] * 3
            else:
                value = min(1, max(0, value))
                color = self.gradient[int((len(self.gradient) - 1) * value)]
                value *= 3
                return [
                    color if y < int(value) else
                    color * Lightness(value - int(value)) if y < value else
                    Color('black')
                    for y in range(3)
                ][::-1]


class MainMasterBar(MainStatBar):
    """
    Represents one of the right-most mini-statistics bar at the top of the main
    screen.

    For the master, this draws the state of the build or downloads queue. For
    slaves, this draws a swatch of the slave's status color.
    """
    def render(self, state):
        if state is None:
            return [Color('#333')] * 3
        if isinstance(state, MasterState):
            return super().render(state)
        else:
            return [state.color] * 3


class StatusRenderer(Renderer):
    """
    The :class:`StatusRenderer` class is responsible for rendering the overall
    master status when the user moves "up" to it from the main screen. It
    includes several horizontally scrolled menus displaying several statistics.
    """
    def __init__(self, main):
        super().__init__()
        self.main = main
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
            task.switch_to(self.main, transition='slide', direction='up',
                           duration=0.5)
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
        text = {
            0: 'Last Ping: {}s'.format(int(ping.total_seconds())),
            1: 'Disk Free: {}%'.format(
                100 * self.main.status.get('disk_free', 0) //
                self.main.status.get('disk_size', 1)),
            2: 'Queue Size: {}'.format(
                self.main.status.get('builds_pending', 0)),
            3: 'Builds/Hour: {}'.format(
                self.main.status.get('builds_last_hour', 0)),
            4: 'Build Time: {}'.format(time),
            5: 'Build Size: {}'.format(format_size(
                self.main.status.get('builds_size', 0))),
        }[x]
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
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.limits = (0, 0, 1, 0)
        self.text = None
        self.update_text()

    def move(self, event, task):
        if event.direction == 'enter' and self.position[0] == 1:
            task.ctrl_queue.send_msg('QUIT')
        if event.direction == 'enter':
            signal.pthread_kill(main_thread().ident, signal.SIGINT)
        delta = super().move(event, task)
        if event.direction == 'up':
            task.switch_to(self.main, transition='slide', direction='down',
                           duration=0.5)
        elif delta != (0, 0):
            self.update_text()
            task.switch_to(self, transition='slide',
                           direction='left' if delta == (1, 0) else 'right',
                           duration=0.5)
        return delta

    def update_text(self):
        x, y = self.position
        text = {
            0: 'Quit?',
            1: 'Terminate?',
        }[x]
        self.text = array(
            draw_text(text, foreground=Color('red'), padding=(8, 0, 8, 1)))
        self.offset = iter(cycle(chain(
            range(8, self.text.shape[1] - 8), range(8)
        )))

    def __iter__(self):
        buf = array(Color('black'))
        while True:
            offset = next(self.offset)
            buf[:self.text.shape[0], :] = self.text[:, offset:offset + 8]
            yield buf.clip(0, 1)


class SlaveRenderer(Renderer):
    """
    The :class:`SlaveRenderer` is used to render the full-screen status of
    a build slave (when selected from the main menu). Various screens are
    included, detailing the slave's label, ABI build tag, and current status.
    """
    def __init__(self, slave):
        super().__init__()
        self.slave = slave
        self.limits = (0, 0, 3, 0)
        self.text = None
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
