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

from __future__ import (
    unicode_literals,
    absolute_import,
    print_function,
    division,
)

import signal
from datetime import datetime, timedelta
from functools import partial
from itertools import cycle, chain
from threading import main_thread

import numpy as np
from pisense import array, draw_text
from colorzero import Color, Lightness, Saturation, Blue

from .states import SlaveList


def bounce(it):
    # bounce('ABC') -> A B C C B A A B C ...
    return cycle(chain(it, reversed(it)))


class Renderer:
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
    def __init__(self):
        super().__init__()
        self.slaves = SlaveList()
        self.status = {}
        self.position = (0, 2)
        self.limits = (0, 2, 7, 7)

    @staticmethod
    def _slave_coords(index):
        return (index // 6, 2 + index % 6)

    @staticmethod
    def _slave_index(x, y):
        return (x * 6) + (y - 2)

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
        if event.direction == 'up' and self.position[1] == 2:
            task.renderer = task.status
            task.transition = partial(
                task.screen.slide_to, direction='down', duration=0.5)
        delta = super().move(event, task)
        if event.direction == 'enter' and self.selected is not None:
            task.renderer = SlaveRenderer(self.selected)
            task.transition = partial(
                task.screen.zoom_to, direction='in', center=self.position,
                duration=0.5)
        return delta

    def __iter__(self):
        buf = array(Color('black'))
        pulse = iter(bounce(range(15)))
        while True:
            buf[:] = Color('black')
            # Render disk-free bar at the top
            disk = (
                8 * self.status.get('disk_free', 0) /
                self.status.get('disk_size', 1))
            buf[0, :] = [
                Color('gray') if x < int(disk) else
                Color('gray') * Lightness(disk - int(disk)) if x < disk else
                Color('blue')
                for x in range(8)
            ]
            # Then the queue length bar
            pkgs = max(
                0, self.status.get('versions_count', 0) -
                self.status.get('versions_tried', 0))
            buf[1, :] = [
                Color('gray') if x < pkgs else Color('blue')
                for x in range(8)
            ]
            # Then the slave status pixels
            for index, slave in enumerate(self.slaves):
                x, y = self._slave_coords(index)
                buf[y, x] = slave.color
            x, y = self.position
            base = Color(*buf[y, x])
            grad = list(base.gradient(Color('white'), steps=15))
            buf[y, x] = grad[next(pulse)]
            yield buf


class StatusRenderer(Renderer):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.limits = (0, 0, 4, 0)
        self.back = None
        self.text = None
        self.update_back()
        self.update_text()

    def move(self, event, task):
        if event.direction == 'enter' and self.position[0] == 4:
            task.ctrl_queue.send_pyobj(['QUIT'])
            signal.pthread_kill(main_thread().ident, signal.SIGINT)
        elif event.direction == 'enter' and self.position[0] == 4:
            signal.pthread_kill(main_thread().ident, signal.SIGINT)
        delta = super().move(event, task)
        if event.direction == 'down':
            task.renderer = task.main
            task.transition = partial(
                task.screen.slide_to, direction='up', duration=0.5)
        elif delta != (0, 0):
            self.update_back()
            self.update_text()
            task.transition = partial(
                task.screen.slide_to,
                direction='left' if delta == (1, 0) else 'right',
                duration=0.5)
        return delta

    def update_back(self):
        x, y = self.position
        if x == 0:
            disk = (
                64 * self.main.status.get('disk_free', 0) /
                self.main.status.get('disk_size', 1))
            self.back = array([
                Color('blue') if i < int(disk) else
                Color('blue') * Blue(disk - int(disk)) if i < disk else
                Color('black')
                for i in range(64)
            ])
            self.back = np.flipud(self.back)
        elif x == 1:
            pkgs = min(
                64, self.main.status.get('versions_count', 0) -
                self.main.status.get('versions_tried', 0))
            self.back = array([
                Color('blue') if i < int(pkgs) else
                Color('black')
                for i in range(64)
            ])
            self.back = np.flipud(self.back)
        elif x == 2:
            bph = min(
                64, self.main.status.get('builds_last_hour', 0))
            self.back = array([
                Color('blue') if i < int(bph) else
                Color('black')
                for i in range(64)
            ])
            self.back = np.flipud(self.back)
        else:
            self.back = array(Color('black'))

    def update_text(self):
        x, y = self.position
        text, color = {
            0: ('Disk Free', 'gray'),
            1: ('Queue Size', 'gray'),
            2: ('Builds/hour', 'gray'),
            3: ('Terminate?', 'red'),
            4: ('Quit?', 'red'),
        }[x]
        self.text = array(
            draw_text(text, foreground=Color(color), padding=(8, 0, 8, 1)))
        self.offset = iter(cycle(range(self.text.shape[1] - 8)))
        self.offset = iter(cycle(chain(
            range(8, self.text.shape[1] - 8), range(8)
        )))

    def __iter__(self):
        now = datetime.utcnow()
        while True:
            if datetime.utcnow() - now > timedelta(seconds=1):
                now = datetime.utcnow()
                self.update_back()
            offset = next(self.offset)
            buf = self.back.copy()
            buf[:self.text.shape[0], :] += self.text[:, offset:offset + 8]
            yield buf.clip(0, 1)


class SlaveRenderer(Renderer):
    def __init__(self, slave):
        super().__init__()
        self.slave = slave
        self.limits = (0, 0, 2, 0)
        self.text = None
        self.update_text()

    def move(self, event, task):
        delta = super().move(event, task)
        if event.direction == 'enter':
            task.renderer = task.main
            task.transition = partial(
                task.screen.zoom_to, direction='out',
                center=task.main.position, duration=0.5)
        elif delta != (0, 0):
            self.update_text()
            task.transition = partial(
                task.screen.slide_to,
                direction='left' if delta == (1, 0) else 'right',
                duration=0.5)
        return delta

    def update_text(self):
        x, y = self.position
        text = {
            0: self.slave.label,
            1: 'ABI:' + self.slave.abi,
            2: self.slave.status,
        }[x]
        self.text = array(
            draw_text(text, foreground=Color('white'),
                      background=self.slave.color, padding=(8, 0, 8, 1)))
        self.offset = iter(cycle(range(self.text.shape[1] - 8)))
        self.offset = iter(cycle(chain(
            range(8, self.text.shape[1] - 8), range(8)
        )))

    def __iter__(self):
        now = datetime.utcnow()
        while True:
            offset = next(self.offset)
            yield self.text[:, offset:offset + 8]
