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


from datetime import datetime, timedelta
from unittest import mock

import zmq
import pytest

from piwheels import const
from piwheels.master.tasks import TaskQuit
from piwheels.master.slave_driver import SlaveDriver
from piwheels.master.states import SlaveState, BuildState


@pytest.fixture()
def builds_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PUSH)
    queue.hwm = 1
    queue.bind(master_config.builds_queue)
    yield queue
    queue.close()


@pytest.fixture()
def index_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PULL)
    queue.hwm = 1
    queue.bind(master_config.index_queue)
    yield queue
    queue.close()


@pytest.fixture()
def stats_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PULL)
    queue.hwm = 1
    queue.bind(master_config.stats_queue)
    yield queue
    queue.close()


@pytest.fixture()
def task(request, zmq_context, builds_queue, index_queue, stats_queue,
         master_status_queue, master_config):
    SlaveState.status_queue = zmq_context.socket(zmq.PUSH)
    SlaveState.status_queue.hwm = 1
    SlaveState.status_queue.connect(const.INT_STATUS_QUEUE)
    SlaveState.counter = 0
    task = SlaveDriver(master_config)
    yield task
    task.close()
    SlaveState.counter = 0


@pytest.fixture()
def slave_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.REQ)
    queue.hwm = 1
    queue.connect(master_config.slave_queue)
    yield queue
    queue.close()


@pytest.fixture()
def slave2_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.REQ)
    queue.hwm = 1
    queue.connect(master_config.slave_queue)
    yield queue
    queue.close()


def test_control_quit(task):
    with pytest.raises(TaskQuit):
        task.quit()
        task.poll()


def test_control_pause(task):
    assert not task.paused
    task.pause()
    task.poll()
    assert task.paused
    task.resume()
    task.poll()
    assert not task.paused


def test_control_bad_message(task):
    task.logger = mock.Mock()
    task.logger.error.call_count == 0
    task._ctrl(['FOO'])
    task.poll()
    task.logger.error.call_count == 1


def test_new_builds(task, builds_queue, stats_queue):
    assert not task.abi_queues
    builds_queue.send_pyobj(['cp34m', 'foo', '0.1'])
    task.poll()
    assert task.abi_queues['cp34m'] == {('foo', '0.1')}
    assert stats_queue.recv_pyobj() == ['STATBQ', {'cp34m': 1}]
    builds_queue.send_pyobj(['cp35m', 'foo', '0.1'])
    task.poll()
    assert task.abi_queues['cp35m'] == {('foo', '0.1')}
    assert stats_queue.recv_pyobj() == ['STATBQ', {'cp34m': 1, 'cp35m': 1}]


def test_slave_says_hello(task, slave_queue):
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    for state in task.slaves.values():
        assert state.slave_id == 1
        assert state.timeout == timedelta(minutes=5)
        assert state.label == 'piwheels1'
        assert state.native_abi == 'cp34m'
        assert state.native_py_version == 'cp34'
        assert state.native_platform == 'linux_armv7l'
        assert not state.expired
        assert state.build is None
        break
    else:
        assert False, "No slaves found"


def test_slave_invalid_message(task, slave_queue):
    task.logger = mock.Mock()
    slave_queue.send(b'HELLO')
    task.poll()
    assert not task.slaves
    assert task.logger.error.call_count == 1


def test_slave_invalid_first_message(task, slave_queue):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['FOO', 'BAR'])
    task.poll()
    assert not task.slaves
    assert task.logger.error.call_count == 1


def test_slave_protocol_error(task, slave_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    assert task.logger.error.call_count == 0
    slave_queue.send_pyobj(['FOO'])
    task.poll()
    assert task.logger.error.call_count == 1


def test_slave_commits_suicide(task, slave_queue, master_status_queue,
                               master_config):
    with mock.patch('piwheels.master.states.datetime') as dt:
        dt.utcnow.return_value = datetime.utcnow()
        task.logger = mock.Mock()
        slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                                'linux_armv7l', 'piwheels1'])
        task.poll()
        assert task.logger.warning.call_count == 1
        assert slave_queue.recv_pyobj() == ['HELLO', 1,
                                            master_config.pypi_simple]
        assert master_status_queue.recv_pyobj() == [
            1, dt.utcnow.return_value, 'HELLO', timedelta(seconds=300),
            'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'
        ]
        assert task.slaves
        slave_queue.send_pyobj(['BYE'])
        task.poll()
        assert task.logger.warning.call_count == 2
        assert master_status_queue.recv_pyobj() == [1, dt.utcnow.return_value,
                                                    'BYE']
        assert not task.slaves


def test_master_lists_nothing(task, master_status_queue):
    task.list_slaves()
    task.poll()
    with pytest.raises(zmq.ZMQError):
        master_status_queue.recv_pyobj(flags=zmq.NOBLOCK)


