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
import pickle
import importlib
from unittest import mock
from threading import Thread, Event
from subprocess import DEVNULL
from itertools import chain, cycle

import zmq
import pytest

from piwheels import __version__
from piwheels.slave import PiWheelsSlave, MasterTimeout


@pytest.fixture()
def mock_systemd(request):
    with mock.patch('piwheels.slave.get_systemd') as sysd_mock:
        ready = Event()
        reloading = Event()
        sysd_mock().ready.side_effect = ready.set
        sysd_mock().reloading.side_effect = reloading.set
        yield ready, reloading


@pytest.fixture()
def mock_slave_driver(request, zmq_context, tmpdir):
    queue = zmq_context.socket(zmq.ROUTER)
    queue.hwm = 1
    queue.bind('ipc://' + str(tmpdir.join('slave-driver-queue')))
    yield queue
    queue.close()


@pytest.fixture()
def mock_file_juggler(request, zmq_context, tmpdir):
    queue = zmq_context.socket(zmq.DEALER)
    queue.hwm = 1
    queue.bind('ipc://' + str(tmpdir.join('file-juggler-queue')))
    yield queue
    queue.close()


@pytest.fixture()
def mock_context(request, zmq_context, tmpdir):
    with mock.patch('zmq.Context.instance') as inst_mock:
        ctx_mock = mock.Mock(wraps=zmq_context)
        inst_mock.return_value = ctx_mock
        # Neuter the term() and destroy() methods
        ctx_mock.term = mock.Mock()
        ctx_mock.destroy = mock.Mock()
        # Override the socket() method so connect calls on the result get
        # re-directed to our local sockets above
        def socket(socket_type, **kwargs):
            sock = zmq_context.socket(socket_type, **kwargs)
            def connect(addr):
                if addr.endswith(':5555'):
                    addr = 'ipc://' + str(tmpdir.join('slave-driver-queue'))
                elif addr.endswith(':5556'):
                    addr = 'ipc://' + str(tmpdir.join('file-juggler-queue'))
                return sock.connect(addr)
            sock_mock = mock.Mock(wraps=sock)
            sock_mock.connect = mock.Mock(side_effect=connect)
            return sock_mock
        ctx_mock.socket = mock.Mock(side_effect=socket)
        yield ctx_mock


@pytest.fixture()
def slave_thread(request, mock_context, mock_systemd, tmpdir):
    main = PiWheelsSlave()
    slave_thread = Thread(daemon=True, target=main, args=([],))
    yield slave_thread


def find_message(records, message):
    for record in records:
        if record.message == message:
            return True
    else:
        return False


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
    assert find_message(caplog.records, 'Slave must not be run as root')


def test_system_exit(mock_systemd, slave_thread, mock_slave_driver):
    ready, reloading = mock_systemd
    with mock.patch('piwheels.slave.PiWheelsSlave.main_loop') as main_loop:
        main_loop.side_effect = SystemExit(1)
        slave_thread.start()
        assert ready.wait(10)
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['BYE']
        slave_thread.join(10)
        assert not slave_thread.is_alive()


def test_bye_exit(mock_systemd, slave_thread, mock_slave_driver):
    ready, reloading = mock_systemd
    slave_thread.start()
    assert ready.wait(10)
    addr, sep, data = mock_slave_driver.recv_multipart()
    assert pickle.loads(data)[0] == 'HELLO'
    mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BYE'])])
    addr, sep, data = mock_slave_driver.recv_multipart()
    assert pickle.loads(data) == ['BYE']
    slave_thread.join(10)
    assert not slave_thread.is_alive()


def test_connection_timeout(mock_systemd, slave_thread, mock_slave_driver, caplog):
    with mock.patch('piwheels.slave.time') as time_mock:
        time_mock.side_effect = chain([1.0, 401.0, 402.0], cycle([403.0]))
        ready, reloading = mock_systemd
        slave_thread.start()
        assert ready.wait(10)
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'HELLO'
        # Allow timeout (time_mock takes care of faking this)
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'HELLO'
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BYE'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['BYE']
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, 'Timed out waiting for master')


def test_bad_message_exit(mock_systemd, slave_thread, mock_slave_driver):
    ready, reloading = mock_systemd
    slave_thread.start()
    assert ready.wait(10)
    addr, sep, data = mock_slave_driver.recv_multipart()
    assert pickle.loads(data)[0] == 'HELLO'
    mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['FOO'])])
    addr, sep, data = mock_slave_driver.recv_multipart()
    assert pickle.loads(data) == ['BYE']
    slave_thread.join(10)
    assert not slave_thread.is_alive()


