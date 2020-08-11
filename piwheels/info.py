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
from collections import namedtuple


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


PiInfo = namedtuple('PiInfo', (
    'model', 'pcb_revision', 'soc', 'manufacturer', 'memory'))

def get_pi_info(revision):
    # Shamelessly nicked from gpio-zero's data.py...
    revision = int(revision, base=16)
    if not revision & 0x800000:
        raise ValueError('old or invalid pi')
    # New-style revision, parse information from bit-pattern:
    #
    # MSB -----------------------> LSB
    # uuuuuuuuFMMMCCCCPPPPTTTTTTTTRRRR
    #
    # uuuuuuuu - Unused
    # F        - New flag (1=valid new-style revision, 0=old-style)
    # MMM      - Memory size (0=256, 1=512, 2=1024)
    # CCCC     - Manufacturer (0=Sony, 1=Egoman, 2=Embest, 3=Sony Japan, 4=Embest, 5=Stadium)
    # PPPP     - Processor (0=2835, 1=2836, 2=2837)
    # TTTTTTTT - Type (0=A, 1=B, 2=A+, 3=B+, 4=2B, 5=Alpha (??), 6=CM,
    #                  8=3B, 9=Zero, 10=CM3, 12=Zero W, 13=3B+, 14=3A+)
    # RRRR     - Revision (0, 1, 2, etc.)
    _memory       = (revision & 0x700000) >> 20
    _manufacturer = (revision & 0xf0000)  >> 16
    _processor    = (revision & 0xf000)   >> 12
    _type         = (revision & 0xff0)    >> 4
    _revision     = (revision & 0x0f)
    model = {
        0:  'A',
        1:  'B',
        2:  'A+',
        3:  'B+',
        4:  '2B',
        6:  'CM',
        8:  '3B',
        9:  'Zero',
        10: 'CM3',
        12: 'Zero W',
        13: '3B+',
        14: '3A+',
        16: 'CM3+',
        17: '4B',
        }.get(_type, '???')
    if model in ('A', 'B'):
        pcb_revision = {
            0: '1.0', # is this right?
            1: '1.0',
            2: '2.0',
            }.get(_revision, 'Unknown')
    else:
        pcb_revision = '1.%d' % _revision
    soc = {
        0: 'BCM2835',
        1: 'BCM2836',
        2: 'BCM2837',
        3: 'BCM2711',
        }.get(_processor, 'Unknown')
    manufacturer = {
        0: 'Sony',
        1: 'Egoman',
        2: 'Embest',
        3: 'Sony Japan',
        4: 'Embest',
        5: 'Stadium',
        }.get(_manufacturer, 'Unknown')
    memory = {
        0: '256Mb',
        1: '512Mb',
        2: '1Gb',
        3: '2Gb',
        4: '4Gb',
        5: '8Gb',
        }.get(_memory, None)
    return PiInfo(model, pcb_revision, soc, manufacturer, memory)


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
