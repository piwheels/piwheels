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
from datetime import datetime, timedelta

import zmq
import pytest

from piwheels import const
from piwheels.master.big_brother import BigBrother


@pytest.fixture()
def stats_result(request):
    return [
        ('packages_count',         1),
        ('packages_built',         0),
        ('versions_count',         2),
        ('versions_tried',         0),
        ('builds_count',           0),
        ('builds_count_success',   0),
        ('builds_count_last_hour', 0),
        ('builds_time',            timedelta(0)),
        ('files_count',            0),
        ('builds_size',            0),
        ('downloads_last_month',   10),
    ]


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
def stats_disk(request):
    return StatVFS(
        4096, 4096, 1000000, 50000, 40000, 1000000, 500000, 500000, 4096,
        255)


@pytest.fixture()
def index_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PULL)
    queue.hwm = 1
    queue.bind(master_config.index_queue)
    def fin():
        queue.close()
    request.addfinalizer(fin)
    return queue


@pytest.fixture()
def task(request, zmq_context, master_config, db_queue, index_queue,
         master_status_queue):
    task = BigBrother(master_config)
    task.start()
    def fin():
        task.quit()
        task.join(2)
        if task.is_alive():
            raise RuntimeError('failed to kill big_brother task')
    request.addfinalizer(fin)
    return task


@pytest.fixture()
def stats_queue(request, zmq_context):
    queue = zmq_context.socket(zmq.PUSH)
    queue.hwm = 1
    queue.connect(const.STATS_QUEUE)
    def fin():
        queue.close()
    request.addfinalizer(fin)
    return queue


def cycle(db_queue, stats_result, index_queue, stats_dict,
          master_status_queue):
    assert db_queue.recv_pyobj() == ['GETSTATS']
    db_queue.send_pyobj(['OK', stats_result])
    assert index_queue.recv_pyobj() == ['HOME', stats_dict]
    msg = master_status_queue.recv_pyobj()
    assert msg == [-1, msg[1], 'STATUS', stats_dict]
    assert db_queue.recv_pyobj() == ['GETDL']
    db_queue.send_pyobj(['OK', {'foo': 10}])
    assert index_queue.recv_pyobj() == ['SEARCH', [('foo', 10)]]


def test_gen_stats(db_queue, master_status_queue, index_queue, task,
                   stats_result, stats_dict):
    with mock.patch('piwheels.master.big_brother.datetime') as dt:
        # There should be one initial cycle (because __init__ sets the time in
        # the past) then nothing
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 40)
        task.timestamp = datetime(2018, 1, 1, 12, 30, 0)
        cycle(db_queue, stats_result, index_queue, stats_dict,
              master_status_queue)


def test_gen_disk_stats(db_queue, master_status_queue, index_queue, task,
                        stats_queue, stats_result, stats_dict, stats_disk):
    with mock.patch('piwheels.master.big_brother.datetime') as dt:
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 40)
        task.timestamp = datetime(2018, 1, 1, 12, 30, 0)
        cycle(db_queue, stats_result, index_queue, stats_dict,
              master_status_queue)
        # Push disk stats in and skip time forward to permit another cycle
        stats_queue.send_pyobj(['STATFS', stats_disk])
        stats_dict['disk_free'] = stats_disk.f_frsize * stats_disk.f_bavail
        stats_dict['disk_size'] = stats_disk.f_frsize * stats_disk.f_blocks
        dt.utcnow.return_value = task.timestamp + timedelta(seconds=40)
        cycle(db_queue, stats_result, index_queue, stats_dict,
              master_status_queue)


def test_gen_queue_stats(db_queue, master_status_queue, index_queue, task,
                         stats_queue, stats_result, stats_dict):
    with mock.patch('piwheels.master.big_brother.datetime') as dt:
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 40)
        task.timestamp = datetime(2018, 1, 1, 12, 30, 0)
        cycle(db_queue, stats_result, index_queue, stats_dict,
              master_status_queue)
        # Push queue stats in and skip time forward to permit another cycle
        stats_queue.send_pyobj(['STATBQ', {'cp34m': 1, 'cp35m': 0}])
        stats_dict['builds_pending'] = 1
        dt.utcnow.return_value = task.timestamp + timedelta(seconds=40)
        cycle(db_queue, stats_result, index_queue, stats_dict,
              master_status_queue)


def test_bad_stats(db_queue, master_status_queue, index_queue, task,
                         stats_queue, stats_result, stats_dict):
    task.logger = mock.Mock()
    with mock.patch('piwheels.master.big_brother.datetime') as dt:
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 40)
        task.timestamp = datetime(2018, 1, 1, 12, 30, 0)
        cycle(db_queue, stats_result, index_queue, stats_dict,
              master_status_queue)
        # Push bad stats, advance time and perform another cycle
        stats_queue.send_pyobj(['FOO'])
        dt.utcnow.return_value = task.timestamp + timedelta(seconds=40)
        cycle(db_queue, stats_result, index_queue, stats_dict,
              master_status_queue)
        assert task.logger.error.call_args == mock.call(
            'invalid big_brother message: %s', 'FOO')
