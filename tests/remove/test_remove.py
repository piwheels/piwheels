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
from piwheels.remove import main


@pytest.fixture()
def import_queue_name(request, tmpdir):
    yield 'ipc://' + str(tmpdir.join('import-queue'))


@pytest.fixture()
def import_queue(request, mock_context, import_queue_name, tmpdir):
    queue = mock_context.socket(transport.REP, protocol=protocols.mr_chase)
    queue.hwm = 1
    queue.bind(import_queue_name)
    yield queue
    queue.close()


class RemoveThread(Thread):
    def __init__(self, args):
        super().__init__(target=self.capture_exc, args=(args,), daemon=True)
        self.exception = None
        self.exitcode = None

    def capture_exc(self, args):
        try:
            self.exitcode = main(args)
        except Exception as e:
            self.exception = e

    def join(self, timeout):
        super().join(timeout)
        if self.exception:
            raise self.exception  # re-raise in the main thread

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        try:
            self.join(10)
        except Exception:
            pass  # ignore any re-raise
        assert not self.is_alive()


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--yes' in out
    assert '--skip' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_abort(caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        assert main(['foo', '0.1']) == 2
    assert find_message(caplog.records, message='User aborted removal')


def test_remove_package(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, 'foo']) as thread:
            assert import_queue.recv_msg() == ('REMPKG', ['foo', False, ''])
            import_queue.send_msg('DONE', 'DELPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_remove_package_builds(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, '--builds', 'foo']) as thread:
            assert import_queue.recv_msg() == ('REMPKG', ['foo', True, ''])
            import_queue.send_msg('DONE', 'DELPKGBLD')
            thread.join(10)
            assert thread.exitcode == 0


def test_remove_missing_package(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, 'foo']) as thread:
            assert import_queue.recv_msg() == ('REMPKG', ['foo', False, ''])
            import_queue.send_msg('ERROR', 'NOPKG')
            with pytest.raises(RuntimeError) as exc:
                thread.join(10)
            assert 'Package foo does not exist' in str(exc.value)


def test_skip_package(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, '--skip', 'broken', 'foo']) as thread:
            assert import_queue.recv_msg() == ('REMPKG', ['foo', False, 'broken'])
            import_queue.send_msg('DONE', 'SKIPPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_remove_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, 'foo', '0.1']) as thread:
            assert import_queue.recv_msg() == ('REMVER', ['foo', '0.1', False, '', False])
            import_queue.send_msg('DONE', 'DELVER')
            thread.join(10)
            assert thread.exitcode == 0


def test_remove_version_builds(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, '--builds', 'foo', '0.1']) as thread:
            assert import_queue.recv_msg() == ('REMVER', ['foo', '0.1', True, '', False])
            import_queue.send_msg('DONE', 'DELVERBLD')
            thread.join(10)
            assert thread.exitcode == 0


def test_remove_missing_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, 'foo', '0.1']) as thread:
            assert import_queue.recv_msg() == ('REMVER', ['foo', '0.1', False, '', False])
            import_queue.send_msg('ERROR', 'NOVER')
            with pytest.raises(RuntimeError) as exc:
                thread.join(10)
            assert 'Version foo 0.1 does not exist' in str(exc.value)


def test_remove_and_skip(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, 'foo', '0.1', '--skip', 'legal']) as thread:
            assert import_queue.recv_msg() == ('REMVER', ['foo', '0.1', False, 'legal', False])
            import_queue.send_msg('DONE', 'SKIPVER')
            thread.join(10)
            assert thread.exitcode == 0


def test_yank_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with RemoveThread(['--import-queue', import_queue_name, 'foo', '0.1', '--yank']) as thread:
            assert import_queue.recv_msg() == ('REMVER', ['foo', '0.1', False, '', True])
            import_queue.send_msg('DONE', 'YANKVER')
            thread.join(10)
            assert thread.exitcode == 0


def test_failure(mock_context, import_queue_name, import_queue):
    with RemoveThread(['--import-queue', import_queue_name, 'foo', '0.1', '--yes']) as thread:
        assert import_queue.recv_msg() == ('REMVER', ['foo', '0.1', False, '', False])
        import_queue.send_msg('ERROR', 'NOPKG')
        with pytest.raises(RuntimeError) as exc:
            thread.join(10)
        assert 'Package foo does not exist' in str(exc.value)
