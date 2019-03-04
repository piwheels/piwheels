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


from datetime import datetime, timedelta, timezone
from unittest import mock

import zmq
import pytest

from piwheels import const, protocols
from piwheels.master.tasks import TaskQuit
from piwheels.master.slave_driver import SlaveDriver
from piwheels.master.states import SlaveState, BuildState


UTC = timezone.utc


@pytest.fixture()
def builds_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PUSH, protocol=protocols.the_architect)
    queue.hwm = 1
    queue.bind(master_config.builds_queue)
    yield queue
    queue.close()


@pytest.fixture()
def web_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        zmq.PULL, protocol=protocols.the_scribe)
    queue.hwm = 1
    queue.bind(master_config.web_queue)
    yield queue
    queue.close()


@pytest.fixture()
def stats_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        zmq.PULL, protocol=protocols.big_brother)
    queue.hwm = 1
    queue.bind(master_config.stats_queue)
    yield queue
    queue.close()


@pytest.fixture()
def task(request, zmq_context, builds_queue, web_queue, stats_queue,
         master_status_queue, master_config):
    SlaveState.status_queue = zmq_context.socket(
        zmq.PUSH, protocol=reversed(protocols.slave_driver))
    SlaveState.status_queue.hwm = 1
    SlaveState.status_queue.connect(const.INT_STATUS_QUEUE)
    SlaveState.counter = 0
    task = SlaveDriver(master_config)
    yield task
    task.close()
    SlaveState.counter = 0


@pytest.fixture()
def slave_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        zmq.REQ, protocol=reversed(protocols.slave_driver))
    queue.hwm = 1
    queue.connect(master_config.slave_queue)
    yield queue
    queue.close()


@pytest.fixture()
def slave2_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        zmq.REQ, protocol=reversed(protocols.slave_driver))
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


def test_new_builds(task, builds_queue, stats_queue):
    assert not task.abi_queues
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll()
    assert task.abi_queues['cp34m'] == [('foo', '0.1')]
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    builds_queue.send_msg('QUEUE', {'cp35m': [('foo', '0.1')]})
    task.poll()
    assert task.abi_queues['cp35m'] == [('foo', '0.1')]
    assert stats_queue.recv_msg() == ('STATBQ', {'cp35m': 1})


