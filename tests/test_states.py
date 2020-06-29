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


import warnings
from unittest import mock
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from piwheels import const, protocols, transport
from piwheels.master.db import Database
from piwheels.states import (
    SlaveState,
    BuildState,
    FileState,
    TransferState,
    DownloadState,
    mkdir_override_symlink,
)


UTC = timezone.utc


@pytest.fixture()
def slave_queue(request, zmq_context, master_status_queue):
    SlaveState.status_queue = zmq_context.socket(
        transport.PUSH, protocol=protocols.monitor_stats)
    SlaveState.status_queue.connect(const.INT_STATUS_QUEUE)
    yield SlaveState.status_queue
    SlaveState.status_queue.close()
    SlaveState.status_queue = None


@pytest.fixture()
def slave_state(slave_queue):
    return SlaveState(
        '10.0.0.2', timedelta(hours=3), timedelta(minutes=2),
        '34', 'cp34m', 'linux_armv7l', 'piwheels2',
        'Raspbian GNU/Linux', '9 (stretch)', 'a020d3', '12345678')


def test_file_state_init(file_state):
    assert len(file_state) == 10
    assert file_state[0] == file_state.filename == 'foo-0.1-cp34-cp34m-linux_armv7l.whl'
    assert file_state[1] == file_state.filesize == 123456
    assert file_state[2] == file_state.filehash == 'c3bef91a6ceda582a97839ab65fc7efb4e79bc4eba53e41272574828ca59325a'
    assert file_state[3] == file_state.package_tag == 'foo'
    assert file_state[4] == file_state.package_version_tag == '0.1'
    assert file_state[5] == file_state.py_version_tag == 'cp34'
    assert file_state[6] == file_state.abi_tag == 'cp34m'
    assert file_state[7] == file_state.platform_tag == 'linux_armv7l'
    assert file_state[8] == file_state.dependencies == {'apt': ['libc6']}
    assert file_state[9] == file_state.transferred == False


def test_file_state_transferred(file_state):
    assert not file_state.transferred
    file_state.verified()
    assert file_state.transferred


def test_build_state_init(build_state, file_state):
    assert len(build_state) == 9
    assert build_state[0] == build_state.slave_id == 1
    assert build_state[1] == build_state.package == 'foo'
    assert build_state[2] == build_state.version == '0.1'
    assert build_state[3] == build_state.abi_tag == 'cp34m'
    assert build_state[4] == build_state.status == True
    assert build_state[5] == build_state.duration == timedelta(seconds=300)
    assert build_state[6] == build_state.output == 'Built successfully'
    assert build_state[7] == build_state.files == {
        'foo-0.1-cp34-cp34m-linux_armv7l.whl': file_state
    }
    assert build_state[8] == build_state.build_id == None


def test_build_state_override_abi(build_state, file_state):
    build_state.abi_tag = 'cp35m'
    assert build_state.abi_tag == 'cp35m'
    build_state[3] = 'cp34m'
    assert build_state.abi_tag == 'cp34m'
    with pytest.raises(AttributeError):
        build_state[0] = 'bar'


def test_build_state_transfers(build_state, file_state):
    assert not build_state.transfers_done
    assert build_state.next_file == file_state.filename
    build_state.files[build_state.next_file].verified()
    assert build_state.transfers_done
    assert build_state.next_file is None


def test_build_state_logged(build_state, file_state):
    assert build_state.build_id is None
    build_state.logged(3)
    assert build_state.build_id == 3


