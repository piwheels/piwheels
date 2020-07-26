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
from pathlib import Path
from unittest import mock

import pytest

from piwheels import protocols, transport
from piwheels.states import TransferState
from piwheels.master.file_juggler import FileJuggler


@pytest.fixture()
def stats_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(transport.PULL, protocol=protocols.big_brother)
    queue.hwm = 1
    queue.bind(master_config.stats_queue)
    yield queue
    queue.close()


@pytest.fixture()
def file_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.DEALER, protocol=reversed(protocols.file_juggler_files))
    queue.hwm = 10
    queue.connect(master_config.file_queue)
    yield queue
    queue.close()


@pytest.fixture()
def fs_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.REQ, protocol=reversed(protocols.file_juggler_fs))
    queue.hwm = 1
    queue.connect(master_config.fs_queue)
    yield queue
    queue.close()


@pytest.fixture()
def task(request, zmq_context, master_config, stats_queue):
    save_output_path = TransferState.output_path
    TransferState.output_path = Path(master_config.output_path)
    task = FileJuggler(master_config)
    yield task
    TransferState.output_path = save_output_path
    task.close()


@pytest.fixture()
def disk_stats(request):
    with mock.patch('piwheels.info.get_disk_stats') as statfs:
        statfs.return_value = (10*1024**3, 5*1024**3)
        yield statfs.return_value


def test_init(task, stats_queue, disk_stats):
    task.once()
    assert stats_queue.recv_msg() == ('STATFS', list(disk_stats))


def test_bad_request(task, fs_queue):
    task.logger = mock.Mock()
    fs_queue.send(b'FOO')
    task.poll(0)
    assert task.logger.error.call_count == 1
    assert fs_queue.recv_msg()[0] == 'ERROR'


def test_expect_file(task, master_config, fs_queue, file_state):
    root = Path(master_config.output_path)
    task.logger = mock.Mock()
    fs_queue.send_msg('EXPECT', [1, file_state.as_message()])
    task.poll(0)
    assert fs_queue.recv_msg() == ('OK', None)
    assert task.logger.info.call_count == 1
    assert (root / 'simple').is_dir()
    assert 1 in task.pending
    assert task.pending[1].slave_id == 1
    assert task.pending[1].file_state == file_state


def test_transfer_bad_start(task, file_queue):
    task.logger = mock.Mock()
    file_queue.send_multipart([b'HELLO', b'1'])
    task.poll(0)
    assert task.logger.exception.call_count == 1
    file_queue.send_multipart([b'HELLO', b'FOO'])
    task.poll(0)
    assert task.logger.exception.call_count == 2


def test_transfer_success(task, master_config, stats_queue, fs_queue,
                          file_queue, file_state, file_content, disk_stats):
    task.logger = mock.Mock()
    root = Path(master_config.output_path)
    fs_queue.send_msg('EXPECT', [1, file_state.as_message()])
    task.poll(0)
    assert fs_queue.recv_msg() == ('OK', None)
    assert 1 in task.pending
    assert not task.active
    assert not task.complete
    assert task.logger.info.call_count == 1
    assert (root / 'simple').is_dir()
    file_queue.send_multipart([b'HELLO', b'1'])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'FETCH', b'0', b'65536']
    assert not task.pending
    assert task.active
    assert not task.complete
    file_queue.send_multipart([b'CHUNK', b'0', file_content[0:65536]])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'FETCH', b'65536', b'57920']
    file_queue.send_multipart([b'CHUNK', b'65536', file_content[65536:123456]])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'DONE']
    assert not task.pending
    assert not task.active
    assert 1 in task.complete
    assert task.logger.info.call_count == 2
    fs_queue.send_msg('VERIFY', [1, file_state.package_tag])
    task.poll(0)
    assert fs_queue.recv_msg() == ('OK', None)
    assert stats_queue.recv_msg() == ('STATFS', list(disk_stats))
    assert task.logger.info.call_count == 3
    assert not task.pending
    assert not task.active
    assert not task.complete
    assert (root / 'simple' / 'foo' / file_state.filename).exists()


