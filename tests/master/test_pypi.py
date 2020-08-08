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


from time import sleep
from unittest import mock
from random import randint
from datetime import datetime, timezone
from threading import Thread
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from xmlrpc.client import ProtocolError
from urllib.parse import urlsplit
from queue import Queue

import pytest
import http.client
import xmlrpc.client
import simplejson as json
from requests.exceptions import RequestException
from simplejson.errors import JSONDecodeError

from piwheels.master.pypi import *


UTC = timezone.utc


def dt(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)


@pytest.fixture()
def mock_requests():
    # XXX Delete me?
    with mock.patch('piwheels.master.pypi.requests') as requests:
        yield requests


@pytest.fixture()
def mock_logger(request):
    with mock.patch('piwheels.master.pypi.logger') as logger:
        yield logger


@pytest.fixture()
def xml_server(request):
    q = Queue()
    def changelog_since_serial(n):
        return [
            (pkg, ver, ts, msg, index)
            for index, (pkg, ver, ts, msg) in enumerate(q.get(), start=n + 1)
        ]
    class ThreadedXMLRPCServer(ThreadingMixIn, SimpleXMLRPCServer):
        pass
    xml_server = ThreadedXMLRPCServer(("127.0.0.1", 8000))
    xml_server.register_introspection_functions()
    xml_server.register_function(changelog_since_serial)
    xml_server_thread = Thread(target=xml_server.serve_forever)
    xml_server_thread.daemon = True
    xml_server_thread.start()
    yield "http://127.0.0.1:8000/", q
    xml_server.shutdown()
    xml_server.server_close()


@pytest.fixture()
def mock_buffer(request):
    with mock.patch('piwheels.master.pypi.PyPIBuffer') as buffer_proxy:
        events = []
        buffer_proxy().__iter__.return_value = events
        yield events


@pytest.fixture()
def mock_json_server(request):
    with mock.patch('piwheels.master.pypi.requests.get') as get:
        packages = {}
        def mock_get(url):
            url = urlsplit(url)
            if url.path.endswith('/json'):
                package = url.path.rsplit('/', 2)[1]
                try:
                    if package == 'pypi-err':
                        return mock.Mock(status_code=503)
                    else:
                        description = packages[package]
                except KeyError:
                    return mock.Mock(status_code=404)
                else:
                    if package == 'pypi-bad':
                        return mock.Mock(status_code=200, json=mock.Mock(
                            return_value={'info': {}}))
                    else:
                        return mock.Mock(status_code=200, json=mock.Mock(
                            return_value={'info': {'summary': description}}))
            else:
                return mock.Mock(status=404)
        get.side_effect = mock_get
        yield packages


