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

import pytest

from piwheels import protocols, transport
from piwheels.master.mr_chase import MrChase
from piwheels.master.slave_driver import build_armv6l_hack


@pytest.fixture()
def import_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.REQ, protocol=reversed(protocols.mr_chase))
    queue.hwm = 1
    queue.connect(master_config.import_queue)
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
def task(request, db_queue, fs_queue, web_queue, stats_queue,
         master_status_queue, master_config):
    task = MrChase(master_config)
    yield task
    task.close()


def test_import_bad_message(task, import_queue):
    task.logger = mock.Mock()
    import_queue.send(b'FOO')
    task.poll(0)
    assert task.logger.error.call_count == 1
    assert len(task.states) == 0


def test_import_protocol_error(task, import_queue):
    task.logger = mock.Mock()
    import_queue.send_msg('SENT')
    task.poll(0)
    assert task.logger.error.call_count == 1
    assert len(task.states) == 0


def test_normal_import(db_queue, fs_queue, web_queue, task, import_queue,
                       build_state, build_state_hacked):
    bs, bsh = build_state, build_state_hacked  # for brevity!
    bs._slave_id = bsh._slave_id = 0

    import_queue.send_msg('IMPORT', bs.as_message())
    db_queue.expect('GETABIS')
    db_queue.send('OK', {'cp34m', 'cp35m'})
    db_queue.expect('VEREXISTS', [bsh.package, bsh.version])
    db_queue.send('OK', True)
    db_queue.expect('LOGBUILD', bsh.as_message())
    db_queue.send('OK', 1234)
    fs_queue.expect('EXPECT', [0, bsh.files[bsh.next_file].as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    bsh.logged(1234)
    assert import_queue.recv_msg() == ('SEND', bsh.next_file)
    assert len(task.states) == 1
    for task_state in task.states.values():
        assert task_state == bsh

    import_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [0, bsh.package])
    fs_queue.send('OK', None)
    web_queue.expect('BOTH', bsh.package)
    web_queue.send('DONE')
    task.poll(0)
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0
    db_queue.check()
    fs_queue.check()
    web_queue.check()


def test_import_dual_files(db_queue, fs_queue, web_queue, task, import_queue,
                           build_state_hacked):
    bsh = build_state_hacked
    bsh._slave_id = 0
    for f in bsh.files.values():
        # Make the Armv6 file a "real" transfer
        f._transferred = False

    import_queue.send_msg('IMPORT', bsh.as_message())
    db_queue.expect('GETABIS')
    db_queue.send('OK', {'cp34m', 'cp35m'})
    db_queue.expect('VEREXISTS', [bsh.package, bsh.version])
    db_queue.send('OK', True)
    db_queue.expect('LOGBUILD', bsh.as_message())
    db_queue.send('OK', 1234)
    # XXX Sometimes we'll have a different order to the re-constructed file list on the server side
    fs_queue.expect('EXPECT', [0, bsh.files[bsh.next_file].as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    bsh.logged(1234)
    msg, filename = import_queue.recv_msg()
    assert msg == 'SEND'
    assert filename in bsh.files

    import_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [0, bsh.package])
    fs_queue.send('OK', None)
    bsh.files[filename].verified()
    fs_queue.expect('EXPECT', [0, bsh.files[bsh.next_file].as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    msg, filename = import_queue.recv_msg()
    assert msg == 'SEND'
    assert filename in bsh.files

    import_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [0, bsh.package])
    fs_queue.send('OK', None)
    web_queue.expect('BOTH', bsh.package)
    web_queue.send('DONE')
    task.poll(0)
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0
    db_queue.check()
    fs_queue.check()
    web_queue.check()


def test_import_resend_file(db_queue, web_queue, fs_queue, task, import_queue,
                            build_state, build_state_hacked):
    bs, bsh = build_state, build_state_hacked
    bs._slave_id = bsh._slave_id = 0

    import_queue.send_msg('IMPORT', bs.as_message())
    db_queue.expect('GETABIS')
    db_queue.send('OK', {'cp34m', 'cp35m'})
    db_queue.expect('VEREXISTS', [bsh.package, bsh.version])
    db_queue.send('OK', True)
    db_queue.expect('LOGBUILD', bsh.as_message())
    db_queue.send('OK', 1234)
    fs_queue.expect('EXPECT', [0, bsh.files[bsh.next_file].as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    bsh.logged(1234)
    assert import_queue.recv_msg() == ('SEND', bsh.next_file)

    import_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [0, bsh.package])
    fs_queue.send('ERROR', 'hash failed')
    task.poll(0)
    assert import_queue.recv_msg() == ('SEND', bsh.next_file)

    import_queue.send_msg('SENT')
    fs_queue.expect('VERIFY', [0, bsh.package])
    fs_queue.send('OK', None)
    web_queue.expect('BOTH', bsh.package)
    web_queue.send('DONE')
    task.poll(0)
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0
    db_queue.check()
    fs_queue.check()
    web_queue.check()


def test_import_default_abi(db_queue, fs_queue, task, import_queue,
                            build_state, build_state_hacked):
    bs, bsh = build_state, build_state_hacked
    bs._slave_id = bsh._slave_id = 0

    import_queue.send_msg('IMPORT', bs.as_message())
    db_queue.expect('GETABIS')
    db_queue.send('OK', {'cp34m', 'cp35m'})
    bsh._abi_tag = 'cp34m'
    db_queue.expect('VEREXISTS', [bsh.package, bsh.version])
    db_queue.send('OK', True)
    db_queue.expect('LOGBUILD', bsh.as_message())
    db_queue.send('OK', 1234)
    fs_queue.expect('EXPECT', [0, bsh.files[bsh.next_file].as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    assert import_queue.recv_msg() == ('SEND', bsh.next_file)
    assert len(task.states) == 1
    fs_queue.check()
    bsh.logged(1234)
    for task_state in task.states.values():
        assert task_state == bsh


def test_import_bad_abi(db_queue, task, import_queue, build_state):
    task.logger = mock.Mock()
    bs = build_state
    bs._slave_id = 0
    bs._abi_tag = 'cp36m'

    import_queue.send_msg('IMPORT', bs.as_message())
    db_queue.expect('GETABIS')
    db_queue.send('OK', {'cp34m', 'cp35m'})
    task.poll(0)
    assert import_queue.recv_msg() == ('ERROR', 'invalid ABI: cp36m')
    assert task.logger.error.call_count == 1
    assert len(task.states) == 0


def test_import_failed_build(task, import_queue, build_state):
    task.logger = mock.Mock()
    bs = build_state
    bs._status = False
    import_queue.send_msg('IMPORT', bs.as_message())
    task.poll(0)
    assert import_queue.recv_msg() == (
        'ERROR', 'importing a failed build is not supported')
    assert task.logger.error.call_count == 1
    assert len(task.states) == 0


def test_import_empty_build(task, import_queue, build_state):
    task.logger = mock.Mock()
    bs = build_state
    bs._files = {}
    import_queue.send_msg('IMPORT', bs.as_message())
    task.poll(0)
    assert import_queue.recv_msg() == ('ERROR', 'no files listed for import')
    assert task.logger.error.call_count == 1
    assert len(task.states) == 0


def test_import_unknown_pkg(db_queue, task, import_queue, build_state):
    task.logger = mock.Mock()
    build_state._slave_id = 0
    bs = build_state

    import_queue.send_msg('IMPORT', bs.as_message())
    db_queue.expect('GETABIS')
    db_queue.send('OK', {'cp34m', 'cp35m'})
    db_queue.expect('VEREXISTS', [bs.package, bs.version])
    db_queue.send('OK', False)
    task.poll(0)
    assert import_queue.recv_msg() == (
        'ERROR', 'unknown package version %s-%s' % (bs.package, bs.version))
    assert task.logger.error.call_count == 1
    assert len(task.states) == 0


def test_import_failed_log(db_queue, task, import_queue, build_state,
                           build_state_hacked):
    task.logger = mock.Mock()
    bs, bsh = build_state, build_state_hacked
    bs._slave_id = 0

    import_queue.send_msg('IMPORT', bs.as_message())
    db_queue.expect('GETABIS')
    db_queue.send('OK', {'cp34m', 'cp35m'})
    db_queue.expect('VEREXISTS', [bsh.package, bsh.version])
    db_queue.send('OK', True)
    db_queue.expect('LOGBUILD', bsh.as_message())
    db_queue.send('ERROR', 'foo')
    task.poll(0)
    assert import_queue.recv_msg() == ('ERROR', 'foo')
    assert task.logger.error.call_count == 1
    assert len(task.states) == 0


def test_import_transfer_goes_wrong(db_queue, fs_queue, task, import_queue,
                                    build_state, build_state_hacked):
    task.logger = mock.Mock()
    bs, bsh = build_state, build_state_hacked
    bs._slave_id = bsh._slave_id = 0

    import_queue.send_msg('IMPORT', bs.as_message())
    db_queue.expect('GETABIS')
    db_queue.send('OK', {'cp34m', 'cp35m'})
    db_queue.expect('VEREXISTS', [bsh.package, bsh.version])
    db_queue.send('OK', True)
    db_queue.expect('LOGBUILD', bsh.as_message())
    db_queue.send('OK', 1234)
    fs_queue.expect('EXPECT', [0, bsh.files[bsh.next_file].as_message()])
    fs_queue.send('OK', None)
    task.poll(0)
    assert import_queue.recv_msg() == ('SEND', bsh.next_file)
    assert len(task.states) == 1
    fs_queue.check()
    bsh.logged(1234)
    import_queue.send(b'FOO')
    task.poll(0)
    assert task.logger.error.call_count == 1


def test_normal_remove(db_queue, web_queue, task, import_queue,
                       build_state_hacked):
    bsh = build_state_hacked
    import_queue.send_msg('REMOVE', [bsh.package, bsh.version, ''])
    db_queue.expect('VEREXISTS', [bsh.package, bsh.version])
    db_queue.send('OK', True)
    web_queue.expect('DELVER', [bsh.package, bsh.version])
    web_queue.send('DONE')
    db_queue.expect('DELVER', [bsh.package, bsh.version])
    db_queue.send('OK', None)
    task.poll(0)
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0
    db_queue.check()
    web_queue.check()


def test_remove_with_skip(db_queue, web_queue, task, import_queue,
                          build_state_hacked):
    bsh = build_state_hacked
    import_queue.send_msg('REMOVE', [bsh.package, bsh.version, 'broken version'])
    db_queue.expect('VEREXISTS', [bsh.package, bsh.version])
    db_queue.send('OK', True)
    db_queue.expect('SKIPVER', [bsh.package, bsh.version, 'broken version'])
    db_queue.send('OK', None)
    web_queue.expect('DELVER', [bsh.package, bsh.version])
    web_queue.send('DONE')
    db_queue.expect('DELBUILD', [bsh.package, bsh.version])
    db_queue.send('OK', None)
    task.poll(0)
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0
    db_queue.check()
    web_queue.check()


def test_remove_unknown_pkg(db_queue, task, import_queue, build_state):
    task.logger = mock.Mock()
    build_state._slave_id = 0
    bs = build_state

    import_queue.send_msg('REMOVE', [bs.package, bs.version, ''])
    db_queue.expect('VEREXISTS', [bs.package, bs.version])
    db_queue.send('OK', False)
    task.poll(0)
    assert import_queue.recv_msg() == (
        'ERROR', 'unknown package version %s-%s' % (bs.package, bs.version))
    assert task.logger.error.call_count == 1
    assert len(task.states) == 0


def test_rebuild_home(task, import_queue, stats_queue):
    import_queue.send_msg('REBUILD', ['HOME'])
    task.poll(0)
    assert stats_queue.recv_msg() == ('HOME', None)
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0


def test_rebuild_search(task, import_queue, stats_queue):
    import_queue.send_msg('REBUILD', ['SEARCH'])
    task.poll(0)
    assert stats_queue.recv_msg() == ('HOME', None)
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0


def test_rebuild_package_project(db_queue, web_queue, task, import_queue,
                                 build_state):
    import_queue.send_msg('REBUILD', ['PROJECT', build_state.package])
    db_queue.expect('PKGEXISTS', build_state.package)
    db_queue.send('OK', True)
    web_queue.expect('PROJECT', build_state.package)
    web_queue.send('DONE')
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0


def test_rebuild_package_index(db_queue, web_queue, task, import_queue,
                                 build_state):
    import_queue.send_msg('REBUILD', ['BOTH', build_state.package])
    db_queue.expect('PKGEXISTS', build_state.package)
    db_queue.send('OK', True)
    web_queue.expect('BOTH', build_state.package)
    web_queue.send('DONE')
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0


def test_rebuild_all_indexes(db_queue, web_queue, task, import_queue):
    import_queue.send_msg('REBUILD', ['BOTH', None])
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', ['foo', 'bar'])  # cheat, this returns a set normally
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert import_queue.recv_msg() == ('DONE', None)
    assert len(task.states) == 0


def test_rebuild_unknown_package(db_queue, task, import_queue):
    import_queue.send_msg('REBUILD', ['BOTH', 'foo'])
    db_queue.expect('PKGEXISTS', 'foo')
    db_queue.send('OK', False)
    task.poll(0)
    assert import_queue.recv_msg() == ('ERROR', 'unknown package foo')
    assert len(task.states) == 0