def test_slave_state_init():
    now = datetime.now(tz=UTC)
    with mock.patch('piwheels.states.datetime') as dt:
        dt.now.return_value = now
        slave_state = SlaveState(
            '10.0.0.2', timedelta(hours=3), timedelta(minutes=2),
            '34', 'cp34m', 'linux_armv7l', 'piwheels2',
            'Raspbian GNU/Linux', '9 (stretch)', 'a020d3', '12345678')
        assert slave_state.slave_id == 1
        assert slave_state.address == '10.0.0.2'
        assert slave_state.label == 'piwheels2'
        assert slave_state.build_timeout == timedelta(hours=3)
        assert slave_state.busy_timeout == timedelta(minutes=2)
        assert slave_state.native_py_version == '34'
        assert slave_state.native_abi == 'cp34m'
        assert slave_state.native_platform == 'linux_armv7l'
        assert slave_state.os_name == 'Raspbian GNU/Linux'
        assert slave_state.os_version == '9 (stretch)'
        assert slave_state.board_revision == 'a020d3'
        assert slave_state.board_serial == '12345678'
        assert slave_state.first_seen == now
        assert slave_state.last_seen == now
        assert slave_state.request is None
        assert slave_state.reply is None
        assert slave_state.build is None
        assert list(slave_state.stats) == []
        assert slave_state.clock_skew is None
        assert not slave_state.killed
        assert not slave_state.paused
        assert not slave_state.skipped


def test_slave_state_kill(slave_state):
    assert not slave_state.killed
    slave_state.kill()
    assert slave_state.killed


def test_slave_state_skip(slave_state):
    assert not slave_state.skipped
    slave_state.skip()
    assert slave_state.skipped


def test_slave_state_paused(slave_state):
    assert not slave_state.paused
    slave_state.sleep()
    assert slave_state.paused


def test_slave_state_resumed(slave_state):
    slave_state.sleep()
    assert slave_state.paused
    slave_state.wake()
    assert not slave_state.paused


def test_slave_state_expired(slave_state):
    slave_state._first_seen = datetime.now(tz=UTC) - timedelta(hours=5)
    assert not slave_state.expired
    slave_state._last_seen = datetime.now(tz=UTC) - timedelta(minutes=5)
    assert slave_state.expired


def test_slave_state_hello(master_status_queue, slave_state):
    slave_state.reply = ('ACK', [slave_state.slave_id, const.PYPI_XMLRPC])
    assert master_status_queue.recv_msg() == ('SLAVE', [
        slave_state.slave_id, mock.ANY, 'HELLO', [
            timedelta(hours=3), timedelta(minutes=2),
            slave_state.native_py_version, slave_state.native_abi,
            slave_state.native_platform, slave_state.label,
            slave_state.os_name, slave_state.os_version,
            slave_state.board_revision, slave_state.board_serial,
        ]
    ])
    assert master_status_queue.recv_msg() == ('SLAVE', [
        slave_state.slave_id, mock.ANY, 'ACK',
        [slave_state.slave_id, 'https://pypi.org/pypi']
    ])


def test_slave_recv_request(build_state, slave_state, file_state):
    with mock.patch('piwheels.states.datetime') as dt:
        now = datetime.now(tz=UTC)
        dt.now.return_value = now
        slave_state.request = (
            'IDLE', [now, 1000, 900, 1000, 900, 1000, 1000, 1.0, 60.0])
        assert slave_state.request == (
            'IDLE', [now, 1000, 900, 1000, 900, 1000, 1000, 1.0, 60.0])
        assert slave_state.last_seen == now
        assert slave_state.build is None
        now = datetime.now(tz=UTC)
        dt.now.return_value = now
        slave_state._reply = ('BUILD', ['foo', '0.1'])
        slave_state.request = ('BUILT', [
            build_state.status, build_state.duration, build_state.output,
            [file_state.as_message()]
        ])
        assert slave_state.last_seen == now
        build_state._slave_id = slave_state.slave_id
        assert slave_state.build == build_state


def test_slave_recv_reply(build_state, slave_state, file_state, slave_queue):
    with mock.patch('piwheels.states.datetime') as dt:
        now = datetime.now(tz=UTC)
        dt.now.return_value = now
        slave_state._reply = ('BUILD', ['foo', '0.1'])
        slave_state.request = ('BUILT', [
            build_state.status, build_state.duration, build_state.output,
            [file_state.as_message()]
        ])
        build_state._slave_id = slave_state.slave_id
        assert slave_state.build == build_state
        slave_state.reply = ('DONE', None)
        assert slave_state.build is None