def test_master_lists_slaves(task, slave_queue, master_config,
                             master_status_queue):
    with mock.patch('piwheels.master.states.datetime') as dt:
        dt.utcnow.return_value = datetime.utcnow()
        slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                                'linux_armv7l', 'piwheels1'])
        task.poll()
        assert slave_queue.recv_pyobj() == ['HELLO', 1,
                                            master_config.pypi_simple]
        assert master_status_queue.recv_pyobj() == [
            1, dt.utcnow.return_value, 'HELLO', timedelta(seconds=300),
            'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'
        ]
        task.list_slaves()
        task.poll()
        assert master_status_queue.recv_pyobj() == [
            1, dt.utcnow.return_value, 'HELLO', timedelta(seconds=300),
            'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'
        ]


def test_slave_remove_expired(task, slave_queue, master_config,
                              master_status_queue):
    with mock.patch('piwheels.master.states.datetime') as dt:
        dt.utcnow.return_value = datetime.utcnow()
        slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                                'linux_armv7l', 'piwheels1'])
        task.poll()
        assert len(task.slaves) == 1
        assert master_status_queue.recv_pyobj() == [
            1, dt.utcnow.return_value, 'HELLO', timedelta(seconds=300),
            'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'
        ]
        old_now = dt.utcnow.return_value
        dt.utcnow.return_value = dt.utcnow.return_value + timedelta(hours=4)
        task.loop()
        assert len(task.slaves) == 0
        assert master_status_queue.recv_pyobj() == [1, old_now, 'BYE']


def test_slave_says_hello(task, slave_queue):
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    for state in task.slaves.values():
        assert state.slave_id == 1
        assert state.timeout == timedelta(minutes=5)
        assert state.label == 'piwheels1'
        assert state.native_abi == 'cp34m'
        assert state.native_py_version == 'cp34'
        assert state.native_platform == 'linux_armv7l'
        assert not state.expired
        assert state.build is None
        break
    else:
        assert False, "No slaves found"


