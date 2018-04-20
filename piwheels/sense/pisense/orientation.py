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
str = type('')

import math
import time
from collections import namedtuple

import RTIMU


IMUValue = namedtuple('IMUValue', ('compass', 'gyroscope', 'accelerometer', 'orientation'))
Readings = namedtuple('Readings', ('x', 'y', 'z'))
Orientation = namedtuple('Orientation', ('roll', 'pitch', 'yaw'))


class SenseIMU(object):
    def __init__(self, imu_settings='/etc/RTIMULib'):
        self._settings = RTIMU.Settings(imu_settings)
        self._imu = RTIMU.RTIMU(self._settings)
        if not self._imu.IMUInit():
            raise RuntimeError('IMU initialization failed')
        self._interval = self._imu.IMUGetPollInterval() / 1000.0 # seconds
        self._compass = None
        self._gyroscope = None
        self._accel = None
        self._fusion = None
        self._last_read = None
        self.orientation_sensors = {'compass', 'gyroscope', 'accelerometer'}

    def __iter__(self):
        while True:
            self._refresh()
            value = IMUValue(
                self._compass,
                self._gyroscope,
                self._accelerometer,
                self._fusion
                )
            if self._fusion:
                yield value
            delay = max(0.0, self._last_read + self._interval - time.time())
            if delay:
                time.sleep(delay)

    @property
    def name(self):
        return self._imu.IMUName()

    @property
    def compass(self):
        self._refresh()
        return self._compass

    @property
    def gyroscope(self):
        self._refresh()
        return self._gyroscope

    @property
    def accelerometer(self):
        self._refresh()
        return self._accelerometer

    @property
    def orientation(self):
        self._refresh()
        return self._fusion

    @property
    def orientation_degrees(self):
        return Orientation(*(math.degrees(e) % 360 for e in self.orientation))

    def _get_sensors(self):
        return self._sensors
    def _set_sensors(self, value):
        self._sensors = frozenset(value)
        self._imu.setCompassEnable('compass' in self._sensors)
        self._imu.setGyroEnable('gyroscope' in self._sensors)
        self._imu.setAccelEnable('accelerometer' in self._sensors)
    orientation_sensors = property(_get_sensors, _set_sensors)

    def _refresh(self):
        now = time.time()
        if self._last_read is None or now - self._last_read > self._interval:
            if self._imu.IMURead():
                d = self._imu.getIMUData()
                if d.get('compassValid', False):
                    self._compass = Readings(*d['compass'])
                if d.get('gyroValid', False):
                    self._gyroscope = Readings(*d['gyro'])
                if d.get('accelValid', False):
                    self._accelerometer = Readings(*d['accel'])
                if d.get('fusionPoseValid', False):
                    self._fusion = Orientation(*d['fusionPose'])
                self._last_read = now
