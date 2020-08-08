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
from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pytest

from conftest import MockTask
from piwheels import const, protocols, transport
from piwheels.states import MasterStats
from piwheels.master.big_brother import BigBrother


UTC = timezone.utc


@pytest.fixture()
def db_result(request):
    return {
        'builds_time':            timedelta(0),
        'builds_size':            0,
        'packages_built':         0,
        'files_count':            0,
        'new_last_hour':          0,
        'downloads_last_hour':    0,
        'downloads_last_month':   0,
        'downloads_all':          0,
        'builds_last_hour':       {},
    }


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
        'downloads_last_hour':   0,
        'downloads_last_month':  0,
        'downloads_all':         0,
        'disk_size':             0,
        'disk_free':             0,
        'mem_size':              0,
        'mem_free':              0,
        'swap_size':             0,
        'swap_free':             0,
        'cpu_temp':              0.0,
        'load_average':          0.0,
    })


StatVFS = namedtuple('StatVFS', (
    'f_bsize',
    'f_frsize',
    'f_blocks',
    'f_bfree',
    'f_bavail',
    'f_files',
    'f_ffree',
    'f_favail',
    'f_flag',
    'f_namemax',
))


@pytest.fixture()
def stats_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.PUSH, protocol=reversed(protocols.big_brother))
    queue.hwm = 1
    queue.connect(master_config.stats_queue)
    yield queue
    queue.close()


@pytest.fixture()
def task(request, master_config):
    task = BigBrother(master_config)
    yield task
    task.close()


def test_update_homepage(db_queue, web_queue, task, db_result, stats_data):
    with mock.patch('piwheels.master.big_brother.datetime') as dt:
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 40, tzinfo=UTC)
        db_result['builds_last_hour'] = {'cp34m': 0, 'cp35m': 0}
        db_result['downloads_all'] = 1000
        db_result['downloads_last_month'] = 100
        stats_data = stats_data._replace(
            builds_last_hour={'cp34m': 0, 'cp35m': 0},
            downloads_all=1000,
            downloads_last_month=100,
        )
        db_queue.expect('GETSTATS')
        db_queue.send('OK', db_result)
        web_queue.expect('HOME', stats_data.as_message())
        web_queue.send('DONE')
        task.update_homepage()
        db_queue.check()
        web_queue.check()


def test_update_search_index(db_queue, web_queue, task):
    with mock.patch('piwheels.master.big_brother.datetime') as dt:
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 40, tzinfo=UTC)
        db_queue.expect('GETSEARCH')
        db_queue.send('OK', {'foo': (10, 100)})
        web_queue.expect('SEARCH', {'foo': [10, 100]})
        web_queue.send('DONE')
        task.update_search_index()
        db_queue.check()
        web_queue.check()


def test_update_stats(master_status_queue, task, stats_data):
    with mock.patch('piwheels.master.big_brother.datetime') as dt, \
            mock.patch('piwheels.info.get_mem_stats') as mem, \
            mock.patch('piwheels.info.get_swap_stats') as swap, \
            mock.patch('piwheels.info.get_cpu_temp') as cpu, \
            mock.patch('os.getloadavg') as load:
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 40, tzinfo=UTC)
        mem.return_value = (2, 1)
        swap.return_value = (4, 3)
        cpu.return_value = 56.0
        load.return_value = (1.3, 2.5, 3.9)
        task.update_stats()
        stats_data = stats_data._replace(
            mem_size=2, mem_free=1, swap_size=4, swap_free=3,
            cpu_temp=56.0, load_average=1.3)
        assert master_status_queue.recv_msg() == (
            'STATS', stats_data.as_message())


def test_gen_disk_stats(task, stats_queue):
    task.intervals.clear()
    with mock.patch('piwheels.master.big_brother.datetime') as dt:
        stats_queue.send_msg('STATFS', [4, 3])
        task.poll(0)
        assert task.stats.disk_size == 4
        assert task.stats.disk_free == 3


def test_gen_queue_stats(task, stats_queue):
    task.intervals.clear()
    with mock.patch('piwheels.master.big_brother.datetime') as dt:
        stats_queue.send_msg('STATBQ', {'cp34m': 1, 'cp35m': 0})
        task.poll(0)
        assert task.stats.builds_pending == {'cp34m': 1, 'cp35m': 0}


def test_gen_homepage(db_queue, db_result, web_queue, task, stats_queue,
                      stats_data):
    with mock.patch('piwheels.tasks.datetime') as dt1, \
            mock.patch('piwheels.master.big_brother.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime(2018, 1, 1, 12, 30, 40, tzinfo=UTC)
        for subtask in task.intervals:
            subtask.last_run = dt1.now.return_value
        stats_queue.send_msg('HOME')
        db_result['builds_last_hour'] = {'cp34m': 5, 'cp35m': 0}
        db_result['downloads_last_month'] = 100
        db_result['downloads_last_hour'] = 1
        stats_data = stats_data._replace(
            builds_last_hour={'cp34m': 5, 'cp35m': 0},
            downloads_last_month=100, downloads_last_hour=1
        )
        db_queue.expect('GETSEARCH')
        db_queue.send('OK', {'foo': (10, 100)})
        web_queue.expect('SEARCH', {'foo': [10, 100]})
        web_queue.send('DONE')
        db_queue.expect('GETSTATS')
        db_queue.send('OK', db_result)
        web_queue.expect('HOME', stats_data.as_message())
        web_queue.send('DONE')
        # Crank the handle once (handles HOME message) but no periodic tasks
        task.poll(0)
        # Crank it again to run the forced periodic tasks
        task.poll(0)
        db_queue.check()
        web_queue.check()


def test_bad_stats(task, stats_queue):
    task.logger = mock.Mock()
    with mock.patch('piwheels.tasks.datetime') as dt:
        dt.now.return_value = datetime(2018, 1, 1, 12, 30, 40, tzinfo=UTC)
        for subtask in task.intervals:
            subtask.last_run = dt.now.return_value
        stats_queue.send(b'FOO')
        task.poll(0)
        assert task.logger.error.call_args == mock.call(
            'unable to deserialize data')
