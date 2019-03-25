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
import io
import zipfile
from hashlib import sha256
from unittest import mock
from pathlib import Path
from threading import Thread, Event
from subprocess import TimeoutExpired
from datetime import datetime, timedelta

import pytest

from piwheels import systemd, transport
from piwheels.slave import builder


@pytest.fixture()
def mock_archive(request):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as arc:
        arc.writestr('foo/__init__.py', b'\x00' * 123456)
        arc.writestr('foo/foo.cpython-34m-linux_armv7l-linux-gnu.so',
                     b'\x7FELF' + b'\xFF' * 123456)
        arc.writestr('foo/im.not.really.a.library.so.there',
                     b'blah' * 4096)
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
    return archive.getvalue()


@pytest.fixture()
def mock_package(request, mock_archive):
    with mock.patch('piwheels.slave.builder.Path.stat') as stat_mock, \
            mock.patch('piwheels.slave.builder.Path.open') as open_mock:
        stat_mock.return_value = os.stat_result(
            (0o644, 1, 1, 1, 1000, 1000, len(mock_archive), 0, 0, 0))
        open_mock.side_effect = lambda mode: io.BytesIO(mock_archive)
        h = sha256()
        h.update(mock_archive)
        yield len(mock_archive), h.hexdigest().lower()


@pytest.fixture()
def transfer_thread(request, zmq_context, mock_systemd, mock_package):
    with zmq_context.socket(transport.DEALER) as server_sock, \
            zmq_context.socket(transport.DEALER) as client_sock:
        server_sock.bind('inproc://test-transfer')
        client_sock.connect('inproc://test-transfer')
        filesize, filehash = mock_package
        path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
        pkg = builder.PiWheelsPackage(path)
        client_thread = Thread(target=pkg.transfer, args=(client_sock, 1))
        client_thread.start()
        yield server_sock
        client_thread.join(10)
        assert not client_thread.is_alive()


def test_package_init(mock_package):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.PiWheelsPackage(path)
    assert pkg.filename ==  'foo-0.1-cp34-cp34m-linux_armv7l.whl'
    assert pkg.filesize == filesize
    assert pkg.filehash == filehash
    assert pkg.package_tag == 'foo'
    assert pkg.package_version_tag == '0.1'
    assert pkg.platform_tag == 'linux_armv7l'
    assert pkg.abi_tag == 'cp34m'
    assert pkg.py_version_tag == 'cp34'
    assert pkg.build_tag is None


def test_package_noabi(mock_package):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-noabi-any.whl')
    pkg = builder.PiWheelsPackage(path)
    assert pkg.filename ==  'foo-0.1-cp34-noabi-any.whl'
    assert pkg.filesize == filesize
    assert pkg.filehash == filehash
    assert pkg.package_tag == 'foo'
    assert pkg.package_version_tag == '0.1'
    assert pkg.platform_tag == 'any'
    assert pkg.abi_tag == 'none'
    assert pkg.py_version_tag == 'cp34'
    assert pkg.build_tag is None


def test_package_hash_cache(mock_package):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-noabi-any.whl')
    pkg = builder.PiWheelsPackage(path)
    assert pkg.filehash == filehash
    # Second retrieval is cached
    assert pkg.filehash == filehash


def test_package_open(mock_package):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.PiWheelsPackage(path)
    with pkg.open() as f:
        with zipfile.ZipFile(f) as arc:
            assert len(arc.namelist()) == 4
            assert 'foo-0.1.dist-info/METADATA' in arc.namelist()
            assert 'foo/foo.cpython-34m-linux_armv7l-linux-gnu.so' in arc.namelist()
            assert 'foo/__init__.py' in arc.namelist()


def test_package_metadata(mock_package):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.PiWheelsPackage(path)
    assert pkg.metadata['Metadata-Version'] == '2.0'
    assert pkg.metadata['Name'] == 'foo'
    assert pkg.metadata['Version'] == '0.1'