def test_slave_says_idle_invalid(task, slave_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    for slave in task.slaves.values():
        slave.reply = ['SEND', 'foo-0.1-py3-none-any.whl']
        break
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_pyobj() == ['BYE']


def test_master_kills_nothing(task):
    task.logger = mock.Mock()
    task.kill_slave(1)
    task.poll()
    assert task.logger.error.call_count == 0


def test_master_says_idle_when_terminated(task, slave_queue, master_config):
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    task.kill_slave(1)
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BYE']


def test_master_kills_correct_slave(task, slave_queue, master_config):
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    task.kill_slave(2)
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['SLEEP']


def test_slave_says_idle_no_builds(task, slave_queue, builds_queue,
                                   master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['SLEEP']


def test_slave_says_idle_with_build(task, slave_queue, builds_queue,
                                    master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    builds_queue.send_pyobj(['cp34m', 'foo', '0.1'])
    task.poll()
    builds_queue.send_pyobj(['cp35m', 'bar', '0.1'])
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BUILD', 'foo', '0.1']


def test_slave_says_idle_with_active_build(task, slave_queue, slave2_queue,
                                           builds_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    slave2_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels2'])
    task.poll()
    assert slave2_queue.recv_pyobj() == ['HELLO', 2, master_config.pypi_simple]
    builds_queue.send_pyobj(['cp34m', 'foo', '0.1'])
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BUILD', 'foo', '0.1']
    builds_queue.send_pyobj(['cp34m', 'foo', '0.1'])
    task.poll()
    slave2_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave2_queue.recv_pyobj() == ['SLEEP']


def test_slave_says_idle_when_paused(task, slave_queue, builds_queue,
                                     master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    builds_queue.send_pyobj(['cp34m', 'foo', '0.1'])
    task.poll()
    task.pause()
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['SLEEP']
    task.resume()
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BUILD', 'foo', '0.1']


def test_slave_says_built_invalid(task, slave_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    slave_queue.send_pyobj(['BUILT', False, 5, '', {}])
    task.poll()
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_pyobj() == ['BYE']


def test_slave_says_built_failed(task, db_queue, slave_queue, builds_queue,
                                 index_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    builds_queue.send_pyobj(['cp34m', 'foo', '0.1'])
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BUILD', 'foo', '0.1']
    slave_queue.send_pyobj(['BUILT', False, 5, '', {}])
    db_queue.expect(['LOGBUILD',
                     BuildState(1, 'foo', '0.1', 'cp34m', False, 5, '', {})])
    db_queue.send(['OK', 1])
    task.poll()
    assert task.logger.info.call_count == 2
    assert index_queue.recv_pyobj() == ['PKG', 'foo']
    assert slave_queue.recv_pyobj() == ['DONE']
    db_queue.check()


def test_slave_says_built_succeeded(task, db_queue, fs_queue, slave_queue,
                                    builds_queue, index_queue, master_config,
                                    file_state, file_state_hacked):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    builds_queue.send_pyobj(['cp34m', 'foo', '0.1'])
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BUILD', 'foo', '0.1']
    slave_queue.send_pyobj([
        'BUILT', True, 5, 'Woohoo!', {file_state.filename: file_state[1:8]}
    ])
    db_queue.expect([
        'LOGBUILD', BuildState(
            1, 'foo', '0.1', 'cp34m', True, 5, 'Woohoo!',
            {
                file_state.filename: file_state,
                file_state_hacked.filename: file_state_hacked
            }
        )
    ])
    db_queue.send(['OK', 1])
    fs_queue.expect(['EXPECT', 1, file_state])
    fs_queue.send(['OK', None])
    task.poll()
    assert task.logger.info.call_count == 3
    assert slave_queue.recv_pyobj() == ['SEND', file_state.filename]
    db_queue.check()
    fs_queue.check()


def test_slave_says_sent_invalid(task, slave_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    slave_queue.send_pyobj(['SENT'])
    task.poll()
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_pyobj() == ['BYE']


def test_slave_says_sent_failed(task, db_queue, fs_queue, slave_queue,
                                builds_queue, master_config,
                                build_state_hacked):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    builds_queue.send_pyobj(['cp34m', bs.package, bs.version])
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BUILD', bs.package, bs.version]
    slave_queue.send_pyobj([
        'BUILT', bs.status, bs.duration, bs.output, {fs1.filename: fs1[1:8]}
    ])
    db_queue.expect(['LOGBUILD', bs])
    db_queue.send(['OK', 1])
    fs_queue.expect(['EXPECT', 1, fs1])
    fs_queue.send(['OK', None])
    task.poll()
    assert slave_queue.recv_pyobj() == ['SEND', fs1.filename]
    slave_queue.send_pyobj(['SENT'])
    fs_queue.expect(['VERIFY', 1, bs.package])
    fs_queue.send(['ERR', IOError()])
    task.poll()
    assert slave_queue.recv_pyobj() == ['SEND', fs1.filename]
    db_queue.check()
    fs_queue.check()


def test_slave_says_sent_succeeded(task, db_queue, fs_queue, slave_queue,
                                   builds_queue, index_queue, master_config,
                                   build_state_hacked):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    builds_queue.send_pyobj(['cp34m', bs.package, bs.version])
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BUILD', bs.package, bs.version]
    slave_queue.send_pyobj([
        'BUILT', bs.status, bs.duration, bs.output, {fs1.filename: fs1[1:8]}
    ])
    db_queue.expect(['LOGBUILD', bs])
    db_queue.send(['OK', 1])
    fs_queue.expect(['EXPECT', 1, fs1])
    fs_queue.send(['OK', None])
    task.poll()
    assert slave_queue.recv_pyobj() == ['SEND', fs1.filename]
    slave_queue.send_pyobj(['SENT'])
    fs_queue.expect(['VERIFY', 1, bs.package])
    fs_queue.send(['OK', None])
    task.poll()
    assert index_queue.recv_pyobj() == ['PKG', bs.package]
    assert slave_queue.recv_pyobj() == ['DONE']
    db_queue.check()
    fs_queue.check()


def test_slave_says_sent_succeeded_more(task, db_queue, fs_queue, slave_queue,
                                        builds_queue, index_queue,
                                        master_config, build_state_hacked):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    fs2._transferred = False
    slave_queue.send_pyobj(['HELLO', 300, 'cp34', 'cp34m',
                            'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['HELLO', 1, master_config.pypi_simple]
    builds_queue.send_pyobj(['cp34m', bs.package, bs.version])
    task.poll()
    slave_queue.send_pyobj(['IDLE'])
    task.poll()
    assert slave_queue.recv_pyobj() == ['BUILD', bs.package, bs.version]
    slave_queue.send_pyobj([
        'BUILT', bs.status, bs.duration, bs.output, {
            f.filename: f[1:8] for f in bs.files.values()
        }
    ])
    db_queue.expect(['LOGBUILD', bs])
    db_queue.send(['OK', 1])
    fs_queue.expect(['EXPECT', 1, fs2])
    fs_queue.send(['OK', None])
    task.poll()
    assert slave_queue.recv_pyobj() == ['SEND', fs2.filename]
    slave_queue.send_pyobj(['SENT'])
    fs_queue.expect(['VERIFY', 1, bs.package])
    fs_queue.send(['OK', None])
    fs_queue.expect(['EXPECT', 1, fs1])
    fs_queue.send(['OK', None])
    task.poll()
    assert index_queue.recv_pyobj() == ['PKG', bs.package]
    assert slave_queue.recv_pyobj() == ['SEND', fs1.filename]
    db_queue.check()
    fs_queue.check()