def test_pypi_buf_talks_to_servers(xml_server):
    xml_url, xml_queue = xml_server
    # NOTE: Must use a serial after PYPI_EPOCH here to permit events thru,
    # and we must include at least 5 minutes worth of events
    buf = PyPIBuffer(pypi_xmlrpc=xml_url, serial=PYPI_EPOCH + 1000)
    buf.transport.use_https = False
    xml_queue.put([
        ('bla', '0.0', 1531320000, 'create'),
    ] * PYPI_MARGIN + [
        ('foo', '0.1', 1531327388, 'create'),
        ('foo', '0.1', 1531327389, 'add source file foo-0.1.tar.gz'),
        ('bar', '1.0', 1531328389, 'create'),
        ('bar', '1.0', 1531328390, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl'),
        ('baz', '2.0', 1531329389, 'create'),
        ('baz', '2.0', 1531329390, 'add py2.py3 file baz-1.0-py2.py3-none-any.whl'),
    ])
    # baz events aren't included in output because they've not "aged" for
    # 5 minutes
    assert list(buf) == [
        ('bla', '0.0', 1531320000, 'create', PYPI_EPOCH + 1000),
        ('foo', '0.1', 1531327388, 'create', PYPI_EPOCH + 1001),
        ('foo', '0.1', 1531327389, 'add source file foo-0.1.tar.gz', PYPI_EPOCH + 1002),
        ('bar', '1.0', 1531328389, 'create', PYPI_EPOCH + 1003),
        ('bar', '1.0', 1531328390, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', PYPI_EPOCH + 1004),
    ]


def test_pypi_buf_returns_empty_before_epoch(xml_server):
    # See notes in prior test
    xml_url, xml_queue = xml_server
    buf = PyPIBuffer(pypi_xmlrpc=xml_url, serial=0)
    buf.transport.use_https = False
    xml_queue.put([
        ('bla', '0.0', ts, 'create')
        for ts in range(1531320000, 1531320000 + 1000)
    ])
    # Nothing returned because it's all before the PYPI_EPOCH
    assert list(buf) == []


def test_pypi_buf_returns_empty_before_serial(xml_server):
    xml_url, xml_queue = xml_server
    # Make sure we're beyond the epoch, even accounting for the amount
    # PyPIBuffer jumps back by (the margin)
    i = PYPI_EPOCH + PYPI_MARGIN + 1000
    buf = PyPIBuffer(pypi_xmlrpc=xml_url, serial=i)
    buf.transport.use_https = False
    xml_queue.put([
        ('bla', '0.0', 1531320000, 'create'),
    ] * (PYPI_MARGIN - 1))
    # Nothing returned yet because PyPIBuffer has jumped backwards PYPI_MARGIN
    # events
    assert list(buf) == []
    xml_queue.put([
        ('foo', '0.1', 1531327388, 'create'),
        ('foo', '0.1', 1531327389, 'add source file foo-0.1.tar.gz'),
        ('bar', '1.0', 1531328389, 'create'),
        ('bar', '1.0', 1531328390, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl'),
        ('baz', '2.0', 1531329389, 'create'),
        ('baz', '2.0', 1531329390, 'add py2.py3 file baz-1.0-py2.py3-none-any.whl'),
    ])
    assert list(buf) == [
        ('foo', '0.1', 1531327388, 'create', i),
        ('foo', '0.1', 1531327389, 'add source file foo-0.1.tar.gz', i + 1),
        ('bar', '1.0', 1531328389, 'create', i + 2),
        ('bar', '1.0', 1531328390, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', i + 3),
    ]


def test_pypi_buf_waits_for_more_events(xml_server):
    xml_url, xml_queue = xml_server
    # Make sure we're beyond the epoch, even accounting for the amount
    # PyPIBuffer jumps back by (the margin)
    i = PYPI_EPOCH + PYPI_MARGIN + 1000
    buf = PyPIBuffer(pypi_xmlrpc=xml_url, serial=i)
    buf.transport.use_https = False
    xml_queue.put([
        ('bla', '0.0', 1531320000, 'create'),
    ] * (PYPI_MARGIN - 1))
    # Nothing yet because of PYPI_MARGIN (see prior test)
    assert list(buf) == []
    xml_queue.put([
        ('foo', '0.1', 1531327388, 'create'),
        ('foo', '0.1', 1531327389, 'add source file foo-0.1.tar.gz'),
    ])
    # Nothing yet because even though we've pushed the event it's waiting for,
    # it's not 5 minutes "old" yet
    assert list(buf) == []
    xml_queue.put([
        ('bar', '1.0', 1531328389, 'create'),
        ('bar', '1.0', 1531328390, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl'),
        ('baz', '2.0', 1531329389, 'create'),
        ('baz', '2.0', 1531329390, 'add py2.py3 file baz-1.0-py2.py3-none-any.whl'),
    ])
    assert list(buf) == [
        ('foo', '0.1', 1531327388, 'create', i),
        ('foo', '0.1', 1531327389, 'add source file foo-0.1.tar.gz', i + 1),
        ('bar', '1.0', 1531328389, 'create', i + 2),
        ('bar', '1.0', 1531328390, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', i + 3),
    ]



def test_pypi_buf_raises_errors():
    class BadXMLHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_error(404, 'Function not found')
    class BadXMLRPCServer(ThreadingMixIn, HTTPServer):
        pass
    server = BadXMLRPCServer(("127.0.0.1", 8000), BadXMLHandler)
    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    try:
        buf = PyPIBuffer(pypi_xmlrpc='http://127.0.0.1:8000/')
        buf.transport.use_https = False
        with pytest.raises(ProtocolError):
            list(buf)
    finally:
        server.shutdown()
        server.server_close()


def test_pypi_read_normal(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
        ('baz', '1.0', 1531327390, 'create', 4),
        ('baz', '1.0', 1531327390, 'add py2.py3 file baz-1.0-py2.py3-none-any.whl', 5),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['bar'] = 'package bar'
    mock_json_server['baz'] = None
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', 'package bar'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'create', 'package bar'),
        ('baz', None,  dt('2018-07-11 16:43:10'), 'create', ''),
        ('baz', '1.0', dt('2018-07-11 16:43:10'), 'create', ''),
    ]


def test_pypi_read_json_err(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('pypi-err', '1.0', 1531327389, 'create', 2),
        ('pypi-err', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['pypi-err'] = 'pypi broke'
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('pypi-err', None,  dt('2018-07-11 16:43:09'), 'create', None),
        ('pypi-err', '1.0', dt('2018-07-11 16:43:09'), 'create', None),
    ]


def test_pypi_read_json_bad(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('pypi-bad', '1.0', 1531327389, 'create', 2),
        ('pypi-bad', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['pypi-bad'] = 'pypi broke'
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('pypi-bad', None,  dt('2018-07-11 16:43:09'), 'create', None),
        ('pypi-bad', '1.0', dt('2018-07-11 16:43:09'), 'create', None),
    ]


def test_pypi_read_missing_description(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
    ]
    mock_json_server['foo'] = 'package foo'
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', None),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'create', None),
    ]


def test_pypi_read_huge_description(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['bar'] = 'bar' * 1000
    expected = ('bar' * 1000)[:199] + '…'
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', expected),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'create', expected),
    ]


def test_pypi_ignore_other_events(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
        ('bar', '1.0', 1531327392, 'foo', 4),
        ('bar', '1.0', 1531327392, 'foo bar baz', 5),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['bar'] = 'package bar'
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', 'package bar'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'create', 'package bar'),
    ]


def test_pypi_cache_expunge(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['bar'] = 'package bar'
    events = PyPIEvents(cache_size=1)
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', 'package bar'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'create', 'package bar'),
    ]
    assert ('foo', '0.1') not in events.versions
    assert ('bar', '1.0') in events.versions


def test_pypi_ignore_dupes(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add source file bar-1.0.tar.gz', 3),
        ('bar', '1.0', 1531327389, 'add source file bar-1.0.zip', 4),
        ('bar', '1.0', 1531327392, 'add cp34 file bar-0.1-cp34-cp34-manylinux1_x86_64.whl', 5),
        ('bar', '1.0', 1531327392, 'add cp35 file bar-0.1-cp35-cp35-manylinux1_x86_64.whl', 6),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['bar'] = 'package bar'
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', 'package bar'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'source', 'package bar'),
    ]


def test_pypi_promote_binary_to_source(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327390, 'add cp34 file bar-0.1-cp34-cp34-manylinux1_x86_64.whl', 3),
        ('bar', '1.0', 1531327390, 'add cp35 file bar-0.1-cp35-cp35-manylinux1_x86_64.whl', 4),
        ('bar', '1.0', 1531327392, 'add source file bar-1.0.tar.gz', 5),
        ('bar', '1.0', 1531327392, 'add source file bar-1.0.zip', 6),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['bar'] = ''
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', ''),
        ('bar', '1.0', dt('2018-07-11 16:43:10'), 'create', ''),
        # Note the timestamp doesn't alter as the release time is the
        # earliest release
        ('bar', '1.0', dt('2018-07-11 16:43:10'), 'source', ''),
    ]


def test_pypi_remove_version(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('foo', '0.1', 1531327388, 'remove', 2),
    ]
    mock_json_server['foo'] = 'package foo'
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'remove', None),
    ]


def test_pypi_remove_package(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('foo', None,  1531327388, 'remove', 2),
    ]
    mock_json_server['foo'] = 'package foo'
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('foo', None,  dt('2018-07-11 16:43:08'), 'remove', None),
    ]


def test_pypi_yank_version(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'yank release', 0),
    ]
    events = PyPIEvents()
    assert list(events) == [
        ('foo', '0.1',  dt('2018-07-11 16:43:08'), 'yank', None),
    ]


def test_pypi_unyank_version(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'unyank release', 0),
    ]
    events = PyPIEvents()
    assert list(events) == [
        ('foo', '0.1',  dt('2018-07-11 16:43:08'), 'unyank', None),
    ]


def test_pypi_backoff(mock_buffer, mock_json_server):
    mock_buffer[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
    ]
    mock_json_server['foo'] = 'package foo'
    mock_json_server['bar'] = ''
    events = PyPIEvents()
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', ''),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'create', ''),
    ]
    mock_buffer[:] = []
    assert list(events) == []
    mock_buffer[:] = [
        ('bar', '1.1', 1531327392, 'create', 4),
        ('bar', '1.1', 1531327393, 'add source file bar-1.1.tar.gz', 5),
    ]
    # Because 10 seconds haven't elapsed...
    assert list(events) == []


def test_pypi_read_improper_state():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.side_effect = (
            http.client.ImproperConnectionState('Something went horribly wrong')
        )
        events = PyPIEvents()
        assert list(events) == []


def test_pypi_read_server_error():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.side_effect = (
            xmlrpc.client.ProtocolError('Something else went wrong',
                                        500, '', '')
        )
        events = PyPIEvents()
        assert list(events) == []


def test_pypi_read_client_error():
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.side_effect = (
            xmlrpc.client.ProtocolError('Client did something stupid',
                                        400, '', '')
        )
        events = PyPIEvents()
        with pytest.raises(xmlrpc.client.ProtocolError):
            list(events)
