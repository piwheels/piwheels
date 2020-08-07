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

import datetime as dt

import pytest

from piwheels.format import format_size, format_timedelta


def test_format_zero():
    assert format_size(0) == '0 B'
    assert format_size(0, zero='-') == '-'
    assert format_size(0.0, zero='-') == '-'


def test_format_ints():
    assert format_size(1) == '1 B'
    assert format_size(10) == '10 B'
    assert format_size(512) == '512 B'
    assert format_size(1023) == '1023 B'
    assert format_size(1024) == '1 KB'
    assert format_size(1024 ** 2) == '1 MB'
    assert format_size(1024 ** 3) == '1 GB'


def test_format_floats():
    assert format_size(1.0) == '1 B'
    assert format_size(10.0) == '10 B'
    assert format_size(512.0) == '512 B'
    assert format_size(1023.0) == '1023 B'
    assert format_size(1024.0) == '1 KB'
    assert format_size(1024.0 ** 2) == '1 MB'
    assert format_size(1024.0 ** 3) == '1 GB'


def test_format_templates():
    assert format_size(1, template='{size:.0f}{suffix}') == '1B'
    assert format_size(1024, template='{size}{suffix}') == '1.0KB'
    assert format_size(1536, template='{size:.1f} {suffix}') == '1.5 KB'


def test_format_timedelta():
    assert format_timedelta(dt.timedelta(0)) == '0:00:00'
    assert format_timedelta(dt.timedelta(seconds=5)) == '0:00:05'
    assert format_timedelta(dt.timedelta(minutes=1)) == '0:01:00'
    assert format_timedelta(dt.timedelta(hours=1, microseconds=1)) == '1:00:00'