def test_hello(mock_systemd, slave_thread, mock_slave_driver):
    ready, reloading = mock_systemd
    slave_thread.start()
    assert ready.wait(10)
    addr, sep, data = mock_slave_driver.recv_multipart()
    assert pickle.loads(data)[0] == 'HELLO'
    mock_slave_driver.send_multipart([
        addr, sep, pickle.dumps(['HELLO', 1, 'https://pypi.org/pypi'])])
    addr, sep, data = mock_slave_driver.recv_multipart()
    assert pickle.loads(data) == ['IDLE']
    mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BYE'])])
    addr, sep, data = mock_slave_driver.recv_multipart()
    assert pickle.loads(data) == ['BYE']
    slave_thread.join(10)
    assert not slave_thread.is_alive()


def test_sleep(mock_systemd, slave_thread, mock_slave_driver):
    with mock.patch('piwheels.slave.randint', return_value=0):
        ready, reloading = mock_systemd
        slave_thread.start()
        assert ready.wait(10)
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'HELLO'
        mock_slave_driver.send_multipart([
            addr, sep, pickle.dumps(['HELLO', 1, 'https://pypi.org/pypi'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['IDLE']
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['SLEEP'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['IDLE']
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BYE'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['BYE']
        slave_thread.join(10)
        assert not slave_thread.is_alive()


def test_slave_build_failed(mock_systemd, slave_thread, mock_slave_driver, caplog):
    with mock.patch('piwheels.slave.builder.Popen') as popen_mock:
        popen_mock().returncode = 1
        ready, reloading = mock_systemd
        slave_thread.start()
        assert ready.wait(10)
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'HELLO'
        mock_slave_driver.send_multipart([
            addr, sep, pickle.dumps(['HELLO', 1, 'https://pypi.org/pypi'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['IDLE']
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BUILD', 'foo', '1.0'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'BUILT'
        assert popen_mock.call_args == mock.call([
            'pip3', 'wheel', '--index-url=https://pypi.org/pypi',
            mock.ANY, mock.ANY, '--no-deps', '--no-cache-dir',
            '--exists-action=w', '--disable-pip-version-check',
            'foo==1.0'],
            stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, env=mock.ANY
        )
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BYE'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['BYE']
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, 'Build failed')


def test_connection_timeout_with_build(mock_systemd, slave_thread, mock_slave_driver, caplog):
    with mock.patch('piwheels.slave.builder.Popen') as popen_mock, \
            mock.patch('piwheels.slave.time') as time_mock:
        time_mock.side_effect = cycle([1.0])
        ready, reloading = mock_systemd
        slave_thread.start()
        assert ready.wait(10)
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'HELLO'
        mock_slave_driver.send_multipart([
            addr, sep, pickle.dumps(['HELLO', 1, 'https://pypi.org/pypi'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['IDLE']
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BUILD', 'foo', '1.0'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'BUILT'
        time_mock.side_effect = chain([400.0], cycle([800.0]))
        # Allow timeout (time_mock takes care of faking this)
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'HELLO'
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BYE'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['BYE']
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, 'Build failed')
    assert find_message(caplog.records, 'Timed out waiting for master')


def test_slave_build_send_done(mock_systemd, slave_thread, mock_slave_driver, tmpdir, caplog):
    with mock.patch('piwheels.slave.builder.Popen') as popen_mock, \
            mock.patch('piwheels.slave.builder.PiWheelsPackage.transfer') as transfer_mock, \
            mock.patch('piwheels.slave.builder.tempfile.TemporaryDirectory') as tmpdir_mock:
        popen_mock().returncode = 0
        tmpdir_mock().name = str(tmpdir)
        tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl').ensure()
        ready, reloading = mock_systemd
        slave_thread.start()
        assert ready.wait(10)
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'HELLO'
        mock_slave_driver.send_multipart([
            addr, sep, pickle.dumps(['HELLO', 1, 'https://pypi.org/pypi'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['IDLE']
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps([
            'BUILD', 'foo', '1.0'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data)[0] == 'BUILT'
        assert popen_mock.call_args == mock.call([
            'pip3', 'wheel', '--index-url=https://pypi.org/pypi',
            mock.ANY, mock.ANY, '--no-deps', '--no-cache-dir',
            '--exists-action=w', '--disable-pip-version-check',
            'foo==1.0'],
            stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, env=mock.ANY
        )
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps([
            'SEND', 'foo-0.1-cp34-cp34m-linux_armv7l.whl'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['SENT']
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['DONE'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['IDLE']
        mock_slave_driver.send_multipart([addr, sep, pickle.dumps(['BYE'])])
        addr, sep, data = mock_slave_driver.recv_multipart()
        assert pickle.loads(data) == ['BYE']
        slave_thread.join(10)
        assert not slave_thread.is_alive()
    assert find_message(caplog.records, 'Build succeeded')
    assert find_message(caplog.records, 'Sending foo-0.1-cp34-cp34m-linux_armv7l.whl to master on localhost')
    assert find_message(caplog.records, 'Removing temporary build directories')
