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


import os
from unittest import mock
from threading import Event
from datetime import datetime, timedelta, timezone

import zmq
import pytest

from piwheels import const, protocols
from piwheels.master.the_secretary import TheSecretary


UTC = timezone.utc


@pytest.fixture()
def task(request, zmq_context, master_config):
    task = TheSecretary(master_config)
    yield task
    task.close()


@pytest.fixture()
def web_queue(request, zmq_context, task, master_config):
    queue = zmq_context.socket(
        zmq.PUSH, protocol=reversed(protocols.the_scribe))
    queue.hwm = 10
    queue.connect(master_config.web_queue)
    yield queue
    queue.close()


@pytest.fixture()
def scribe_queue(request, zmq_context, task):
    queue = zmq_context.socket(zmq.PULL, protocol=protocols.the_scribe)
    queue.hwm = 10
    queue.connect(const.SCRIBE_QUEUE)
    yield queue
    queue.close()


@pytest.fixture()
def stats_dict(request):
    return {
        'packages_count': 1,
        'packages_built': 0,
        'versions_count': 2,
        'builds_count':   0,
        'builds_last_hour': 0,
        'builds_success': 0,
        'builds_time': timedelta(0),
        'builds_size': 0,
        'builds_pending': 0,
        'files_count': 0,
        'disk_free': 0,
        'disk_size': 1,
        'downloads_last_month': 10,
    }


def test_pass_through(task, web_queue, scribe_queue, stats_dict):
    web_queue.send_msg('HOME', stats_dict)
    task.poll()
    assert scribe_queue.recv_msg() == ('HOME', stats_dict)
    web_queue.send_msg('SEARCH', {'foo': 1})
    task.poll()
    assert scribe_queue.recv_msg() == ('SEARCH', {'foo': 1})


def test_bad_request(task, web_queue):
    web_queue.send(b'FOO')
    e = Event()
    task.logger = mock.Mock()
    task.logger.error.side_effect = lambda *args: e.set()
    task.poll()
    assert e.wait(1)
    assert task.logger.error.call_args('invalid web_queue message: %s', 'FOO')


def test_buffer(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt:
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 0, tz=UTC)
        task.loop()
        web_queue.send_msg('PKGPROJ', 'foo')
        task.poll()
        task.loop()
        with pytest.raises(zmq.error.Again):
            assert scribe_queue.recv_pyobj(flags=zmq.NOBLOCK)
        dt.now.return_value = datetime(2018, 1, 1, 12, 35, 0, tz=UTC)
        task.loop()
        assert scribe_queue.recv_msg() == ('PKGPROJ', 'foo')


def test_upgrade(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt:
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 0, tz=UTC)
        task.loop()
        web_queue.send_msg('PKGPROJ', 'foo')
        task.poll()
        task.loop()
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 30, tz=UTC)
        web_queue.send_msg('PKGBOTH', 'foo')
        task.poll()
        task.loop()
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 31, tz=UTC)
        web_queue.send_msg('PKGPROJ', 'bar')
        task.poll()
        task.loop()
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 32, tz=UTC)
        web_queue.send_msg('PKGPROJ', 'bar')
        task.poll()
        task.loop()
        dt.now.return_value = datetime(2018, 1, 1, 12, 35, 0, tz=UTC)
        task.loop()
        assert scribe_queue.recv_msg() == ('PKGBOTH', 'foo')
        assert scribe_queue.recv_msg() == ('PKGPROJ', 'bar')
