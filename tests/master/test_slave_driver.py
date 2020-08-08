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

import pytest

from piwheels import const, protocols, tasks, transport
from piwheels.states import SlaveState, BuildState
from piwheels.master.slave_driver import SlaveDriver


UTC = timezone.utc


@pytest.fixture()
def builds_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(transport.PUSH, protocol=protocols.the_architect)
    queue.hwm = 1
    queue.connect(master_config.builds_queue)
    yield queue
    queue.close()


@pytest.fixture()
def stats_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.PULL, protocol=protocols.big_brother)
    queue.hwm = 1
    queue.bind(master_config.stats_queue)
    yield queue
    queue.close()


@pytest.fixture()
def task(request, zmq_context, web_queue, stats_queue, master_status_queue,
         master_config):
    SlaveState.status_queue = zmq_context.socket(
        transport.PUSH, protocol=reversed(protocols.slave_driver))
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
        transport.REQ, protocol=reversed(protocols.slave_driver))
    queue.hwm = 1
    queue.connect(master_config.slave_queue)
    yield queue
    queue.close()


@pytest.fixture()
def slave2_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.REQ, protocol=reversed(protocols.slave_driver))
    queue.hwm = 1
    queue.connect(master_config.slave_queue)
    yield queue
    queue.close()


@pytest.fixture()
def delete_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.REQ, protocol=protocols.cloud_gazer)
    queue.connect(const.SKIP_QUEUE)
    yield queue
    queue.close()


@pytest.fixture()
def hello_data(request):
    return [
        timedelta(hours=3), timedelta(seconds=300),
        'cp34', 'cp34m', 'linux_armv7l', 'piwheels1',
        'Raspbian GNU/Linux', '9 (stretch)', 'a020d3', '12345678'
    ]


def stats_data(now=None):
    if now is None:
        now = datetime.now(tz=UTC)
    return [now, 1000, 900, 1000, 900, 1000, 1000, 1.0, 60.0]


def test_control_quit(task):
    with pytest.raises(tasks.TaskQuit):
        task.quit()
        task.poll(0)


def test_control_pause(task):
    assert not task.paused
    task.pause()
    task.poll(0)
    assert task.paused
    task.resume()
    task.poll(0)
    assert not task.paused


def test_new_builds(task, builds_queue, stats_queue):
    assert not task.abi_queues
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert task.abi_queues['cp34m'] == [('foo', '0.1')]
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    builds_queue.send_msg('QUEUE', {'cp35m': [('foo', '0.1')]})
    task.poll(0)
    assert task.abi_queues['cp35m'] == [('foo', '0.1')]
    assert stats_queue.recv_msg() == ('STATBQ', {'cp35m': 1})


def test_slave_says_hello(task, slave_queue, hello_data):
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    for state in task.slaves.values():
        assert state.slave_id == 1
        assert state.timeout == timedelta(minutes=5)
        assert state.label == 'piwheels1'
        assert state.native_abi == 'cp34m'
        assert state.native_py_version == 'cp34'
        assert state.native_platform == 'linux_armv7l'
        assert state.os_name == 'Raspbian GNU/Linux'
        assert state.os_version == '9 (stretch)'
        assert state.board_revision == 'a020d3'
        assert state.board_serial == '12345678'
        assert not state.expired
        assert state.build is None
        break
    else:
        assert False, "No slaves found"


def test_slave_invalid_message(task, slave_queue):
    task.logger = mock.Mock()
    slave_queue.send(b'FOO')
    task.poll(0)
    assert not task.slaves
    assert task.logger.error.call_count == 1


def test_slave_invalid_first_message(task, slave_queue):
    task.logger = mock.Mock()
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert not task.slaves
    assert task.logger.error.call_count == 1


def test_builds_invalid_message(task, builds_queue):
    task.logger = mock.Mock()
    builds_queue.send(b'FOO')
    task.poll(0)
    assert not task.abi_queues
    assert task.logger.error.call_count == 1


def test_slave_protocol_error(task, slave_queue, master_config, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    assert task.logger.error.call_count == 0
    slave_queue.send(b'FOO')
    task.poll(0)
    assert task.logger.error.call_count == 1


def test_slave_commits_suicide(task, slave_queue, master_status_queue,
                               master_config, hello_data):
    with mock.patch('piwheels.states.datetime') as dt:
        dt.now.return_value = datetime.now(tz=UTC)
        task.logger = mock.Mock()
        slave_queue.send_msg('HELLO', hello_data)
        task.poll(0)
        assert task.logger.warning.call_count == 1
        assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
        assert master_status_queue.recv_msg() == (
            'SLAVE', [
                1, dt.now.return_value, 'HELLO', hello_data
            ]
        )
        assert master_status_queue.recv_msg() == (
            'SLAVE', [
                1, dt.now.return_value, 'ACK', [1, master_config.pypi_simple]
            ]
        )
        assert task.slaves
        slave_queue.send_msg('BYE')
        task.poll(0)
        assert task.logger.warning.call_count == 2
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt.now.return_value, 'DIE', protocols.NoData]
        )
        assert not task.slaves


