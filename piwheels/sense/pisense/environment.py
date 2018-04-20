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

import time
from collections import namedtuple

import RTIMU


EnvironValue = namedtuple('EnvironValue', ('pressure', 'humidity', 'temperature'))


class SenseEnvironment(object):
    def __init__(self, imu_settings='/etc/RTIMULib'):
        self._settings = RTIMU.Settings(imu_settings)
        self._p_sensor = RTIMU.RTPressure(self._settings)
        self._h_sensor = RTIMU.RTHumidity(self._settings)
        if not self._p_sensor.pressureInit():
            raise RuntimeError('Pressure sensor initialization failed')
        if not self._h_sensor.humidityInit():
            raise RuntimeError('Humidity sensor initialization failed')
        self._pressure = None
        self._humidity = None
        self._temperature = None
        self._interval = 0.04
        self._last_read = None
        self.temperature_sensors = {'pressure', 'humidity'}

    def __iter__(self):
        while True:
            self._refresh()
            yield EnvironValue(
                self._pressure,
                self._humidity,
                self._temperature,
                )
            delay = max(0.0, self._last_read + self._interval - time.time())
            if delay:
                time.sleep(delay)

    @property
    def pressure(self):
        self._refresh()
        return self._pressure

    @property
    def humidity(self):
        self._refresh()
        return self._humidity

    @property
    def temperature(self):
        self._refresh()
        return self._temperature

    def _get_sensors(self):
        return self._temp_sensors
    def _set_sensors(self, value):
        self._temp_sensors = frozenset(value)
    temperature_sensors = property(_get_sensors, _set_sensors)

    def _refresh(self):
        now = time.time()
        if self._last_read is None or now - self._last_read > self._interval:
            p_valid, p_value, tp_valid, tp_value = self._p_sensor.pressureRead()
            h_valid, h_value, th_valid, th_value = self._h_sensor.humidityRead()
            if p_valid:
                self._pressure = p_value
            if h_valid:
                self._humidity = h_value
            t_value = ()
            if tp_valid and 'pressure' in self._temp_sensors:
                t_value += (tp_value,)
            if th_valid and 'humidity' in self._temp_sensors:
                t_value += (th_value,)
            if t_value:
                self._temperature = sum(t_value) / len(t_value)
            self._last_read = now

