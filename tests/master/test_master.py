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
from threading import Thread

import pytest

from conftest import find_message
from piwheels import __version__, protocols, transport
from piwheels.states import MasterStats
from piwheels.master import main, const


@pytest.fixture()
def mock_pypi(request):
    with mock.patch('xmlrpc.client.ServerProxy') as proxy:
        proxy().changelog_since_serial.return_value = []
        yield proxy


@pytest.fixture()
def mock_signal(request):
    with mock.patch('signal.signal') as signal:
        yield signal


@pytest.fixture()
def mock_context(request, zmq_context):
    with mock.patch('piwheels.transport.Context') as ctx_mock:
        # Pass thru calls to Context.socket, but ignore everything else (in
        # particular, destroy and term calls as we want the testing context to
        # stick around)
        ctx_mock().socket.side_effect = zmq_context.socket
        yield ctx_mock


@pytest.fixture()
def master_thread(request, mock_pypi, mock_context, mock_systemd, mock_signal,
                  tmpdir, db_url, db, with_schema):
    main_thread = None
    def _master_thread(args=None):
        nonlocal main_thread
        if args is None:
            args = []
        main_thread = Thread(daemon=True, target=main, args=([
            '--dsn', db_url,
            '--output-path', str(tmpdir.join('output')),
            '--status-queue',  'ipc://' + str(tmpdir.join('status-queue')),
            '--control-queue', 'ipc://' + str(tmpdir.join('control-queue')),
            '--slave-queue',   'ipc://' + str(tmpdir.join('slave-queue')),
            '--file-queue',    'ipc://' + str(tmpdir.join('file-queue')),
            '--import-queue',  'ipc://' + str(tmpdir.join('import-queue')),
            '--log-queue',     'ipc://' + str(tmpdir.join('log-queue')),
        ] + list(args),))
        return main_thread
    yield _master_thread
    if main_thread is not None and main_thread.is_alive():
        with mock_context().socket(
                transport.PUSH, protocol=reversed(protocols.master_control)) as control:
            control.connect('ipc://' + str(tmpdir.join('control-queue')))
            control.send_msg('QUIT')
        main_thread.join(10)
        assert not main_thread.is_alive()


@pytest.fixture()
def master_control(request, tmpdir, mock_context):
    control = mock_context().socket(
        transport.PUSH, protocol=reversed(protocols.master_control))
    control.connect('ipc://' + str(tmpdir.join('control-queue')))
    yield control
    control.close()


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--pypi-xmlrpc' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_no_root(caplog):
    with mock.patch('os.geteuid') as geteuid:
        geteuid.return_value = 0
        assert main([]) != 0
        assert find_message(caplog.records,
                            message='Master must not be run as root')


def test_quit_control(mock_systemd, master_thread, master_control):
    thread = master_thread()
    thread.start()
    assert mock_systemd._ready.wait(10)
    master_control.send_msg('QUIT')
    thread.join(10)
    assert not thread.is_alive()


def test_system_exit(mock_systemd, master_thread, caplog):
    with mock.patch('piwheels.master.PiWheelsMaster.main_loop') as main_loop:
        main_loop.side_effect = SystemExit(1)
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        thread.join(10)
        assert not thread.is_alive()
    assert find_message(caplog.records, message='shutting down on SIGTERM')


def test_system_ctrl_c(mock_systemd, master_thread, caplog):
    with mock.patch('piwheels.master.PiWheelsMaster.main_loop') as main_loop:
        main_loop.side_effect = KeyboardInterrupt()
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        thread.join(10)
        assert not thread.is_alive()
    assert find_message(caplog.records, message='shutting down on Ctrl+C')


def test_bad_control(mock_systemd, master_thread, master_control, caplog):
    thread = master_thread()
    thread.start()
    assert mock_systemd._ready.wait(10)
    master_control.send(b'FOO')
    master_control.send_msg('QUIT')
    thread.join(10)
    assert not thread.is_alive()
    assert find_message(caplog.records, message='unable to deserialize data')