def test_master_lists_nothing(task, master_status_queue):
    task.list_slaves()
    task.poll(0)
    with pytest.raises(transport.Error):
        master_status_queue.recv_msg(flags=transport.NOBLOCK)


def test_master_lists_slaves(task, slave_queue, master_config,
                             master_status_queue, hello_data):
    with mock.patch('piwheels.states.datetime') as dt:
        dt.now.return_value = datetime.now(tz=UTC)
        slave_queue.send_msg('HELLO', hello_data)
        task.poll(0)
        assert slave_queue.recv_msg() == ('ACK', [
            1, master_config.pypi_simple])
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt.now.return_value, 'HELLO', hello_data]
        )
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt.now.return_value, 'ACK', [1, master_config.pypi_simple]]
        )
        task.list_slaves()
        task.poll(0)
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt.now.return_value, 'HELLO', hello_data]
        )


def test_slave_remove_expired(task, slave_queue, master_config,
                              master_status_queue, hello_data):
    with mock.patch('piwheels.states.datetime') as dt1, \
            mock.patch('piwheels.tasks.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime.now(tz=UTC)
        slave_queue.send_msg('HELLO', hello_data)
        task.poll(0)
        assert len(task.slaves) == 1
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt1.now.return_value, 'HELLO', hello_data])
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt1.now.return_value, 'ACK', [1, master_config.pypi_simple]])
        old_now = dt1.now.return_value
        dt1.now.return_value = dt2.now.return_value = dt1.now.return_value + timedelta(hours=4)
        task.poll(0)
        assert len(task.slaves) == 0
        assert master_status_queue.recv_msg() == ('SLAVE', [1, old_now, 'DIE', None])


def test_slave_remove_expired_build(task, slave_queue, master_config,
                                    builds_queue, stats_queue,
                                    master_status_queue, hello_data):
    task.logger = mock.Mock()
    with mock.patch('piwheels.states.datetime') as dt1, \
            mock.patch('piwheels.tasks.datetime') as dt2:
        dt1.now.return_value = dt2.now.return_value = datetime.now(tz=UTC)
        slave_queue.send_msg('HELLO', hello_data)
        task.poll(0)
        assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt1.now.return_value, 'HELLO', hello_data])
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt1.now.return_value, 'ACK', [1, master_config.pypi_simple]])
        builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
        task.poll(0)
        assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
        builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')],
                                        'cp35m': [('bar', '0.1')]})
        task.poll(0)
        assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1, 'cp35m': 1})
        slave_queue.send_msg('IDLE', stats_data(dt1.now.return_value))
        task.poll(0)
        assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
        assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0, 'cp35m': 1})
        assert master_status_queue.recv_msg() == (
            'SLAVE', [
                1, dt1.now.return_value, 'STATS', stats_data(dt1.now.return_value)
            ])
        assert master_status_queue.recv_msg() == (
            'SLAVE', [1, dt1.now.return_value, 'BUILD', ['foo', '0.1']])
        old_now = dt1.now.return_value
        dt1.now.return_value = dt2.now.return_value = dt1.now.return_value + timedelta(hours=4)
        task.poll(0)
        assert len(task.slaves) == 0
        assert master_status_queue.recv_msg() == ('SLAVE', [1, old_now, 'DIE', None])


def test_slave_says_hello(task, slave_queue, hello_data):
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    for state in task.slaves.values():
        assert state.slave_id == 1
        assert state.build_timeout == timedelta(hours=3)
        assert state.busy_timeout == timedelta(minutes=5)
        assert state.label == 'piwheels1'
        assert state.native_abi == 'cp34m'
        assert state.native_py_version == 'cp34'
        assert state.native_platform == 'linux_armv7l'
        assert state.os_name == 'Raspbian GNU/Linux'
        assert state.os_version == '9 (stretch)'
        assert state.board_revision == 'a020d3'
        assert state.board_serial == '12345678'
        assert not state.expired
        assert state.build is None
        break
    else:
        assert False, "No slaves found"


