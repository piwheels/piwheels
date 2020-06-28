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
import zipfile
from hashlib import sha256
from unittest import mock
from pathlib import Path
from threading import Thread
from datetime import timedelta

import pytest

from conftest import find_message
from piwheels import __version__, protocols, transport
from piwheels.importer import main


@pytest.fixture()
def mock_wheel(request, tmpdir):
    filename = str(tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl'))
    with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_STORED) as arc:
        arc.writestr('foo/__init__.py', b'\x00' * 123456)
        arc.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 2.0
Name: foo
Version: 0.1
Summary: A test package
Home-page: http://foo.com/
Author: Some foo
Author-email: foo@foo.com
License: BSD
Platform: any
Classifier: Development Status :: 5 - Production/Stable
Classifier: Intended Audience :: Developers
Classifier: License :: OSI Approved :: BSD License
Classifier: Operating System :: OS Independent
Classifier: Programming Language :: Python

""")
    return filename


@pytest.fixture()
def mock_wheel_no_abi(request, tmpdir):
    filename = str(tmpdir.join('foo-0.1-cp34-none-any.whl'))
    with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_STORED) as arc:
        arc.writestr('foo/__init__.py', b'\x00' * 123456)
        arc.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 2.0
Name: foo
Version: 0.1
Summary: A test package
Home-page: http://foo.com/
Author: Some foo
Author-email: foo@foo.com
License: BSD
Platform: any
Classifier: Development Status :: 5 - Production/Stable
Classifier: Intended Audience :: Developers
Classifier: License :: OSI Approved :: BSD License
Classifier: Operating System :: OS Independent
Classifier: Programming Language :: Python

""")
    return filename


@pytest.fixture()
def mock_wheel_stats(request, mock_wheel):
    h = sha256()
    with Path(mock_wheel) as p:
        with p.open('rb') as f:
            h.update(f.read())
        return p.stat().st_size, h.hexdigest().lower()


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


class ImportThread(Thread):
    def __init__(self, args):
        super().__init__(target=self.capture_exc, args=(args,), daemon=True)
        self.exception = None
        self.exitcode = None

    def capture_exc(self, args):
        try:
            self.exitcode = main(args)
        except Exception as e:
            self.exception = e

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.join(10)
        assert not self.is_alive()


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--package' in out
    assert '--package-version' in out
    assert '--abi' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_abort(mock_wheel):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        assert main([mock_wheel]) == 2