def test_package_dependencies(mock_package, tmpdir):
    builder.PiWheelsPackage.apt_cache = None
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.Popen') as popen_mock, \
            mock.patch('piwheels.slave.builder.Path.resolve', lambda self: self), \
            mock.patch('piwheels.slave.builder.apt') as apt_mock:
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        popen_mock().communicate.return_value = (b"""\
        linux-vdso.so.1 =>  (0x00007ffd48669000)
        libblas.so.3 => /usr/lib/libblas.so.3 (0x00007f711a958000)
        libm.so.6 => /lib/arm-linux-gnueabihf/libm.so.6 (0x00007f711a64f000)
        libpthread.so.0 => /lib/arm-linux-gnueabihf/libpthread.so.0 (0x00007f711a432000)
        libc.so.6 => /lib/arm-linux-gnueabihf/libc.so.6 (0x00007f711a068000)
        /lib64/ld-linux-x86-64.so.2 (0x00007f711af48000)
        libopenblas.so.0 => /usr/lib/libopenblas.so.0 (0x00007f7117fd4000)
        libgfortran.so.3 => /usr/lib/arm-linux-gnueabihf/libgfortran.so.3 (0x00007f7117ca9000)
        libquadmath.so.0 => /usr/lib/arm-linux-gnueabihf/libquadmath.so.0 (0x00007f7117a6a000)
        libgcc_s.so.1 => /lib/arm-linux-gnueabihf/libgcc_s.so.1 (0x00007f7117854000)
""", b"")
        popen_mock().returncode = 0
        def pkg(name, files):
            m = mock.Mock()
            m.name = name
            m.installed = True
            m.installed_files = files
            return m
        apt_mock.cache.Cache.return_value = [
            pkg('libc6', [
                '/lib/arm-linux-gnueabihf/libc.so.6',
                '/lib/arm-linux-gnueabihf/libm.so.6',
                '/lib/arm-linux-gnueabihf/libpthread.so.0',
            ]),
            pkg('libopenblas-base', [
                '/usr/lib/libblas.so.3',
                '/usr/lib/libopenblas.so.0',
            ]),
            pkg('libgcc1', ['/lib/arm-linux-gnueabihf/libgcc_s.so.1']),
            pkg('libgfortran3', ['/usr/lib/arm-linux-gnueabihf/libgfortran.so.3']),
        ]
        path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
        pkg = builder.PiWheelsPackage(path)
        assert pkg.dependencies == {
            'apt': ['libc6', 'libgcc1', 'libgfortran3', 'libopenblas-base'],
            '': ['/usr/lib/arm-linux-gnueabihf/libquadmath.so.0'],
        }


