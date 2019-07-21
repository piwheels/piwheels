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

import pytest

from piwheels import const, protocols, transport
from piwheels.states import MasterStats
from piwheels.master.db import RewritePendingRow
from piwheels.master.the_secretary import TheSecretary


UTC = timezone.utc


@pytest.fixture()
def scribe_queue(request, zmq_context):
    queue = zmq_context.socket(transport.PULL, protocol=protocols.the_scribe)
    queue.hwm = 10
    queue.bind(const.SCRIBE_QUEUE)
    yield queue
    queue.close()


@pytest.fixture()
def task(request, zmq_context, master_config, scribe_queue, db_queue):
    task = TheSecretary(master_config)
    db_queue.expect('LOADRWP')
    db_queue.send('OK', [])
    task.once()
    db_queue.check()
    yield task
    db_queue.expect('SAVERWP', [])
    db_queue.send('OK', None)
    task.close()
    db_queue.check()


@pytest.fixture()
def web_queue(request, zmq_context, task, master_config):
    queue = zmq_context.socket(
        transport.PUSH, protocol=reversed(protocols.the_scribe))
    queue.hwm = 10
    queue.connect(master_config.web_queue)
    yield queue
    queue.close()


@pytest.fixture()
def stats_data(request):
    return MasterStats(**{
        'timestamp':             datetime(2018, 1, 1, 12, 30, 40, tzinfo=UTC),
        'packages_built':        0,
        'builds_last_hour':      {},
        'builds_time':           timedelta(0),
        'builds_size':           0,
        'builds_pending':        {},
        'new_last_hour':         0,
        'files_count':           0,
        'downloads_last_hour':   1,
        'downloads_last_month':  10,
        'downloads_all':         100,
        'disk_free':             0,
        'disk_size':             0,
        'mem_free':              0,
        'mem_size':              0,
        'cpu_temp':              0.0,
        'load_average':          0.0,
    })


def test_pass_through(task, web_queue, scribe_queue, stats_data, db_queue):
    web_queue.send_msg('HOME', stats_data.as_message())
    task.poll(0)
    assert scribe_queue.recv_msg() == ('HOME', stats_data.as_message())
    web_queue.send_msg('SEARCH', {'foo': (0, 1)})
    task.poll(0)
    assert scribe_queue.recv_msg() == ('SEARCH', {'foo': [0, 1]})


def test_bad_request(task, web_queue):
    web_queue.send(b'FOO')
    e = Event()
    task.logger = mock.Mock()
    task.logger.error.side_effect = lambda *args: e.set()
    task.poll(0)
    assert e.wait(1)
    assert task.logger.error.call_args('invalid web_queue message: %s', 'FOO')


def test_buffer(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt1, \
            mock.patch('piwheels.tasks.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 0, tzinfo=UTC)
        task.force(task.handle_output)
        task.poll(0)
        web_queue.send_msg('PKGPROJ', 'foo')
        task.poll(0)
        with pytest.raises(transport.Again):
            scribe_queue.recv_msg(flags=transport.NOBLOCK)
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 35, 0, tzinfo=UTC)
        task.poll(0)
        assert scribe_queue.recv_msg() == ('PKGPROJ', 'foo')


def test_upgrade(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt1, \
            mock.patch('piwheels.tasks.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 0, tzinfo=UTC)
        task.force(task.handle_output)
        task.poll(0)
        web_queue.send_msg('PKGPROJ', 'foo')
        task.poll(0)
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 30, tzinfo=UTC)
        web_queue.send_msg('PKGBOTH', 'foo')
        task.poll(0)
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 31, tzinfo=UTC)
        web_queue.send_msg('PKGPROJ', 'bar')
        task.poll(0)
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 32, tzinfo=UTC)
        web_queue.send_msg('PKGPROJ', 'bar')
        task.poll(0)
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 35, 0, tzinfo=UTC)
        task.poll(0)
        assert scribe_queue.recv_msg() == ('PKGBOTH', 'foo')
        assert scribe_queue.recv_msg() == ('PKGPROJ', 'bar')


def test_persistence(zmq_context, master_config, scribe_queue, db_queue):
    task = TheSecretary(master_config)
    try:
        db_queue.expect('LOADRWP')
        db_queue.send('OK', [
            RewritePendingRow('foo', datetime(2018, 1, 1, 12, 30, 0, tzinfo=UTC), 'PKGPROJ'),
            RewritePendingRow('bar', datetime(2018, 1, 1, 12, 30, 5, tzinfo=UTC), 'PKGBOTH'),
        ])
        task.once()
        db_queue.check()
        task.poll(0)
        assert scribe_queue.recv_msg() == ('PKGPROJ', 'foo')
        assert scribe_queue.recv_msg() == ('PKGBOTH', 'bar')
    finally:
        db_queue.expect('SAVERWP', [])
        db_queue.send('OK', None)
        task.close()
        db_queue.check()