def test_auto_package_version(mock_wheel, caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        main([mock_wheel])
    assert find_message(caplog.records, message='Package:  foo')
    assert find_message(caplog.records, message='Version:  0.1')


def test_manual_package_version(mock_wheel, caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        main(['--package', 'bar', '--package-version', '0.2', mock_wheel])
    assert find_message(caplog.records, message='Package:  bar')
    assert find_message(caplog.records, message='Version:  0.2')


def test_import_failure(mock_wheel, mock_wheel_stats, import_queue_name, import_queue):
    filesize, filehash = mock_wheel_stats
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with ImportThread(['--import-queue', import_queue_name, mock_wheel]) as thread:
            assert import_queue.recv_msg() == (
                'IMPORT', [
                    0, 'foo', '0.1', 'cp34m', True, timedelta(0),
                    'Imported manually via piw-import', [
                        [
                            'foo-0.1-cp34-cp34m-linux_armv7l.whl',
                            filesize, filehash, 'foo', '0.1',
                            'cp34', 'cp34m', 'linux_armv7l', {},
                        ],
                    ]
                ]
            )
            import_queue.send_msg('ERROR', 'Unknown package "foo"')
            thread.join(10)
            assert isinstance(thread.exception, RuntimeError)


def test_import_send_failure(mock_wheel, mock_wheel_stats, import_queue_name, import_queue):
    filesize, filehash = mock_wheel_stats
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with ImportThread(['--import-queue', import_queue_name, mock_wheel]) as thread, \
                mock.patch('piwheels.slave.builder.Wheel.transfer') as transfer_mock:
            assert import_queue.recv_msg() == (
                'IMPORT', [
                    0, 'foo', '0.1', 'cp34m', True, timedelta(0),
                    'Imported manually via piw-import', [
                        [
                            'foo-0.1-cp34-cp34m-linux_armv7l.whl',
                            filesize, filehash, 'foo', '0.1',
                            'cp34', 'cp34m', 'linux_armv7l', {},
                        ],
                    ]
                ]
            )
            import_queue.send_msg('SEND', 'foo-0.1-cp34-cp34m-linux_armv7l.whl')
            assert import_queue.recv_msg() == ('SENT', None)
            import_queue.send(b'FOO')
            thread.join(10)
            assert isinstance(thread.exception, IOError)


def test_import_no_delete_on_fail(mock_wheel, mock_wheel_stats, import_queue_name, import_queue):
    filesize, filehash = mock_wheel_stats
    with ImportThread(['-y', '--delete', '--import-queue', import_queue_name, mock_wheel]) as thread, \
            mock.patch('piwheels.slave.builder.Wheel.transfer') as transfer_mock:
        assert import_queue.recv_msg() == (
            'IMPORT', [
                0, 'foo', '0.1', 'cp34m', True, timedelta(0),
                'Imported manually via piw-import', [
                    [
                        'foo-0.1-cp34-cp34m-linux_armv7l.whl',
                        filesize, filehash, 'foo', '0.1',
                        'cp34', 'cp34m', 'linux_armv7l', {},
                    ],
                ]
            ]
        )
        import_queue.send_msg('SEND', 'foo-0.1-cp34-cp34m-linux_armv7l.whl')
        assert import_queue.recv_msg() == ('SENT', None)
        import_queue.send_msg('ERROR', 'The master broke')
        thread.join(10)
        assert isinstance(thread.exception, RuntimeError)
        assert os.path.exists(mock_wheel)


def test_import_success(mock_wheel, mock_wheel_stats, import_queue_name, import_queue):
    filesize, filehash = mock_wheel_stats
    with ImportThread(['-y', '--import-queue', import_queue_name, mock_wheel]) as thread, \
            mock.patch('piwheels.slave.builder.Wheel.transfer') as transfer_mock:
        assert import_queue.recv_msg() == (
            'IMPORT', [
                0, 'foo', '0.1', 'cp34m', True, timedelta(0),
                'Imported manually via piw-import', [
                    [
                        'foo-0.1-cp34-cp34m-linux_armv7l.whl',
                        filesize, filehash, 'foo', '0.1',
                        'cp34', 'cp34m', 'linux_armv7l', {},
                    ],
                ]
            ]
        )
        import_queue.send_msg('SEND', 'foo-0.1-cp34-cp34m-linux_armv7l.whl')
        assert import_queue.recv_msg() == ('SENT', None)
        import_queue.send_msg('DONE')
        thread.join(10)
        assert thread.exception is None
        assert thread.exitcode == 0
        assert os.path.exists(mock_wheel)


def test_import_override_log(mock_wheel, mock_wheel_stats, import_queue_name, import_queue, tmpdir):
    filesize, filehash = mock_wheel_stats
    output = tmpdir.join('foo_output.txt')
    output.write('FOO\n')
    with ImportThread(['-y', '--output', str(output), '--import-queue', import_queue_name, mock_wheel]) as thread, \
            mock.patch('piwheels.slave.builder.Wheel.transfer') as transfer_mock:
        assert import_queue.recv_msg() == (
            'IMPORT', [
                0, 'foo', '0.1', 'cp34m', True, timedelta(0), 'FOO\n', [
                    [
                        'foo-0.1-cp34-cp34m-linux_armv7l.whl',
                        filesize, filehash, 'foo', '0.1',
                        'cp34', 'cp34m', 'linux_armv7l', {},
                    ],
                ]
            ]
        )
        import_queue.send_msg('SEND', 'foo-0.1-cp34-cp34m-linux_armv7l.whl')
        assert import_queue.recv_msg() == ('SENT', None)
        import_queue.send_msg('DONE')
        thread.join(10)
        assert thread.exception is None
        assert thread.exitcode == 0
        assert os.path.exists(mock_wheel)


def test_import_no_abi(mock_wheel_no_abi, mock_wheel_stats, import_queue_name, import_queue):
    mock_wheel = mock_wheel_no_abi
    with pytest.raises(RuntimeError):
        main(['-y', '--import-queue', import_queue_name, mock_wheel])


def test_import_override_abi(mock_wheel_no_abi, mock_wheel_stats, import_queue_name, import_queue):
    mock_wheel = mock_wheel_no_abi
    filesize, filehash = mock_wheel_stats
    with ImportThread(['-y', '--abi', 'cp35m', '--import-queue', import_queue_name, mock_wheel]) as thread, \
            mock.patch('piwheels.slave.builder.Wheel.transfer') as transfer_mock:
        assert import_queue.recv_msg() == (
            'IMPORT', [
                0, 'foo', '0.1', 'cp35m', True, timedelta(0),
                'Imported manually via piw-import', [
                    [
                        'foo-0.1-cp34-none-any.whl',
                        filesize, filehash, 'foo', '0.1',
                        'cp34', 'none', 'any', {},
                    ],
                ]
            ]
        )
        import_queue.send_msg('SEND', 'foo-0.1-cp34-none-any.whl')
        assert import_queue.recv_msg() == ('SENT', None)
        import_queue.send_msg('DONE')
        thread.join(10)
        assert thread.exception is None
        assert thread.exitcode == 0
        assert os.path.exists(mock_wheel)


def test_import_then_delete(mock_wheel, mock_wheel_stats, import_queue_name, import_queue):
    filesize, filehash = mock_wheel_stats
    with ImportThread(['-y', '--delete', '--import-queue', import_queue_name, mock_wheel]) as thread, \
            mock.patch('piwheels.slave.builder.Wheel.transfer') as transfer_mock:
        assert import_queue.recv_msg() == (
            'IMPORT', [
                0, 'foo', '0.1', 'cp34m', True, timedelta(0),
                'Imported manually via piw-import', [
                    [
                        'foo-0.1-cp34-cp34m-linux_armv7l.whl',
                        filesize, filehash, 'foo', '0.1',
                        'cp34', 'cp34m', 'linux_armv7l', {},
                    ],
                ]
            ]
        )
        import_queue.send_msg('SEND', 'foo-0.1-cp34-cp34m-linux_armv7l.whl')
        assert import_queue.recv_msg() == ('SENT', None)
        import_queue.send_msg('DONE')
        thread.join(10)
        assert thread.exception is None
        assert thread.exitcode == 0
        assert not os.path.exists(mock_wheel)