def test_status_passthru(tmpdir, mock_context, mock_systemd, master_thread):
    with mock_context().socket(transport.PUSH, protocol=protocols.monitor_stats) as int_status, \
            mock_context().socket(transport.SUB, protocol=reversed(protocols.monitor_stats)) as ext_status:
        ext_status.connect('ipc://' + str(tmpdir.join('status-queue')))
        ext_status.subscribe('')
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        # Wait for the first statistics message (from BigBrother) to get the
        # SUB queue working
        msg, data = ext_status.recv_msg()
        assert msg == 'STATS'
        data = MasterStats.from_message(data)
        data = data._replace(new_last_hour=83)
        int_status.connect(const.INT_STATUS_QUEUE)
        int_status.send_msg('STATS', data.as_message())
        # Try several times to read the passed-thru message; other messages
        # (like stats from BigBrother) will be sent to ext-status too
        for i in range(3):
            msg, copy = ext_status.recv_msg()
            if msg == 'STATS':
                assert MasterStats.from_message(copy) == data
                break
        else:
            assert False, "Didn't see modified STATS passed-thru"


def test_kill_control(mock_systemd, master_thread, master_control):
    with mock.patch('piwheels.master.SlaveDriver.kill_slave') as kill_slave:
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        master_control.send_msg('KILL', 1)
        master_control.send_msg('QUIT')
        thread.join(10)
        assert not thread.is_alive()
        assert kill_slave.call_args == mock.call(1)


def test_kill_all_control(mock_systemd, master_thread, master_control, caplog):
    with mock.patch('piwheels.master.SlaveDriver.kill_slave') as kill_slave:
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        master_control.send_msg('KILL', None)
        master_control.send_msg('QUIT')
        thread.join(10)
        assert not thread.is_alive()
        assert kill_slave.call_args == mock.call(None)
        assert find_message(caplog.records, message='killing all slaves')


def test_skip_control(mock_systemd, master_thread, master_control):
    with mock.patch('piwheels.master.SlaveDriver.skip_slave') as skip_slave:
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        master_control.send_msg('SKIP', 1)
        master_control.send_msg('QUIT')
        thread.join(10)
        assert not thread.is_alive()
        assert skip_slave.call_args == mock.call(1)


def test_skip_all_control(mock_systemd, master_thread, master_control, caplog):
    with mock.patch('piwheels.master.SlaveDriver.skip_slave') as skip_slave:
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        master_control.send_msg('SKIP', None)
        master_control.send_msg('QUIT')
        thread.join(10)
        assert not thread.is_alive()
        assert skip_slave.call_args == mock.call(None)
        assert find_message(caplog.records, message='skipping all slaves')


def test_sleep_control(mock_systemd, master_thread, master_control):
    with mock.patch('piwheels.master.SlaveDriver.sleep_slave') as sleep_slave, \
            mock.patch('piwheels.master.SlaveDriver.wake_slave') as wake_slave:
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        master_control.send_msg('SLEEP', 1)
        master_control.send_msg('WAKE', 1)
        master_control.send_msg('QUIT')
        thread.join(10)
        assert not thread.is_alive()
        assert sleep_slave.call_args == mock.call(1)
        assert wake_slave.call_args == mock.call(1)


def test_sleep_all_control(mock_systemd, master_thread, master_control, caplog):
    thread = master_thread()
    thread.start()
    assert mock_systemd._ready.wait(10)
    master_control.send_msg('SLEEP', None)
    master_control.send_msg('WAKE', None)
    master_control.send_msg('QUIT')
    thread.join(10)
    assert not thread.is_alive()
    assert find_message(caplog.records, message='sleeping all slaves and master')
    assert find_message(caplog.records, message='waking all slaves and master')


def test_new_monitor(mock_systemd, master_thread, master_control, caplog):
    with mock.patch('piwheels.master.SlaveDriver.list_slaves') as list_slaves:
        thread = master_thread()
        thread.start()
        assert mock_systemd._ready.wait(10)
        master_control.send_msg('HELLO')
        master_control.send_msg('QUIT')
        thread.join(10)
        assert not thread.is_alive()
        assert find_message(caplog.records,
                            message='sending status to new monitor')
        assert list_slaves.call_args == mock.call()


def test_debug(mock_systemd, master_thread, master_control, caplog):
    thread = master_thread(args=['--debug', 'master.the_scribe',
                                 '--debug', 'master.the_architect'])
    thread.start()
    assert mock_systemd._ready.wait(10)
    master_control.send_msg('QUIT')
    thread.join(10)
    assert not thread.is_alive()
    assert find_message(caplog.records, name='master.the_scribe',
                        levelname='DEBUG', message='<< QUIT None')
    assert find_message(caplog.records, name='master.the_architect',
                        levelname='DEBUG', message='<< QUIT None')