def test_slave_recv_bad_built(build_state, slave_state, file_state, slave_queue):
    with mock.patch('piwheels.states.datetime') as dt:
        now = datetime.now(tz=UTC)
        dt.now.return_value = now
        slave_state._reply = ('BUILD', ['foo', '0.1'])
        slave_state.request = ('BUILT', None)
        assert slave_state.build is None
        slave_state.reply = ('DONE', None)
        assert slave_state.build is None


def test_slave_state_recv_hello(master_status_queue, slave_state):
    with mock.patch('piwheels.states.datetime') as dt:
        now = datetime.now(tz=UTC)
        dt.now.return_value = now
        slave_state._reply = (
            'IDLE', [1000, 900, 1000, 900, 1000, 1000, 1.0, 60.0])
        slave_state._last_seen = now
        slave_state.hello()
        assert master_status_queue.recv_msg() == ('SLAVE', [
            slave_state.slave_id, mock.ANY, 'HELLO', [
                timedelta(hours=3), timedelta(minutes=2),
                '34', 'cp34m', 'linux_armv7l', 'piwheels2',
                'Raspbian GNU/Linux', '9 (stretch)', 'a020d3', '12345678'
            ]
        ])
        assert master_status_queue.recv_msg() == ('SLAVE', [
            slave_state.slave_id, now, 'IDLE',
            [1000, 900, 1000, 900, 1000, 1000, 1.0, 60.0]
        ])


def test_transfer_state_init(tmpdir, file_state):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    trans_state = TransferState(1, file_state)
    assert trans_state.slave_id == 1
    assert trans_state.file_state == file_state
    assert not trans_state.done


def test_transfer_state_fetch1(tmpdir, file_state, file_content):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    trans_state = TransferState(1, file_state)
    assert trans_state.fetch() == range(TransferState.chunk_size)
    trans_state.chunk(0, file_content[:TransferState.chunk_size])
    assert trans_state.fetch() == range(TransferState.chunk_size, 123456)
    trans_state.chunk(
        TransferState.chunk_size, file_content[TransferState.chunk_size:])
    assert trans_state.fetch() is None
    assert trans_state.done
    trans_state.reset_credit()
    assert trans_state.fetch() is None


def test_transfer_state_fetch2(tmpdir, file_state, file_content):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    trans_state = TransferState(1, file_state)
    trans_state._credit = 10  # hack the credit
    assert trans_state.fetch() == range(TransferState.chunk_size)
    assert trans_state.fetch() == range(TransferState.chunk_size, 123456)
    assert trans_state.fetch() == range(TransferState.chunk_size)
    trans_state.chunk(0, file_content[:TransferState.chunk_size])
    assert trans_state.fetch() == range(TransferState.chunk_size, 123456)
    assert trans_state.fetch() == range(TransferState.chunk_size, 123456)
    trans_state.chunk(TransferState.chunk_size,
                      file_content[TransferState.chunk_size:])
    assert trans_state.fetch() is None
    assert trans_state.done


def test_transfer_verify(tmpdir, file_state, file_content):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    trans_state = TransferState(1, file_state)
    r = trans_state.fetch()
    trans_state.chunk(r.start, file_content[r.start:r.stop])
    r = trans_state.fetch()
    trans_state.chunk(r.start, file_content[r.start:r.stop])
    assert trans_state.done
    trans_state.verify()


def test_transfer_verify_fail_size(tmpdir, file_state, file_content):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    trans_state = TransferState(1, file_state)
    r = trans_state.fetch()
    trans_state.chunk(r.start, file_content[r.start:r.stop])
    r = trans_state.fetch()
    trans_state.chunk(r.start, file_content[r.start:r.stop])
    assert trans_state.done
    trans_state._file.write(b'\x00' * 4)
    with pytest.raises(IOError):
        trans_state.verify()


