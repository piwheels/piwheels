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
from subprocess import DEVNULL
from itertools import chain, cycle
from datetime import datetime, timedelta, timezone

import pytest

from conftest import find_message
from piwheels import __version__, protocols, transport
from piwheels.states import BuildState
from piwheels.slave import PiWheelsSlave, MasterTimeout


UTC = timezone.utc


@pytest.fixture()
def mock_slave_driver(request, zmq_context, tmpdir):
    queue = zmq_context.socket(
        transport.ROUTER, protocol=protocols.slave_driver)
    queue.hwm = 1
    queue.bind('ipc://' + str(tmpdir.join('slave-driver-queue')))
    yield queue
    queue.close()


@pytest.fixture()
def mock_file_juggler(request, zmq_context, tmpdir):
    queue = zmq_context.socket(
        transport.DEALER, protocol=protocols.file_juggler)
    queue.hwm = 1
    queue.bind('ipc://' + str(tmpdir.join('file-juggler-queue')))
    yield queue
    queue.close()


@pytest.fixture()
def mock_signal(request):
    with mock.patch('signal.signal') as signal:
        yield signal


@pytest.fixture()
def slave_thread(request, mock_context, mock_systemd, mock_signal, tmpdir):
    main = PiWheelsSlave()
    slave_thread = Thread(daemon=True, target=main, args=([],))
    yield slave_thread


def test_help(capsys):
    main = PiWheelsSlave()
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--master' in out


def test_version(capsys):
    main = PiWheelsSlave()
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_no_root(caplog):
    main = PiWheelsSlave()
    with mock.patch('os.geteuid') as geteuid:
        geteuid.return_value = 0
        assert main([]) != 0
    assert find_message(caplog.records, message='Slave must not be run as root')


def test_bad_clock(caplog):
    main = PiWheelsSlave()
    with mock.patch('piwheels.slave.datetime') as dt:
        dt.side_effect = datetime
        dt.now.return_value = datetime(2000, 1, 1, tzinfo=timezone.utc)
        assert main([]) != 0
    assert find_message(caplog.records, message='System clock is far in the past')


def test_system_exit(mock_systemd, slave_thread, mock_slave_driver):
    with mock.patch('piwheels.slave.PiWheelsSlave.main_loop') as main_loop:
        main_loop.side_effect = SystemExit(1)
        slave_thread.start()
        assert mock_systemd._ready.wait(10)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BYE'
        slave_thread.join(10)
        assert not slave_thread.is_alive()


def test_bye_exit(mock_systemd, slave_thread, mock_slave_driver):
    slave_thread.start()
    assert mock_systemd._ready.wait(10)
    addr, msg, data = mock_slave_driver.recv_addr_msg()
    assert msg == 'HELLO'
    mock_slave_driver.send_addr_msg(addr, 'DIE')
    addr, msg, data = mock_slave_driver.recv_addr_msg()
    assert msg == 'BYE'
    slave_thread.join(10)
    assert not slave_thread.is_alive()


def test_connection_timeout(mock_systemd, slave_thread, mock_slave_driver, caplog):
    with mock.patch('piwheels.slave.datetime') as time_mock:
        start = datetime.now(tz=UTC)
        time_mock.side_effect = datetime
        time_mock.now.side_effect = chain([
            start,
            start,
            start + timedelta(seconds=400),
            start + timedelta(seconds=401),
        ], cycle([
            start + timedelta(seconds=403),
        ]))
        slave_thread.start()
        assert mock_systemd._ready.wait(10)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        # Allow timeout (time_mock takes care of faking this)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        mock_slave_driver.send_addr_msg(addr, 'DIE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BYE'
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, message='Timed out waiting for master')


def test_bad_message_exit(mock_systemd, slave_thread, mock_slave_driver):
    slave_thread.start()
    assert mock_systemd._ready.wait(10)
    addr, msg, data = mock_slave_driver.recv_addr_msg()
    assert msg == 'HELLO'
    mock_slave_driver.send_multipart([addr, b'', b'FOO'])
    addr, msg, data = mock_slave_driver.recv_addr_msg()
    assert msg == 'BYE'
    slave_thread.join(10)
    assert not slave_thread.is_alive()


def test_hello(mock_systemd, slave_thread, mock_slave_driver):
    slave_thread.start()
    assert mock_systemd._ready.wait(10)
    addr, msg, data = mock_slave_driver.recv_addr_msg()
    assert msg == 'HELLO'
    mock_slave_driver.send_addr_msg(addr, 'ACK', [1, 'https://pypi.org/pypi'])
    addr, msg, data = mock_slave_driver.recv_addr_msg()
    assert msg == 'IDLE'
    mock_slave_driver.send_addr_msg(addr, 'DIE')
    addr, msg, data = mock_slave_driver.recv_addr_msg()
    assert msg == 'BYE'
    slave_thread.join(10)
    assert not slave_thread.is_alive()