def test_slave_says_idle_invalid(task, slave_queue, master_config, stats_queue,
                                 hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    for slave in task.slaves.values():
        slave.reply = ('SEND', 'foo-0.1-py3-none-any.whl')
        break
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_msg() == ('DIE', None)


def test_master_kills_nothing(task):
    task.logger = mock.Mock()
    task.kill_slave(1)
    task.poll(0)
    assert task.logger.error.call_count == 0


def test_master_says_idle_when_terminated(task, slave_queue, master_config,
                                          hello_data):
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    task.kill_slave(1)
    task.poll(0)
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('DIE', None)


def test_master_kills_correct_slave(task, slave_queue, master_config,
                                    stats_queue, hello_data):
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    task.kill_slave(2)
    task.poll(0)
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('SLEEP', False)
    assert stats_queue.recv_msg() == ('STATBQ', {})


def test_slave_idle_with_no_builds(task, slave_queue, builds_queue,
                                   master_config, stats_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('SLEEP', False)
    assert stats_queue.recv_msg() == ('STATBQ', {})


def test_slave_idle_with_build(task, slave_queue, builds_queue, master_config,
                               stats_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')],
                                    'cp35m': [('bar', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1, 'cp35m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0, 'cp35m': 1})


def test_slave_cont_with_build(task, slave_queue, builds_queue, master_config,
                               stats_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')],
                                    'cp35m': [('bar', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1, 'cp35m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0, 'cp35m': 1})
    slave_queue.send_msg('BUSY', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('CONT', None)


def test_slave_idle_after_skip(task, slave_queue, builds_queue, master_config,
                               stats_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    task.skip_slave(1)
    task.poll(0)
    slave_queue.send_msg('BUSY', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('DONE', None)


def test_slave_idle_after_delete_version(
        task, slave_queue, builds_queue, master_config, delete_queue,
        stats_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    delete_queue.send_msg('DELVER', ('foo', '0.1'))
    task.poll(0)
    assert delete_queue.recv_msg() == ('OK', None)
    slave_queue.send_msg('BUSY', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('DONE', None)


def test_slave_idle_after_delete_package(
        task, slave_queue, builds_queue, master_config, delete_queue,
        stats_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    delete_queue.send_msg('DELPKG', 'foo')
    task.poll(0)
    assert delete_queue.recv_msg() == ('OK', None)
    slave_queue.send_msg('BUSY', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('DONE', None)


def test_slave_delete_with_other_builds(
        task, slave_queue, slave2_queue, builds_queue, stats_queue,
        master_status_queue, master_config, delete_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    hello_data[4] = 'piwheels2'
    slave2_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave2_queue.recv_msg() == ('ACK', [2, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave2_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave2_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('SLEEP', False)
    delete_queue.send_msg('DELPKG', 'foo')
    task.poll(0)
    assert delete_queue.recv_msg() == ('OK', None)
    slave2_queue.send_msg('BUSY', stats_data())
    master_status_queue.drain()
    task.poll(0)
    assert slave2_queue.recv_msg() == ('DONE', None)
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('SLEEP', False)
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    # ('foo', None) should be in recent_deletes, so this'll be excluded
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})


def test_slave_idle_with_other_build(task, slave_queue, slave2_queue,
                                     builds_queue, stats_queue, master_config,
                                     hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    hello_data[4] = 'piwheels2'
    slave2_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave2_queue.recv_msg() == ('ACK', [2, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    slave2_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave2_queue.recv_msg() == ('SLEEP', False)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})


def test_slave_idle_when_paused(task, slave_queue, builds_queue, master_config,
                                stats_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    task.pause()
    task.poll(0)
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('SLEEP', True)
    task.resume()
    task.poll(0)
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})


def test_slave_says_built_invalid(task, slave_queue, master_config, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    slave_queue.send_msg('BUILT', [False, timedelta(seconds=5), '', []])
    task.poll(0)
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_msg() == ('DIE', None)


def test_slave_says_built_failed(task, db_queue, web_queue, slave_queue,
                                 builds_queue, master_config, stats_queue,
                                 hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [False, timedelta(seconds=5), '', []])
    bs = BuildState(
        1, 'foo', '0.1', 'cp34m', False, timedelta(seconds=5), '', {})
    db_queue.expect('LOGBUILD', bs.as_message())
    db_queue.send('OK', 1)
    web_queue.expect('PROJECT', bs.package)
    web_queue.send('DONE')
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.logger.info.call_count == 2
    assert slave_queue.recv_msg() == ('DONE', None)


def test_slave_says_built_failed_with_cont(
        task, db_queue, slave_queue, builds_queue, web_queue, master_config,
        stats_queue, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUSY', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('CONT', None)
    slave_queue.send_msg('BUILT', [False, timedelta(seconds=5), '', []])
    bs = BuildState(
        1, 'foo', '0.1', 'cp34m', False, timedelta(seconds=5), '', {})
    db_queue.expect('LOGBUILD', bs.as_message())
    db_queue.send('OK', 1)
    web_queue.expect('PROJECT', bs.package)
    web_queue.send('DONE')
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.logger.info.call_count == 2
    assert slave_queue.recv_msg() == ('DONE', None)


def test_slave_says_built_succeeded(task, fs_queue, slave_queue, builds_queue,
                                    web_queue, stats_queue, master_config,
                                    file_state, file_state_hacked, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [
        True, timedelta(seconds=5), 'Woohoo!', [file_state.as_message()]
    ])
    fs_queue.expect('EXPECT', [1, file_state.as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    fs_queue.check()
    assert task.logger.info.call_count == 3
    assert slave_queue.recv_msg() == ('SEND', file_state.filename)


def test_slave_throws_away_skipped_builds(
        task, slave_queue, builds_queue, stats_queue, master_config,
        hello_data, file_state):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [('foo', '0.1')]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', ['foo', '0.1'])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    task.skip_slave(1)
    task.poll(0)
    slave_queue.send_msg('BUILT', [
        True, timedelta(seconds=5), 'Woohoo!', [file_state.as_message()]
    ])
    task.poll(0)
    assert task.logger.info.call_count == 2
    assert slave_queue.recv_msg() == ('DONE', None)


def test_slave_says_sent_invalid(task, slave_queue, master_config, hello_data):
    task.logger = mock.Mock()
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    slave_queue.send_msg('SENT')
    task.poll(0)
    assert task.logger.error.call_count == 1
    assert slave_queue.recv_msg() == ('DIE', None)


def test_slave_says_sent_failed(task, fs_queue, slave_queue, builds_queue,
                                stats_queue, master_config,
                                build_state_hacked, hello_data):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [(bs.package, bs.version)]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', [bs.package, bs.version])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [
        bs.status, bs.duration, bs.output, [fs1.as_message()]
    ])
    fs_queue.expect('EXPECT', [1, fs1.as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    assert slave_queue.recv_msg() == ('SEND', fs1.filename)
    slave_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [1, bs.package])
    fs_queue.send('ERROR', '')
    task.poll(0)
    fs_queue.check()
    assert slave_queue.recv_msg() == ('SEND', fs1.filename)


def test_slave_says_sent_succeeded(task, db_queue, fs_queue, slave_queue,
                                   builds_queue, web_queue, stats_queue,
                                   master_config, build_state_hacked,
                                   hello_data):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [(bs.package, bs.version)]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', [bs.package, bs.version])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [
        bs.status, bs.duration, bs.output, [fs1.as_message()]
    ])
    fs_queue.expect('EXPECT', [1, fs1.as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    assert slave_queue.recv_msg() == ('SEND', fs1.filename)
    slave_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [1, bs.package])
    fs_queue.send('OK', None)
    db_queue.expect('LOGBUILD', bs.as_message())
    db_queue.send('OK', 1)
    web_queue.expect('BOTH', bs.package)
    web_queue.send('DONE')
    task.poll(0)
    db_queue.check()
    fs_queue.check()
    web_queue.check()
    assert slave_queue.recv_msg() == ('DONE', None)


def test_slave_says_sent_succeeded_more(task, fs_queue, slave_queue,
                                        builds_queue, web_queue, stats_queue,
                                        master_config, build_state_hacked,
                                        hello_data):
    bs = build_state_hacked
    fs1 = [f for f in bs.files.values() if not f.transferred][0]
    fs2 = [f for f in bs.files.values() if f.transferred][0]
    fs2._transferred = False
    slave_queue.send_msg('HELLO', hello_data)
    task.poll(0)
    assert slave_queue.recv_msg() == ('ACK', [1, master_config.pypi_simple])
    builds_queue.send_msg('QUEUE', {'cp34m': [(bs.package, bs.version)]})
    task.poll(0)
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 1})
    slave_queue.send_msg('IDLE', stats_data())
    task.poll(0)
    assert slave_queue.recv_msg() == ('BUILD', [bs.package, bs.version])
    assert stats_queue.recv_msg() == ('STATBQ', {'cp34m': 0})
    slave_queue.send_msg('BUILT', [
        bs.status, bs.duration, bs.output,
        [f.as_message() for f in bs.files.values()]
    ])
    fs_queue.expect('EXPECT', [1, fs2.as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    assert slave_queue.recv_msg() == ('SEND', fs2.filename)
    slave_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [1, bs.package])
    fs_queue.send('OK', None)
    fs_queue.expect('EXPECT', [1, fs1.as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    assert slave_queue.recv_msg() == ('SEND', fs1.filename)
    fs_queue.check()