def test_package_dependencies_missing(mock_package, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.Popen') as popen_mock, \
            mock.patch('piwheels.slave.builder.Path.resolve', side_effect=FileNotFoundError()), \
            mock.patch('piwheels.slave.builder.apt') as apt_mock:
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        popen_mock().communicate.return_value = (
            b"libopenblas.so.0 => /usr/lib/libopenblas.so.0 (0x00007f7117fd4000)", b"")
        popen_mock().returncode = 0
        path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
        pkg = builder.PiWheelsPackage(path)
        assert pkg.dependencies == {}


def test_package_dependencies_cached(mock_package, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.Popen') as popen_mock, \
            mock.patch('piwheels.slave.builder.Path.resolve', side_effect=FileNotFoundError()), \
            mock.patch('piwheels.slave.builder.apt') as apt_mock:
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        popen_mock().communicate.return_value = (
            b"libopenblas.so.0 => /usr/lib/libopenblas.so.0 (0x00007f7117fd4000)", b"")
        popen_mock().returncode = 0
        path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
        pkg = builder.PiWheelsPackage(path)
        assert pkg.dependencies == {}
        tmpdir_mock.reset_mock()
        assert pkg.dependencies == {}
        assert tmpdir_mock.call_count == 0


def test_package_dependencies_failed(mock_package, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.Popen') as popen_mock, \
            mock.patch('piwheels.slave.builder.apt') as apt_mock:
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        popen_mock().communicate.side_effect = [
            TimeoutExpired('ldd', 10), (b"", b"")]
        path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
        pkg = builder.PiWheelsPackage(path)
        assert pkg.dependencies == {}


def test_package_transfer(mock_archive, mock_package, transfer_thread):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.PiWheelsPackage(path)
    assert transfer_thread.recv_multipart() == [b'HELLO', b'1']
    transfer_thread.send_multipart([b'FETCH', b'0', str(filesize).encode('ascii')])
    assert transfer_thread.recv_multipart() == [b'CHUNK', b'0', mock_archive]
    transfer_thread.send_multipart([b'DONE'])


def test_package_transfer_nonsense(mock_archive, mock_package, transfer_thread):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.PiWheelsPackage(path)
    assert transfer_thread.recv_multipart() == [b'HELLO', b'1']
    transfer_thread.send_multipart([b'FOO', b'BAR'])
    # Continue with the transfer normally; the anomalous message should be
    # ignored and the protocol should continue
    transfer_thread.send_multipart([b'FETCH', b'0', b'4096'])
    transfer_thread.send_multipart([b'FETCH', b'4096', str(filesize - 4096).encode('ascii')])
    chunk1 = transfer_thread.recv_multipart()
    chunk2 = transfer_thread.recv_multipart()
    assert chunk1 == [b'CHUNK', b'0', mock_archive[:4096]]
    assert chunk2 == [b'CHUNK', b'4096', mock_archive[4096:]]
    transfer_thread.send_multipart([b'DONE'])


def test_builder_init():
    b = builder.PiWheelsBuilder('foo', '0.1')
    assert b.wheel_dir is None
    assert b.package == 'foo'
    assert b.version == '0.1'
    assert b.duration is None
    assert b.output == ''
    assert b.files == []
    assert not b.status


def test_builder_as_message():
    b = builder.PiWheelsBuilder('foo', '0.1')
    assert b.as_message == ['foo', '0.1', False, None, '', []]


def test_builder_build_success(mock_archive, mock_systemd, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.Popen') as popen_mock:
        tmpdir_mock().name = str(tmpdir)
        def wait(timeout):
            with tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl').open('wb') as f:
                f.write(mock_archive)
        popen_mock().wait.side_effect = wait
        popen_mock().returncode = 0
        b = builder.PiWheelsBuilder('foo', '0.1')
        b.build()
        assert b.status
        args, kwargs = popen_mock.call_args
        assert args[0][-1] == 'foo==0.1'
        assert len(b.files) == 1
        assert b.files[0].filename == 'foo-0.1-cp34-cp34m-linux_armv7l.whl'


def test_builder_build_timeout(mock_systemd, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.Popen') as popen_mock, \
            mock.patch('piwheels.slave.builder.datetime') as time_mock:
        tmpdir_mock().name = str(tmpdir)
        popen_mock().wait.side_effect = TimeoutExpired('pip3', 300)
        popen_mock().returncode = -9
        now = datetime.utcnow()
        time_mock.utcnow.side_effect = [
            now, now + timedelta(seconds=100), now + timedelta(seconds=1000),
            now + timedelta(seconds=1001)]
        b = builder.PiWheelsBuilder('foo', '0.1')
        b.build()
        assert not b.status
        args, kwargs = popen_mock.call_args
        assert args[0][-1] == 'foo==0.1'
        assert len(b.files) == 0
        assert popen_mock().terminate.call_count == 1
        assert popen_mock().kill.call_count == 1


def test_builder_build_clean(mock_systemd, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.Popen') as popen_mock:
        tmpdir_mock().name = str(tmpdir)
        popen_mock().wait.side_effect = lambda timeout: None
        popen_mock().returncode = 0
        b = builder.PiWheelsBuilder('foo', '0.1')
        b.build()
        assert b.status
        b.clean()
        assert tmpdir_mock().cleanup.call_args == mock.call()
