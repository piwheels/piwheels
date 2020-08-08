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

from conftest import MockTask
from piwheels import const, protocols, transport
from piwheels.states import MasterStats
from piwheels.master.db import RewritePendingRow
from piwheels.master.the_secretary import TheSecretary


UTC = timezone.utc


@pytest.fixture()
def scribe_queue(request, zmq_context, master_config):
    task = MockTask(zmq_context, transport.REP, const.SCRIBE_QUEUE,
                    protocols.the_scribe)
    yield task
    task.close()


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
        transport.REQ, protocol=reversed(protocols.the_scribe))
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
        'disk_size':             0,
        'disk_free':             0,
        'mem_size':              0,
        'mem_free':              0,
        'swap_size':             0,
        'swap_free':             0,
        'load_average':          0.0,
        'cpu_temp':              0.0,
    })


def test_pass_through(task, web_queue, scribe_queue, stats_data, db_queue):
    web_queue.send_msg('HOME', stats_data.as_message())
    scribe_queue.expect('HOME', stats_data.as_message())
    scribe_queue.send('DONE')
    task.poll(0)
    scribe_queue.check()
    assert web_queue.recv_msg() == ('DONE', None)

    web_queue.send_msg('SEARCH', {'foo': (0, 1)})
    scribe_queue.expect('SEARCH', {'foo': (0, 1)})
    scribe_queue.send('DONE')
    task.poll(0)
    scribe_queue.check()
    assert web_queue.recv_msg() == ('DONE', None)


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
        web_queue.send_msg('PROJECT', 'foo')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        scribe_queue.check()  # tests for empty input queue

        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 35, 0, tzinfo=UTC)
        scribe_queue.expect('PROJECT', 'foo')
        scribe_queue.send('DONE')
        task.poll(0)
        scribe_queue.check()


def test_delete_package(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt1, \
            mock.patch('piwheels.tasks.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 0, tzinfo=UTC)
        web_queue.send_msg('DELPKG', 'foo')
        scribe_queue.expect('DELPKG', 'foo')
        scribe_queue.send('DONE')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        scribe_queue.check()


def test_delete_unbuffered_version(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt1, \
            mock.patch('piwheels.tasks.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 0, tzinfo=UTC)
        web_queue.send_msg('DELVER', ('foo', '0.1'))
        scribe_queue.expect('DELVER', ('foo', '0.1'))
        scribe_queue.send('DONE')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        scribe_queue.check()


def test_delete_buffered_version(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt1, \
            mock.patch('piwheels.tasks.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 0, 0, tzinfo=UTC)
        web_queue.send_msg('PROJECT', 'foo')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        assert task.commands
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 0, tzinfo=UTC)
        web_queue.send_msg('DELVER', ('foo', '0.1'))
        scribe_queue.expect('DELVER', ('foo', '0.1'))
        scribe_queue.send('DONE')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        assert not task.commands
        scribe_queue.check()


def test_upgrade(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt1, \
            mock.patch('piwheels.tasks.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 0, tzinfo=UTC)
        task.force(task.handle_output)
        task.poll(0)
        web_queue.send_msg('PROJECT', 'foo')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 30, tzinfo=UTC)
        web_queue.send_msg('BOTH', 'foo')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 31, tzinfo=UTC)
        web_queue.send_msg('PROJECT', 'bar')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 32, tzinfo=UTC)
        web_queue.send_msg('PROJECT', 'bar')
        task.poll(0)
        assert web_queue.recv_msg() == ('DONE', None)
        scribe_queue.check()  # tests for empty input queue

        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 35, 0, tzinfo=UTC)
        scribe_queue.expect('BOTH', 'foo')
        scribe_queue.send('DONE')
        scribe_queue.expect('PROJECT', 'bar')
        scribe_queue.send('DONE')
        task.poll(0)
        scribe_queue.check()


def test_persistence(zmq_context, master_config, scribe_queue, db_queue):
    task = TheSecretary(master_config)
    try:
        db_queue.expect('LOADRWP')
        db_queue.send('OK', [
            RewritePendingRow('foo', datetime(2018, 1, 1, 12, 30, 0, tzinfo=UTC), 'PROJECT'),
            RewritePendingRow('bar', datetime(2018, 1, 1, 12, 30, 5, tzinfo=UTC), 'BOTH'),
        ])
        task.once()
        db_queue.check()

        scribe_queue.expect('PROJECT', 'foo')
        scribe_queue.send('DONE')
        scribe_queue.expect('BOTH', 'bar')
        scribe_queue.send('DONE')
        task.poll(0)
        scribe_queue.check()
    finally:
        db_queue.expect('SAVERWP', [])
        db_queue.send('OK', None)
        task.close()
        db_queue.check()
