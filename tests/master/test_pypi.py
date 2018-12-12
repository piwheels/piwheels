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


from unittest import mock
from datetime import datetime

import pytest

from piwheels.master.pypi import PyPIEvents


def dt(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')


def test_pypi_read_normal():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.return_value = [
            ('foo', '0.1', 1531327388, 'create', 0),
            ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
            ('bar', '1.0', 1531327389, 'create', 2),
            ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
        ]
        events = PyPIEvents()
        assert list(events) == [
            ('foo', None,  dt('2018-07-11 16:43:08'), None),
            ('foo', '0.1', dt('2018-07-11 16:43:08'), True),
            ('bar', None,  dt('2018-07-11 16:43:09'), None),
            ('bar', '1.0', dt('2018-07-11 16:43:09'), False),
        ]


def test_pypi_ignore_other_events():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.return_value = [
            ('foo', '0.1', 1531327388, 'create', 0),
            ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
            ('bar', '1.0', 1531327389, 'create', 2),
            ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
            ('bar', '1.0', 1531327392, 'foo', 4),
            ('bar', '1.0', 1531327392, 'foo bar baz', 5),
        ]
        events = PyPIEvents()
        assert list(events) == [
            ('foo', None,  dt('2018-07-11 16:43:08'), None),
            ('foo', '0.1', dt('2018-07-11 16:43:08'), True),
            ('bar', None,  dt('2018-07-11 16:43:09'), None),
            ('bar', '1.0', dt('2018-07-11 16:43:09'), False),
        ]


def test_pypi_cache_expunge():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.return_value = [
            ('foo', '0.1', 1531327388, 'create', 0),
            ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
            ('bar', '1.0', 1531327389, 'create', 2),
            ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
        ]
        events = PyPIEvents(cache_size=1)
        assert list(events) == [
            ('foo', None,  dt('2018-07-11 16:43:08'), None),
            ('foo', '0.1', dt('2018-07-11 16:43:08'), True),
            ('bar', None,  dt('2018-07-11 16:43:09'), None),
            ('bar', '1.0', dt('2018-07-11 16:43:09'), False),
        ]
        assert ('foo', '0.1') not in events.cache
        assert ('bar', '1.0') in events.cache


def test_pypi_ignore_dupes():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.return_value = [
            ('foo', '0.1', 1531327388, 'create', 0),
            ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
            ('bar', '1.0', 1531327389, 'create', 2),
            ('bar', '1.0', 1531327389, 'add source file bar-1.0.tar.gz', 3),
            ('bar', '1.0', 1531327389, 'add source file bar-1.0.zip', 4),
            ('bar', '1.0', 1531327392, 'add cp34 file bar-0.1-cp34-cp34-manylinux1_x86_64.whl', 5),
            ('bar', '1.0', 1531327392, 'add cp35 file bar-0.1-cp35-cp35-manylinux1_x86_64.whl', 6),
        ]
        events = PyPIEvents()
        assert list(events) == [
            ('foo', None,  dt('2018-07-11 16:43:08'), None),
            ('foo', '0.1', dt('2018-07-11 16:43:08'), True),
            ('bar', None,  dt('2018-07-11 16:43:09'), None),
            ('bar', '1.0', dt('2018-07-11 16:43:09'), True),
        ]


def test_pypi_promote_binary_to_source():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.return_value = [
            ('foo', '0.1', 1531327388, 'create', 0),
            ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
            ('bar', '1.0', 1531327389, 'create', 2),
            ('bar', '1.0', 1531327390, 'add cp34 file bar-0.1-cp34-cp34-manylinux1_x86_64.whl', 3),
            ('bar', '1.0', 1531327390, 'add cp35 file bar-0.1-cp35-cp35-manylinux1_x86_64.whl', 4),
            ('bar', '1.0', 1531327392, 'add source file bar-1.0.tar.gz', 5),
            ('bar', '1.0', 1531327392, 'add source file bar-1.0.zip', 6),
        ]
        events = PyPIEvents()
        assert list(events) == [
            ('foo', None,  dt('2018-07-11 16:43:08'), None),
            ('foo', '0.1', dt('2018-07-11 16:43:08'), True),
            ('bar', None,  dt('2018-07-11 16:43:09'), None),
            ('bar', '1.0', dt('2018-07-11 16:43:10'), False),
            # Note the timestamp doesn't alter as the release time is the
            # earliest release
            ('bar', '1.0', dt('2018-07-11 16:43:10'), True),
        ]


def test_pypi_backoff():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.return_value = [
            ('foo', '0.1', 1531327388, 'create', 0),
            ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
            ('bar', '1.0', 1531327389, 'create', 2),
            ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
        ]
        events = PyPIEvents()
        assert list(events) == [
            ('foo', None,  dt('2018-07-11 16:43:08'), None),
            ('foo', '0.1', dt('2018-07-11 16:43:08'), True),
            ('bar', None,  dt('2018-07-11 16:43:09'), None),
            ('bar', '1.0', dt('2018-07-11 16:43:09'), False),
        ]
        proxy().changelog_since_serial.return_value = []
        assert list(events) == []
        proxy().changelog_since_serial.return_value = [
            ('bar', '1.1', 1531327392, 'create', 4),
            ('bar', '1.1', 1531327393, 'add source file bar-1.1.tar.gz', 5),
        ]
        # Because 10 seconds haven't elapsed...
        assert list(events) == []


def test_pypi_read_improper_state():
    import http.client
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.side_effect = (
            http.client.ImproperConnectionState('Something went horribly wrong')
        )
        events = PyPIEvents()
        assert list(events) == []


def test_pypi_read_server_error():
    import xmlrpc.client
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.side_effect = (
            xmlrpc.client.ProtocolError('Something else went wrong',
                                        500, '', '')
        )
        events = PyPIEvents()
        assert list(events) == []

def test_pypi_read_client_error():
    import xmlrpc.client
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.side_effect = (
            xmlrpc.client.ProtocolError('Client did something stupid',
                                        400, '', '')
        )
        events = PyPIEvents()
        with pytest.raises(xmlrpc.client.ProtocolError):
            list(events)
