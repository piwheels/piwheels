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
import importlib
from unittest import mock
from threading import Thread, Event

import zmq
import pytest

from piwheels import __version__
from piwheels.master import main


def module_setup(module):
    importlib.reload(piwheels.systemd)


@pytest.fixture()
def mock_context(request, zmq_context):
    with mock.patch('zmq.Context.instance') as ctx_mock:
        # Pass thru calls to Context.socket, but ignore everything else (in
        # particular, destroy and term calls as we want the testing context to
        # stick around)
        ctx_mock().socket.side_effect = zmq_context.socket
        yield ctx_mock


@pytest.fixture()
def mock_systemd(request):
    with mock.patch('piwheels.master.Systemd') as sysd_mock:
        ready = Event()
        sysd_mock().ready.side_effect = ready.set
        yield ready


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


def test_quit_control(mock_context, mock_systemd,
                      tmpdir, db_url, db, with_schema):
    with mock.patch('xmlrpc.client.ServerProxy') as proxy, \
            mock.patch('signal.signal') as signal:
        proxy().changelog_since_serial.return_value = []
        main_thread = Thread(daemon=True, target=main, args=([
            '--dsn', db_url,
            '--output-path', str(tmpdir.join('output')),
            '--status-queue',  'ipc://' + str(tmpdir.join('status-queue')),
            '--control-queue', 'ipc://' + str(tmpdir.join('control-queue')),
            '--slave-queue',   'ipc://' + str(tmpdir.join('slave-queue')),
            '--file-queue',    'ipc://' + str(tmpdir.join('file-queue')),
            '--import-queue',  'ipc://' + str(tmpdir.join('import-queue')),
            '--log-queue',     'ipc://' + str(tmpdir.join('log-queue')),
        ],))
        main_thread.start()
        assert mock_systemd.wait(10)
        ctrl = mock_context().socket(zmq.PUSH)
        ctrl.connect('ipc://' + str(tmpdir.join('control-queue')))
        ctrl.send_pyobj(['QUIT'])
        ctrl.close()
        main_thread.join(10)
        assert not main_thread.is_alive()