def test_transfer_verify_fail_hash(tmpdir, file_state, file_content):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    trans_state = TransferState(1, file_state)
    r = trans_state.fetch()
    trans_state.chunk(r.start, file_content[r.start:r.stop])
    r = trans_state.fetch()
    trans_state.chunk(r.start, file_content[r.start:r.stop])
    assert trans_state.done
    trans_state._file.seek(0)
    trans_state._file.write(b'\xff\xff')
    with pytest.raises(IOError):
        trans_state.verify()


def test_transfer_rollback(tmpdir, file_state, file_content):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    final_path = TransferState.output_path / 'simple' / 'foo' / file_state.filename
    trans_state = TransferState(1, file_state)
    temp_path = TransferState.output_path / trans_state._file.name
    trans_state._file.seek(0)
    trans_state._file.write(file_content)
    trans_state.rollback()
    assert not final_path.exists()
    assert not temp_path.exists()


def test_transfer_commit(tmpdir, file_state, file_content):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    trans_state = TransferState(1, file_state)
    trans_state._file.seek(0)
    trans_state._file.write(file_content)
    trans_state.commit('foo')
    assert not (TransferState.output_path / 'simple' / trans_state._file.name).exists()
    final_path = TransferState.output_path / 'simple' / 'foo' / file_state.filename
    assert final_path.exists()


def test_transfer_commit_override_symlink(tmpdir, file_state, file_content):
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    final_path = TransferState.output_path / 'simple' / 'foo' / file_state.filename
    final_path.parent.with_name('bar').mkdir()
    final_path.parent.symlink_to('bar', True)
    trans_state = TransferState(1, file_state)
    trans_state._file.seek(0)
    trans_state._file.write(file_content)
    trans_state.commit('foo')
    assert not (TransferState.output_path / 'simple' / trans_state._file.name).exists()
    assert not final_path.parent.is_symlink()
    assert final_path.parent.is_dir()
    assert final_path.exists()


def test_transfer_commit_armv6_hack(tmpdir, file_state, file_content):
    file_state._filename = 'foo-0.1-cp34-cp34m-linux_armv7l.whl'
    file_state._py_version_tag = 'cp34'
    file_state._abi_tag = 'cp34m'
    file_state._platform_tag = 'linux_armv7l'
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    final_path = TransferState.output_path / 'simple' / 'foo' / file_state.filename
    link_path = final_path.with_name('foo-0.1-cp34-cp34m-linux_armv6l.whl')
    trans_state = TransferState(1, file_state)
    trans_state._file.seek(0)
    trans_state._file.write(file_content)
    trans_state.commit('foo')
    assert not (TransferState.output_path / 'simple' / trans_state._file.name).exists()
    assert final_path.exists()
    assert link_path.is_symlink()
    assert link_path.resolve() == final_path


def test_transfer_commit_armv6_exists(tmpdir, file_state, file_content):
    file_state._filename = 'foo-0.1-cp34-cp34m-linux_armv7l.whl'
    file_state._py_version_tag = 'cp34'
    file_state._abi_tag = 'cp34m'
    file_state._platform_tag = 'linux_armv7l'
    tmpdir.mkdir('simple')
    TransferState.output_path = Path(str(tmpdir))
    final_path = TransferState.output_path / 'simple' / 'foo' / file_state.filename
    link_path = final_path.with_name('foo-0.1-cp34-cp34m-linux_armv6l.whl')
    link_path.parent.mkdir()
    link_path.touch()
    trans_state = TransferState(1, file_state)
    trans_state._file.seek(0)
    trans_state._file.write(file_content)
    trans_state.commit('foo')
    assert not (TransferState.output_path / 'simple' / trans_state._file.name).exists()
    assert final_path.exists()
    assert not link_path.is_symlink()


def test_override_symlink_fallback():
    pkg_dir = mock.Mock()
    pkg_dir.mkdir.side_effect = [FileExistsError, None]
    pkg_dir.is_symlink.return_value = True
    pkg_dir.unlink.side_effect = IsADirectoryError
    mkdir_override_symlink(pkg_dir)
