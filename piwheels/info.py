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
Defines a set of utility functions for querying information about the platform
we're running on (mostly quite Pi specific).
"""


import io
import os
import shlex
import errno
import struct


def _hexdump(filename, fmt='>L'):
    try:
        size = struct.calcsize(fmt)
        with io.open(filename, 'rb') as f:
            return hex(struct.unpack(fmt, f.read(size))[0])[2:].lstrip('0')
    except IOError as exc:
        if exc.errno == errno.ENOENT:
            return 'unknown'
        else:
            raise


def get_board_revision():
    """
    Returns the board's revision code as a string.
    """
    return _hexdump('/proc/device-tree/system/linux,revision')


def get_board_serial():
    """
    Returns the board's serial number as a string.
    """
    return _hexdump('/proc/device-tree/system/linux,serial', '>Q')


def get_os_name_version():
    """
    Returns the OS name and version (from :file:`/etc/os-release`) as a tuple
    of strings.
    """
    values = {}
    labels = {'NAME', 'VERSION'}
    try:
        with io.open('/etc/os-release', 'r') as f:
            for line in f:
                label, value = line.strip().split('=', 1)
                if label in labels:
                    values[label] = shlex.split(value)[0]
                    if labels <= values.keys():
                        break
    except IOError as e:
        if e.errno == errno.ENOENT:
            pass
        else:
            raise
    return (values.get('NAME', 'Linux'), values.get('VERSION', ''))


def get_cpu_count():
    """
    Returns the number of online CPUs.
    """
    with io.open('/sys/devices/system/cpu/online', 'r') as f:
        value = f.read().strip()
        ranges = value.split(',')
        result = 0
        for r in ranges:
            if '-' in r:
                start, stop = r.split('-', 1)
                result += len(range(int(start), int(stop) + 1))
            else:
                result += 1
    return result


def get_disk_stats(path):
    """
    Returns a tuple of (path_total, path_free) measured in bytes for the
    specified *path* of the file-system.
    """
    stat = os.statvfs(path)
    return (stat.f_blocks * stat.f_frsize, stat.f_bavail * stat.f_frsize)


def get_mem_stats():
    """
    Returns a tuple of (memory_total, memory_free) measured in bytes.
    """
    values = {}
    labels = {'MemTotal:', 'MemAvailable:', 'MemFree:', 'Cached:'}
    with io.open('/proc/meminfo', 'r') as f:
        for line in f:
            label, value, units = line.split()
            if label in labels:
                assert units == 'kB'
                values[label] = int(value) * 1024
                if {'MemTotal:', 'MemAvailable:'} <= values.keys():
                    return (
                        values['MemTotal:'],
                        values['MemAvailable:']
                    )
                elif {'MemTotal:', 'MemFree:', 'Cached:'} <= values.keys():
                    return (
                        values['MemTotal:'],
                        values['MemFree:'] + values['Cached:']
                    )
    raise RuntimeError('unable to determine memory stats')


def get_swap_stats():
    """
    Returns a tuple of (swap_total, swap_free) measured in bytes.
    """
    values = {}
    labels = {'SwapTotal:', 'SwapFree:'}
    with io.open('/proc/meminfo', 'r') as f:
        for line in f:
            label, value, units = line.split()
            if label in labels:
                assert units == 'kB'
                values[label] = int(value) * 1024
                if {'SwapTotal:', 'SwapFree:'} == values.keys():
                    return (
                        values['SwapTotal:'],
                        values['SwapFree:']
                    )
    raise RuntimeError('unable to determine swap stats')


def get_cpu_temp():
    """
    Returns the CPU temperature.
    """
    try:
        with io.open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return int(f.read()) / 1000
    except FileNotFoundError:
        return 0.0