def test_verify_failure(task, master_config, fs_queue, file_queue, file_state,
                        file_content):
    task.logger = mock.Mock()
    root = Path(master_config.output_path)
    fs_queue.send_msg('EXPECT', [1, file_state.as_message()])
    task.poll(0)
    assert fs_queue.recv_msg() == ('OK', None)
    assert (root / 'simple').is_dir()
    file_queue.send_multipart([b'HELLO', b'1'])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'FETCH', b'0', b'65536']
    file_queue.send_multipart([b'CHUNK', b'0', b'\x01' * 65536])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'FETCH', b'65536', b'57920']
    file_queue.send_multipart([b'CHUNK', b'65536', file_content[65536:123456]])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'DONE']
    fs_queue.send_msg('VERIFY', [1, file_state.package_tag])
    task.poll(0)
    assert fs_queue.recv_msg()[0] == 'ERROR'
    assert task.logger.warning.call_count == 1
    assert not (root / 'simple' / 'foo' / file_state.filename).exists()


def test_transfer_restart(task, fs_queue, file_queue, file_state,
                          file_content):
    task.logger = mock.Mock()
    fs_queue.send_msg('EXPECT', [1, file_state.as_message()])
    task.poll(0)
    assert fs_queue.recv_msg() == ('OK', None)
    file_queue.send_multipart([b'HELLO', b'1'])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'FETCH', b'0', b'65536']
    file_queue.send_multipart([b'CHUNK', b'0', file_content[:65536]])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'FETCH', b'65536', b'57920']
    # Pretend we've lost so many packets that we're attempting to restart; this
    # should be accepted with no error reported
    file_queue.send_multipart([b'HELLO', b'1'])
    task.poll(0)
    assert task.logger.error.call_count == 0
    assert file_queue.recv_multipart() == [b'FETCH', b'65536', b'57920']
    file_queue.send_multipart([b'CHUNK', b'65536', file_content[65536:123456]])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'DONE']
    fs_queue.send_msg('VERIFY', [1, file_state.package_tag])
    task.poll(0)
    assert fs_queue.recv_msg() == ('OK', None)


def test_transfer_error_recovery(task, fs_queue, file_queue, file_state,
                                 file_content):
    task.logger = mock.Mock()
    fs_queue.send_msg('EXPECT', [1, file_state.as_message()])
    task.poll(0)
    assert fs_queue.recv_msg() == ('OK', None)
    # Emulate a left over CHUNK packet from a prior transfer; should be
    # ignored except under debug conditions
    file_queue.send_multipart([b'CHUNK', b'65536', file_content[65536:123456]])
    task.poll(0)
    assert task.logger.debug.call_count == 1
    # Send a corrupted HELLO; should be reported as error but ignored
    file_queue.send_multipart([b'ELLO', b'1'])
    task.poll(0)
    assert task.logger.exception.call_count == 1
    # Carry on with the transfer to make sure it succeeds after the initial
    # hiccups
    file_queue.send_multipart([b'HELLO', b'1'])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'FETCH', b'0', b'65536']
    file_queue.send_multipart([b'CHUNK', b'0', file_content[:65536]])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'FETCH', b'65536', b'57920']
    file_queue.send_multipart([b'HUNK', b'65536', file_content[65536:123456]])
    task.poll(0)
    assert task.logger.exception.call_count == 2
    assert file_queue.recv_multipart() == [b'FETCH', b'65536', b'57920']
    file_queue.send_multipart([b'CHUNK', b'65536', file_content[65536:123456]])
    task.poll(0)
    assert file_queue.recv_multipart() == [b'DONE']
    fs_queue.send_msg('VERIFY', [1, file_state.package_tag])
    task.poll(0)
    assert fs_queue.recv_msg() == ('OK', None)