def test_slave_says_hello(task, slave_queue):
    slave_queue.send_msg('HELLO', [
        300.0, 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
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
    slave_queue.send(b'FOO')
    task.poll()
    assert not task.slaves
    assert task.logger.error.call_count == 1


def test_slave_invalid_first_message(task, slave_queue):
    task.logger = mock.Mock()
    slave_queue.send_msg('IDLE')
    task.poll()
    assert not task.slaves
    assert task.logger.error.call_count == 1


def test_builds_invalid_message(task, builds_queue):
    task.logger = mock.Mock()
    builds_queue.send(b'FOO')
    task.poll()
    assert not task.abi_queues
    assert task.logger.error.call_count == 1


def test_slave_protocol_error(task, slave_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    assert task.logger.error.call_count == 0
    slave_queue.send(b'FOO')
    task.poll()
    assert task.logger.error.call_count == 1


def test_slave_commits_suicide(task, slave_queue, master_status_queue,
                               master_config):
    with mock.patch('piwheels.master.states.datetime') as dt:
        dt.now.return_value = datetime.now(tz=UTC)
        task.logger = mock.Mock()
        slave_queue.send_msg('HELLO', [
            timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l',
            'piwheels1'])
        task.poll()
        assert task.logger.warning.call_count == 1
        assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
        assert master_status_queue.recv_msg() == (
            'SLAVE', [
                1, dt.now.return_value, 'ACK', [1, 'https://pypi.org/simple']
            ]
        )
        assert task.slaves
        slave_queue.send_msg('BYE')
        task.poll()
        assert task.logger.warning.call_count == 2
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt.now.return_value, 'DIE', protocols.NoData]
        )
        assert not task.slaves


def test_master_lists_nothing(task, master_status_queue):
    task.list_slaves()
    task.poll()
    with pytest.raises(zmq.ZMQError):
        master_status_queue.recv_msg(flags=zmq.NOBLOCK)


def test_master_lists_slaves(task, slave_queue, master_config,
                             master_status_queue):
    with mock.patch('piwheels.master.states.datetime') as dt:
        dt.now.return_value = datetime.now(tz=UTC)
        slave_queue.send_msg('HELLO', [
            timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l',
            'piwheels1'])
        task.poll()
        assert slave_queue.recv_msg() == ('ACK', [
            1, master_config.pypi_simple])
        assert master_status_queue.recv_msg() == (
            'SLAVE', [
                1, dt.now.return_value, 'ACK', [
                    1, 'https://pypi.org/simple'
                ]
            ]
        )
        task.list_slaves()
        task.poll()
        assert master_status_queue.recv_msg() == (
            'SLAVE', [
                1, dt.now.return_value, 'HELLO', [
                    timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l',
                    'piwheels1'
                ]
            ]
        )


def test_slave_remove_expired(task, slave_queue, master_config,
                              master_status_queue):
    with mock.patch('piwheels.master.states.datetime') as dt:
        dt.now.return_value = datetime.now(tz=UTC)
        slave_queue.send_msg('HELLO', [
            timedelta(seconds=300),
            'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
        task.poll()
        assert len(task.slaves) == 1
        assert master_status_queue.recv_msg() == (
            'SLAVE', [
                1, dt.now.return_value, 'ACK',
                [1, 'https://pypi.org/simple']
            ]
        )
        old_now = dt.now.return_value
        dt.now.return_value = dt.now.return_value + timedelta(hours=4)
        task.loop()
        assert len(task.slaves) == 0
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, old_now, 'BYE', None])


def test_slave_says_hello(task, slave_queue):
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
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


def test_slave_says_idle_invalid(task, slave_queue, master_config, stats_queue):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    for slave in task.slaves.values():
        slave.reply = ('SEND', 'foo-0.1-py3-none-any.whl')
        break
    slave_queue.send_msg('IDLE')
    task.poll()
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_msg() == ('DIE', None)


def test_master_kills_nothing(task):
    task.logger = mock.Mock()
    task.kill_slave(1)
    task.poll()
    assert task.logger.error.call_count == 0


def test_master_says_idle_when_terminated(task, slave_queue, master_config):
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    task.kill_slave(1)
    task.poll()
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('DIE', None)


def test_master_kills_correct_slave(task, slave_queue, master_config,
                                    stats_queue):
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    task.kill_slave(2)
    task.poll()
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('SLEEP', None)
    assert stats_queue.recv_msg() == ('STATBQ', {})


def test_slave_says_idle_no_builds(task, slave_queue, builds_queue,
                                   master_config, stats_queue):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('SLEEP', None)
    assert stats_queue.recv_msg() == ('STATBQ', {})


def test_slave_says_idle_with_build(task, slave_queue, builds_queue,
                                    master_config, stats_queue):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')],
                                    'cp35m': [('bar', '0.1')]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1, 'cp35m': 1})
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0, 'cp35m': 1})


def test_slave_says_idle_with_active_build(task, slave_queue, slave2_queue,
                                           builds_queue, stats_queue,
                                           master_config):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    slave2_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels2'])
    task.poll()
    assert slave2_queue.recv_msg() == ('ACK', [2, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll()
    slave2_queue.send_msg('IDLE')
    task.poll()
    assert slave2_queue.recv_msg() == ('SLEEP', None)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})


def test_slave_says_idle_when_paused(task, slave_queue, builds_queue,
                                     master_config, stats_queue):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    task.pause()
    task.poll()
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('SLEEP', None)
    task.resume()
    task.poll()
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})


def test_slave_says_built_invalid(task, slave_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    slave_queue.send_msg('BUILT', [False, timedelta(seconds=5), '', []])
    task.poll()
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_msg() == ('DIE', None)


def test_slave_says_built_failed(task, db_queue, slave_queue, builds_queue,
                                 web_queue, master_config, stats_queue):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [False, timedelta(seconds=5), '', []])
    bs = BuildState(
        1, 'foo', '0.1', 'cp34m', False, timedelta(seconds=5), '', {})
    db_queue.expect('LOGBUILD', bs.as_message())
    db_queue.send('OK', 1)
    task.poll()
    assert task.logger.info.call_count == 2
    assert web_queue.recv_msg() == ('PKGPROJ', 'foo')
    assert slave_queue.recv_msg() == ('DONE', None)
    db_queue.check()


