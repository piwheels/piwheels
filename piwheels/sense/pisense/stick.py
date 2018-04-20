# vim: set et sw=4 sts=4 fileencoding=utf-8:
#
# Experimental API for the Sense HAT
# Copyright (c) 2016 Dave Jones <dave@waveform.org.uk>
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

from __future__ import (
    unicode_literals,
    absolute_import,
    print_function,
    division,
    )
native_str = str
str = type('')

import io
import os
import glob
import errno
import struct
import select
import warnings
from collections import namedtuple, deque
from threading import Thread, RLock
from queue import Queue, Full, Empty


InputEvent = namedtuple('InputEvent', ('timestamp', 'direction', 'action'))


class SenseStickBufferFull(Warning):
    "Warning raised when the joystick's event buffer fills"


class SenseStick(object):
    SENSE_HAT_EVDEV_NAME = 'Raspberry Pi Sense HAT Joystick'
    EVENT_FORMAT = native_str('llHHI')
    EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
    EVENT_BUFFER = 100

    EV_KEY = 0x01

    STATE_RELEASE = 0
    STATE_PRESS = 1
    STATE_HOLD = 2

    KEY_UP = 103
    KEY_LEFT = 105
    KEY_RIGHT = 106
    KEY_DOWN = 108
    KEY_ENTER = 28

    def __init__(self):
        self._callbacks_lock = RLock()
        self._callbacks_close = Event()
        self._callbacks = {}
        self._callbacks_thread = None
        self._closing = Event()
        self._buffer = Queue(maxsize=self.EVENT_BUFFER)
        self._read_thread = Thread(
            target=self._read_stick,
            args=(io.open(self._stick_device(), 'rb', buffering=0),))
        self._read_thread.daemon = True
        self._read_thread.start()

    def close(self):
        if self._read_thread:
            self._closing.set()
            self._read_thread.join()
            if self._callbacks_thread:
                self._callbacks_thread.join()
            self._read_thread = None
            self._callbacks_thread = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    def _stick_device(self):
        for evdev in glob.glob('/sys/class/input/event*'):
            try:
                with io.open(os.path.join(evdev, 'device', 'name'), 'r') as f:
                    if f.read().strip() == self.SENSE_HAT_EVDEV_NAME:
                        return os.path.join('/dev', 'input', os.path.basename(evdev))
            except IOError as e:
                if e.errno != errno.ENOENT:
                    raise
        raise RuntimeError('unable to locate SenseHAT joystick device')

    def _read_stick(self, stick_file):
        try:
            while not self._closing.wait(0):
                if select.select([stick_file], [], [], 0.1)[0]:
                    event = stick_file.read(self.EVENT_SIZE)
                    (
                        tv_sec,
                        tv_usec,
                        type,
                        code,
                        value,
                    ) = struct.unpack(self.EVENT_FORMAT, event)
                    if type == self.EV_KEY:
                        if self._buffer.full():
                            warnings.warn(SenseStickBufferFull(
                                "The internal SenseStick buffer is full; "
                                "try reading some events!"))
                            self._buffer.get()
                        self._buffer.put(InputEvent(
                            timestamp=tv_sec + (tv_usec / 1000000),
                            direction={
                                self.KEY_UP:    'up',
                                self.KEY_DOWN:  'down',
                                self.KEY_LEFT:  'left',
                                self.KEY_RIGHT: 'right',
                                self.KEY_ENTER: 'push',
                            }[code],
                            state={
                                self.STATE_PRESS:   'pressed',
                                self.STATE_RELEASE: 'released',
                                self.STATE_HOLD:    'held',
                            }[value]
                        ))
        finally:
            stick_file.close()

    def _run_callbacks(self):
        while not self._callbacks_close.wait(0) and not self._closing.wait(0):
            event = self.read(0.1)
            if event is not None:
                with self._callbacks_lock:
                    try:
                        self._callbacks[event.direction](event)
                    except KeyError:
                        pass

    def _start_stop_callbacks(self):
        with self._callbacks_lock:
            if self._callbacks and not self._callbacks_thread:
                self._callbacks_close.clear()
                self._callbacks_thread = Thread(target=self._run_callbacks)
                self._callbacks_thread.daemon = True
                self._callbacks_thread.start()
            elif not self._callbacks and self._callbacks_thread:
                self._callbacks_close.set()
                self._callbacks_thread.join()
                self._callbacks_thread = None

    def __iter__(self):
        while True:
            yield self._buffer.get()

    def read(self, timeout=None):
        try:
            return self._buffer.get(timeout=timeout)
        except Empty:
            return None

    @property
    def when_up(self):
        with self._callbacks_lock:
            return self._callbacks.get('up')

    @when_up.setter
    def when_up(self, value):
        with self._callbacks_lock:
            if value:
                self._callbacks['up'] = value
            else:
                self._callbacks.pop('up', None)
            self._start_stop_callbacks()

    @property
    def when_down(self):
        with self._callbacks_lock:
            return self._callbacks.get('down')

    @when_down.setter
    def when_down(self, value):
        with self._callbacks_lock:
            if value:
                self._callbacks['down'] = value
            else:
                self._callbacks.pop('down', None)
            self._start_stop_callbacks()

    @property
    def when_left(self):
        with self._callbacks_lock:
            return self._callbacks.get('left')

    @when_left.setter
    def when_left(self, value):
        with self._callbacks_lock:
            if value:
                self._callbacks['left'] = value
            else:
                self._callbacks.pop('left', None)
            self._start_stop_callbacks()

    @property
    def when_right(self):
        with self._callbacks_lock:
            return self._callbacks.get('right')

    @when_right.setter
    def when_right(self, value):
        with self._callbacks_lock:
            if value:
                self._callbacks['right'] = value
            else:
                self._callbacks.pop('right', None)
            self._start_stop_callbacks()

    @property
    def when_enter(self):
        with self._callbacks_lock:
            return self._callbacks.get('push')

    @when_enter.setter
    def when_enter(self, value):
        with self._callbacks_lock:
            if value:
                self._callbacks['push'] = value
            else:
                self._callbacks.pop('push', None)
            self._start_stop_callbacks()