def test_sleep(mock_systemd, slave_thread, mock_slave_driver):
    with mock.patch('piwheels.slave.randint', return_value=0):
        slave_thread.start()
        assert mock_systemd._ready.wait(10)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        mock_slave_driver.send_addr_msg(addr, 'ACK', [1, 'https://pypi.org/pypi'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'SLEEP', False)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'DIE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BYE'
        slave_thread.join(10)
        assert not slave_thread.is_alive()


def test_slave_build_failed(mock_systemd, slave_thread, mock_slave_driver, caplog):
    with mock.patch('piwheels.slave.Builder') as builder_mock:
        builder_mock().is_alive.return_value = False
        builder_mock().status = False
        builder_mock().as_message.return_value = [
            'foo', '1.0', False, timedelta(seconds=2), 'It all went wrong!', []
        ]
        slave_thread.start()
        assert mock_systemd._ready.wait(10)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        mock_slave_driver.send_addr_msg(addr, 'ACK', [1, 'https://pypi.org/pypi'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'BUILD', ['foo', '1.0'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUSY'
        mock_slave_driver.send_addr_msg(addr, 'CONT')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUILT'
        assert not data[0] # status
        mock_slave_driver.send_addr_msg(addr, 'DIE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BYE'
        slave_thread.join(10)
        assert not slave_thread.is_alive()


def test_connection_timeout_with_build(mock_systemd, slave_thread, mock_slave_driver, caplog):
    with mock.patch('piwheels.slave.datetime') as time_mock, \
            mock.patch('piwheels.slave.Builder') as builder_mock:
        builder_mock().is_alive.return_value = False
        builder_mock().status = False
        start = datetime.now(tz=UTC)
        time_mock.side_effect = datetime
        time_mock.now.side_effect = cycle([start])
        slave_thread.start()
        assert mock_systemd._ready.wait(10)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        mock_slave_driver.send_addr_msg(addr, 'ACK', [1, 'https://pypi.org/pypi'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'BUILD', ['foo', '1.0'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUSY'
        time_mock.now.side_effect = chain([
            start + timedelta(seconds=400),
        ], cycle([
            start + timedelta(seconds=800),
        ]))
        # Allow timeout (time_mock takes care of faking this)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        mock_slave_driver.send_addr_msg(addr, 'DIE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BYE'
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, message='Removing temporary build directories')
    assert find_message(caplog.records, message='Timed out waiting for master')


def test_slave_build_stopped(mock_systemd, slave_thread, mock_slave_driver,
                             caplog):
    with mock.patch('piwheels.slave.Builder') as builder_mock:
        builder_mock().is_alive.return_value = True
        slave_thread.start()
        assert mock_systemd._ready.wait(10)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        mock_slave_driver.send_addr_msg(addr, 'ACK', [1, 'https://pypi.org/pypi'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'BUILD', ['foo', '1.0'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUSY'
        mock_slave_driver.send_addr_msg(addr, 'CONT')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUSY'
        def mock_stop():
            builder_mock().is_alive.return_value = False
        builder_mock().stop.side_effect = mock_stop
        mock_slave_driver.send_addr_msg(addr, 'DONE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'DIE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BYE'
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, message='Terminating current build')
    assert find_message(caplog.records, message='Removing temporary build directories')


def test_slave_build_stop_failed(mock_systemd, slave_thread, mock_slave_driver,
                                 caplog):
    with mock.patch('piwheels.slave.Builder') as builder_mock:
        builder_mock().is_alive.return_value = True
        slave_thread.start()
        assert mock_systemd._ready.wait(10)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        mock_slave_driver.send_addr_msg(addr, 'ACK', [1, 'https://pypi.org/pypi'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'BUILD', ['foo', '1.0'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUSY'
        mock_slave_driver.send_addr_msg(addr, 'CONT')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUSY'
        mock_slave_driver.send_addr_msg(addr, 'DONE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BYE'
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, message='Terminating current build')
    assert find_message(caplog.records, message='Build failed to terminate')


def test_slave_build_send_done(mock_systemd, slave_thread, mock_slave_driver,
                               file_state, tmpdir, caplog):
    with mock.patch('piwheels.slave.Builder') as builder_mock:
        builder_mock().is_alive.return_value = False
        builder_mock().as_message.return_value = [
            'foo', '1.0', True, timedelta(seconds=6), '',
            [tuple(file_state)[:-1]]
        ]
        wheel_mock = mock.Mock()
        wheel_mock.filename = file_state.filename
        builder_mock().wheels = [wheel_mock]
        builder_mock().status = True
        slave_thread.start()
        assert mock_systemd._ready.wait(10)
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'HELLO'
        mock_slave_driver.send_addr_msg(addr, 'ACK', [1, 'https://pypi.org/pypi'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'BUILD', ['foo', '1.0'])
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUSY'
        mock_slave_driver.send_addr_msg(addr, 'CONT')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BUILT'
        mock_slave_driver.send_addr_msg(addr, 'SEND', 'foo-0.1-cp34-cp34m-linux_armv7l.whl')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'SENT'
        mock_slave_driver.send_addr_msg(addr, 'DONE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'IDLE'
        mock_slave_driver.send_addr_msg(addr, 'DIE')
        addr, msg, data = mock_slave_driver.recv_addr_msg()
        assert msg == 'BYE'
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, message='Build succeeded')
    assert find_message(caplog.records,
                        message='Sending foo-0.1-cp34-cp34m-linux_armv7l.whl '
                        'to master on localhost')
    assert find_message(caplog.records, message='Removing temporary build directories')