def test_slave_says_built_succeeded(task, db_queue, fs_queue, slave_queue,
                                    builds_queue, web_queue, stats_queue,
                                    master_config, file_state,
                                    file_state_hacked):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [
        True, timedelta(seconds=5), 'Woohoo!', [file_state.as_message()]
    ])
    db_queue.expect(
        'LOGBUILD', BuildState(
            1, 'foo', '0.1', 'cp34m', True, timedelta(seconds=5), 'Woohoo!',
            {
                file_state.filename: file_state,
                file_state_hacked.filename: file_state_hacked
            }
        ).as_message()
    )
    db_queue.send('OK', 1)
    fs_queue.expect('EXPECT', [1, file_state.as_message()])
    fs_queue.send('OK')
    task.poll()
    assert task.logger.info.call_count == 3
    assert slave_queue.recv_msg() == ('SEND', file_state.filename)
    db_queue.check()
    fs_queue.check()


def test_slave_says_sent_invalid(task, slave_queue, master_config):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    slave_queue.send_msg('SENT')
    task.poll()
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_msg() == ('DIE', None)


def test_slave_says_sent_failed(task, db_queue, fs_queue, slave_queue,
                                builds_queue, stats_queue, master_config,
                                build_state_hacked):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [(bs.package, bs.version)]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('BUILD', [bs.package, bs.version])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [
        bs.status, bs.duration, bs.output, [fs1.as_message()]
    ])
    db_queue.expect('LOGBUILD', bs.as_message())
    db_queue.send('OK', 1)
    fs_queue.expect('EXPECT', [1, fs1.as_message()])
    fs_queue.send('OK')
    task.poll()
    assert slave_queue.recv_msg() == ('SEND', fs1.filename)
    slave_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [1, bs.package])
    fs_queue.send('ERROR', '')
    task.poll()
    assert slave_queue.recv_msg() == ('SEND', fs1.filename)
    db_queue.check()
    fs_queue.check()


def test_slave_says_sent_succeeded(task, db_queue, fs_queue, slave_queue,
                                   builds_queue, web_queue, stats_queue,
                                   master_config, build_state_hacked):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [(bs.package, bs.version)]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('BUILD', [bs.package, bs.version])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [
        bs.status, bs.duration, bs.output, [fs1.as_message()]
    ])
    db_queue.expect('LOGBUILD', bs.as_message())
    db_queue.send('OK', 1)
    fs_queue.expect('EXPECT', [1, fs1.as_message()])
    fs_queue.send('OK')
    task.poll()
    assert slave_queue.recv_msg() == ('SEND', fs1.filename)
    slave_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [1, bs.package])
    fs_queue.send('OK')
    task.poll()
    assert web_queue.recv_msg() == ('PKGBOTH', bs.package)
    assert slave_queue.recv_msg() == ('DONE', None)
    db_queue.check()
    fs_queue.check()


def test_slave_says_sent_succeeded_more(task, db_queue, fs_queue, slave_queue,
                                        builds_queue, web_queue, stats_queue,
                                        master_config, build_state_hacked):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    fs2._transferred = False
    slave_queue.send_msg('HELLO', [
        timedelta(seconds=300), 'cp34', 'cp34m', 'linux_armv7l', 'piwheels1'])
    task.poll()
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [(bs.package, bs.version)]})
    task.poll()
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE')
    task.poll()
    assert slave_queue.recv_msg() == ('BUILD', [bs.package, bs.version])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [
        bs.status, bs.duration, bs.output,
        [f.as_message() for f in bs.files.values()]
    ])
    db_queue.expect('LOGBUILD', bs.as_message())
    db_queue.send('OK', 1)
    fs_queue.expect('EXPECT', [1, fs2.as_message()])
    fs_queue.send('OK')
    task.poll()
    assert slave_queue.recv_msg() == ('SEND', fs2.filename)
    slave_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [1, bs.package])
    fs_queue.send('OK')
    fs_queue.expect('EXPECT', [1, fs1.as_message()])
    fs_queue.send('OK')
    task.poll()
    assert slave_queue.recv_msg() == ('SEND', fs1.filename)
    db_queue.check()
    fs_queue.check()
