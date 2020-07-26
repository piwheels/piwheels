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

from piwheels.master.pypi import PyPIEvents


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
            for index, (pkg, ver, ts, msg) in enumerate(q.get(), start=n)
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
def mock_xml_server(request):
    with mock.patch('xmlrpc.client.ServerProxy') as xml_proxy:
        events = []
        xml_proxy().changelog_since_serial.return_value = events
        yield events


@pytest.fixture()
def json_server(request):
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        pass
    class JSONRequestHandler(BaseHTTPRequestHandler):
        packages = {}
        def do_GET(self):
            if self.path.endswith('/json'):
                try:
                    package = self.path.rsplit('/', 2)[1]
                    description = self.packages[package]
                except KeyError:
                    self.send_error(404, 'Not found')
                else:
                    self.send_response(200, 'OK')
                    self.end_headers()
                    data = {'info': {'summary': description}}
                    self.wfile.write(json.dumps(data).encode('utf-8'))
            else:
                self.send_error(404, 'Not found')
    json_server = ThreadedHTTPServer(("127.0.0.1", 8001), JSONRequestHandler)
    json_server_thread = Thread(target=json_server.serve_forever)
    json_server_thread.daemon = True
    json_server_thread.start()
    yield "http://127.0.0.1:8001/", JSONRequestHandler.packages
    json_server.shutdown()
    json_server.server_close()


@pytest.fixture()
def mock_json_server(request):
    with mock.patch('piwheels.master.pypi.requests.get') as get:
        packages = {}
        def mock_get(url):
            url = urlsplit(url)
            if url.path.endswith('/json'):
                package = url.path.rsplit('/', 2)[1]
                try:
                    description = packages[package]
                except KeyError:
                    return mock.Mock(status_code=404)
                else:
                    return mock.Mock(status_code=200, json=mock.Mock(
                        return_value={'info': {'summary': description}}))
            else:
                return mock.Mock(status=404)
        get.side_effect = mock_get
        yield packages


def test_pypi_talks_to_servers(xml_server, json_server):
    xml_url, xml_queue = xml_server
    json_url, json_dict = json_server
    events = PyPIEvents(pypi_xmlrpc=xml_url, pypi_json=json_url)
    events.transport.use_https = False
    xml_queue.put([
        ('foo', '0.1', 1531327388, 'create'),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz'),
        ('bar', '1.0', 1531327389, 'create'),
        ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl'),
    ])
    json_dict['foo'] = 'package foo'
    json_dict['bar'] = 'package bar'
    assert list(events) == [
        ('foo', None,  dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.1', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
        ('bar', None,  dt('2018-07-11 16:43:09'), 'create', 'package bar'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'create', 'package bar'),
    ]


def test_pypi_raises_errors(json_server):
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
        events = PyPIEvents(pypi_xmlrpc='http://127.0.0.1:8000/',
                            pypi_json=json_server[0])
        events.transport.use_https = False
        with pytest.raises(ProtocolError):
            list(events)
    finally:
        server.shutdown()
        server.server_close()


def test_pypi_read_normal(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
        ('foo', '0.1', 1531327388, 'create', 0),
        ('foo', '0.1', 1531327388, 'add source file foo-0.1.tar.gz', 1),
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 3),
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


def test_pypi_read_missing_description(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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


def test_pypi_read_huge_description(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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


def test_pypi_ignore_other_events(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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


def test_pypi_cache_expunge(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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
    assert ('foo', '0.1') not in events.cache
    assert ('bar', '1.0') in events.cache


def test_pypi_ignore_dupes(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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


def test_pypi_promote_binary_to_source(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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


def test_pypi_remove_version(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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


def test_pypi_remove_package(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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


def test_pypi_yank_version(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
        ('foo', '0.1', 1531327388, 'yank release', 0),
    ]
    events = PyPIEvents()
    assert list(events) == [
        ('foo', '0.1',  dt('2018-07-11 16:43:08'), 'yank', None),
    ]


def test_pypi_unyank_version(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
        ('foo', '0.1', 1531327388, 'unyank release', 0),
    ]
    events = PyPIEvents()
    assert list(events) == [
        ('foo', '0.1',  dt('2018-07-11 16:43:08'), 'unyank', None),
    ]


def test_pypi_backoff(mock_xml_server, mock_json_server):
    mock_xml_server[:] = [
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
    mock_xml_server[:] = []
    assert list(events) == []
    mock_xml_server[:] = [
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
