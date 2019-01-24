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
from functools import partial
from itertools import cycle, chain
from threading import main_thread

import numpy as np
from pisense import array, draw_text
from colorzero import Color, Lightness, Saturation, Blue, ease_out

from .states import SlaveList
from ..format import format_size


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
    the application (the first screen shown on start). It consists of three
    simple bar charts at the top of the screen indicating last ping time,
    remaining disk space, and number of packages left in the queue. The status
    of each slave is depicted as a single pixel below these three rows.
    """
    def __init__(self):
        super().__init__()
        self.slaves = SlaveList()
        self.status = {}
        self.position = (0, 3)
        self.limits = (0, 3, 7, 7)
        self.last_message = datetime(1970, 1, 1)
        self.blue_grad = list(Color('blue').gradient(Color('white'), 32))

    def message(self, msg, data):
        self.last_message = datetime.now(tz=UTC)
        if msg == 'STATS':
            self.status = data
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
            task.renderer = task.renderers['status']
            task.transition = partial(
                task.screen.slide_to, direction='down', duration=0.5)
        elif event.direction == 'down' and self.position[1] == 7:
            task.renderer = task.renderers['quit']
            task.transition = partial(
                task.screen.slide_to, direction='up', duration=0.5)
        delta = super().move(event, task)
        if event.direction == 'enter' and self.selected is not None:
            task.renderer = SlaveRenderer(self.selected)
            task.transition = partial(
                task.screen.zoom_to, direction='in', center=self.position,
                duration=0.5)
        return delta

    def _render_ping(self, buf, pulse):
        # Render the ping bar at the top
        ping = 8 * max(
            timedelta(0),
            datetime.now(tz=UTC) - self.last_message).total_seconds() / 30
        if ping > 8:
            buf[0, :] = Color(pulse / 15, 0, 0)
        else:
            buf[0, :] = [
                Color('white') if x < int(ping) else
                self.blue_grad[int(32 * (ping - int(ping)))] if x < ping else
                Color('blue')
                for x in range(8)
            ]

    def _render_disk(self, buf, pulse):
        # Then the disk-free bar
        disk = (
            8 * self.status.get('disk_free', 0) /
            self.status.get('disk_size', 1))
        buf[1, :] = [
            Color('white') if x < int(disk) else
            self.blue_grad[int(32 * (disk - int(disk)))] if x < disk else
            Color('blue')
            for x in range(8)
        ]

    def _render_queue(self, buf, pulse):
        # Then the queue length bar
        pkgs = 8 * max(0, self.status.get('builds_pending', 0)) / 64
        buf[2, :] = [
            Color('white') if x < int(pkgs) else
            self.blue_grad[int(32 * (pkgs - int(pkgs)))] if x < pkgs else
            Color('blue')
            for x in range(8)
        ]

    def _render_slaves(self, buf, pulse):
        # Then the slave status pixels
        for index, slave in enumerate(self.slaves):
            x, y = self._slave_coords(index)
            if 0 <= x < 8 and 0 <= y < 8:
                buf[y, x] = slave.color
        x, y = self.position
        base = Color(*buf[y, x])
        grad = list(base.gradient(Color('white'), steps=15))
        buf[y, x] = grad[pulse]

    def __iter__(self):
        buf = array(Color('black'))
        pulse = iter(bounce(range(15)))
        methods = (
            self._render_ping,
            self._render_disk,
            self._render_queue,
            self._render_slaves,
        )
        while True:
            buf[:] = Color('black')
            p = next(pulse)
            self.slaves.prune()
            for method in methods:
                method(buf, p)
            yield buf


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
        self.update_back()
        self.update_text()

    def move(self, event, task):
        if event.direction == 'enter' and self.position[0] == 4:
            task.ctrl_queue.send_pyobj(['QUIT'])
        if event.direction == 'enter' and self.position[0] >= 4:
            signal.pthread_kill(main_thread().ident, signal.SIGINT)
        delta = super().move(event, task)
        if event.direction == 'down':
            task.renderer = self.main
            task.transition = partial(
                task.screen.slide_to, direction='up', duration=0.5)
        elif delta != (0, 0):
            self.offset = cycle([8])
            self.update_back()
            self.update_text()
            task.transition = partial(
                task.screen.slide_to,
                direction='left' if delta == (1, 0) else 'right', duration=0.5)
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
            task.ctrl_queue.send_pyobj(['QUIT'])
        if event.direction == 'enter':
            signal.pthread_kill(main_thread().ident, signal.SIGINT)
        delta = super().move(event, task)
        if event.direction == 'up':
            task.renderer = self.main
            task.transition = partial(
                task.screen.slide_to, direction='down', duration=0.5)
        elif delta != (0, 0):
            self.update_text()
            task.transition = partial(
                task.screen.slide_to,
                direction='left' if delta == (1, 0) else 'right', duration=0.5)
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
            task.renderer = task.renderers['main']
            task.transition = partial(
                task.screen.zoom_to, direction='out',
                center=task.renderers['main'].position, duration=0.5)
        elif delta != (0, 0):
            self.update_text()
            task.transition = partial(
                task.screen.slide_to,
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
        now = datetime.now(tz=UTC)
        while True:
            offset = next(self.offset)
            yield self.text[:, offset:offset + 8]
