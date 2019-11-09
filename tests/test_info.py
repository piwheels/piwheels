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


import io
import errno
from posix import statvfs_result
from unittest import mock

import pytest

from piwheels.info import (
    get_board_revision,
    get_board_serial,
    get_os_name_version,
    get_cpu_count,
    get_disk_stats,
    get_swap_stats,
    get_mem_stats,
    get_cpu_temp,
)


def test_get_board_revision():
    with mock.patch('io.open') as m:
        m.return_value.__enter__.return_value = io.BytesIO(b'\x00\x12\x34\x56')
        assert get_board_revision() == '123456'
        m.return_value.__enter__.return_value = None
        m.return_value.__enter__.side_effect = IOError(errno.ENOENT, 'File not found')
        assert get_board_revision() == 'unknown'
        m.return_value.__enter__.side_effect = IOError(errno.EACCES, 'Permission denied')
        with pytest.raises(IOError):
            get_board_revision()


def test_get_board_serial():
    with mock.patch('io.open') as m:
        m.return_value.__enter__.return_value = io.BytesIO(b'\x01\x23\x45\x67\x89\xAB\xCD\xEF')
        assert get_board_serial() == '123456789abcdef'
        m.return_value.__enter__.return_value = None
        m.return_value.__enter__.side_effect = IOError(errno.ENOENT, 'File not found')
        assert get_board_serial() == 'unknown'
        m.return_value.__enter__.side_effect = IOError(errno.EACCES, 'Permission denied')
        with pytest.raises(IOError):
            get_board_serial()


def test_os_name_version():
    with mock.patch('io.open') as m:
        m.return_value.__enter__.return_value = io.StringIO(
            'PRETTY_NAME="Foo Linux 1"\nNAME="Foo Linux"\nVERSION=1')
        assert get_os_name_version() == ('Foo Linux', '1')
        m.return_value.__enter__.return_value = io.StringIO(
            'NAME="Foo \\"Linux\\""\nVERSION=1')
        assert get_os_name_version() == ('Foo "Linux"', '1')
        m.return_value.__enter__.return_value = io.StringIO()
        assert get_os_name_version() == ('Linux', '')
        m.return_value.__enter__.return_value = None
        m.return_value.__enter__.side_effect = IOError(errno.ENOENT, 'File not found')
        assert get_os_name_version() == ('Linux', '')
        m.return_value.__enter__.side_effect = IOError(errno.EACCES, 'Permission denied')
        with pytest.raises(IOError):
            get_os_name_version()


def test_get_cpu_count():
    with mock.patch('io.open') as m:
        m.return_value.__enter__.return_value = io.StringIO("0")
        assert get_cpu_count() == 1
        m.return_value.__enter__.return_value = io.StringIO("0-1")
        assert get_cpu_count() == 2
        m.return_value.__enter__.return_value = io.StringIO("0,2")
        assert get_cpu_count() == 2
        m.return_value.__enter__.return_value = io.StringIO("0-3")
        assert get_cpu_count() == 4
        m.return_value.__enter__.return_value = io.StringIO("0-3,5")
        assert get_cpu_count() == 5


def test_get_disk_stats():
    with mock.patch('os.statvfs') as statvfs:
        statvfs.return_value = statvfs_result((
            4096, 4096, 100000, 48000, 48000, 0, 0, 0, 0, 255))
        assert get_disk_stats('/home/pi') == (100000 * 4096, 48000 * 4096)


def test_get_swap_stats():
    with mock.patch('io.open') as m:
        m.return_value.__enter__.return_value = io.StringIO(
            "SwapTotal:      1024 kB\n"
            "SwapFree:       1024 kB\n")
        assert get_swap_stats() == (1024 * 1024, 1024 * 1024)
        m.return_value.__enter__.return_value = io.StringIO(
            "SwapTotal:      1024 kB\n"
            "SwapFree:         10 kB\n")
        assert get_swap_stats() == (1024 * 1024, 10 * 1024)
        m.return_value.__enter__.return_value = io.StringIO()
        with pytest.raises(RuntimeError):
            get_swap_stats()


def test_get_mem_stats():
    with mock.patch('io.open') as m:
        m.return_value.__enter__.return_value = io.StringIO(
            "MemTotal:       1024 kB\n"
            "MemFree:         100 kB\n"
            "Buffers:          10 kB\n"
            "Cached:          100 kB\n"
            "SwapCached:        0 kB\n")
        assert get_mem_stats() == (1024 * 1024, 200 * 1024)
        m.return_value.__enter__.return_value = io.StringIO(
            "MemTotal:       1024 kB\n"
            "MemAvailable:    256 kB\n"
            "MemFree:         100 kB\n")
        assert get_mem_stats() == (1024 * 1024, 256 * 1024)
        m.return_value.__enter__.return_value = io.StringIO()
        with pytest.raises(RuntimeError):
            get_mem_stats()


def test_get_cpu_temp():
    with mock.patch('io.open') as m:
        m.return_value.__enter__.return_value = io.StringIO("60000")
        assert get_cpu_temp() == 60.0
        m.return_value.__enter__.return_value = io.StringIO("76543")
        assert get_cpu_temp() == 76.543
        m.return_value.__enter__.side_effect = FileNotFoundError
        assert get_cpu_temp() == 0.0
