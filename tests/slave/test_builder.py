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


import re
import os
import io
import zipfile
from hashlib import sha256
from unittest import mock
from pathlib import Path
from threading import Thread
from datetime import datetime, timedelta, timezone

import pytest

from piwheels import transport, proc
from piwheels.slave import builder


UTC = timezone.utc


@pytest.fixture()
def bad_archive(request):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as arc:
        arc.writestr('foo/__init__.py', b'\x00' * 123456)
        arc.writestr('foo/foo.cpython-34m-linux_armv7l-linux-gnu.so',
                     b'\x7FELF' + b'\xFF' * 123456)
        arc.writestr('foo/im.not.really.a.library.so.there',
                     b'blah' * 4096)
    return archive.getvalue()


@pytest.fixture()
def mock_archive(request, bad_archive):
    source = io.BytesIO(bad_archive)
    archive = io.BytesIO()
    with zipfile.ZipFile(source, 'r') as src:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as dest:
            for info in src.infolist():
                dest.writestr(info, src.read(info))
            dest.writestr('foo-0.1.dist-info/METADATA', """\
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
def mock_archive_requires_python(request, bad_archive):
    source = io.BytesIO(bad_archive)
    archive = io.BytesIO()
    with zipfile.ZipFile(source, 'r') as src:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as dest:
            for info in src.infolist():
                dest.writestr(info, src.read(info))
            dest.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 2.0
Name: foo
Version: 0.1
Summary: A test package
Home-page: http://foo.com/
Author: Some foo
Author-email: foo@foo.com
License: BSD
Platform: any
Requires-Python: >=3.9

""")
    return archive.getvalue()


@pytest.fixture()
def mock_archive_pip_dependencies_gpiozero_0(request, bad_archive):
    source = io.BytesIO(bad_archive)
    archive = io.BytesIO()
    with zipfile.ZipFile(source, 'r') as src:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as dest:
            for info in src.infolist():
                dest.writestr(info, src.read(info))
            dest.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 2.0
Name: gpiozero
Version: 0.1.0
Summary: A simple interface to everyday GPIO components used with Raspberry Pi
Home-page: https://github.com/RPi-Distro/gpio-zero
Author: Some fool
Author-email: foo@foo.com
License: BSD
Keywords: raspberrypi,gpio
Platform: UNKNOWN
Classifier: Development Status :: 1 - Planning
Classifier: Intended Audience :: Education
Classifier: Topic :: Education
Classifier: Topic :: System :: Hardware
Classifier: License :: OSI Approved :: BSD License
Classifier: Programming Language :: Python :: 2
Classifier: Programming Language :: Python :: 3
Requires-Dist: RPi.GPIO
Requires-Dist: w1thermsensor

""")
    return archive.getvalue()


@pytest.fixture()
def mock_archive_pip_dependencies_gpiozero_2(request, bad_archive):
    source = io.BytesIO(bad_archive)
    archive = io.BytesIO()
    with zipfile.ZipFile(source, 'r') as src:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as dest:
            for info in src.infolist():
                dest.writestr(info, src.read(info))
            dest.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 2.1
Name: gpiozero
Version: 2.0.1
Summary: A simple interface to GPIO devices with Raspberry Pi
Home-page: https://gpiozero.readthedocs.io/
Author: Some fool
Author-email: foo@foo.com
License: BSD-3-Clause
Project-URL: Documentation, https://gpiozero.readthedocs.io/
Project-URL: Source Code, https://github.com/gpiozero/gpiozero
Project-URL: Issue Tracker, https://github.com/gpiozero/gpiozero/issues
Keywords: raspberrypi gpio
Classifier: Development Status :: 5 - Production/Stable
Classifier: Intended Audience :: Education
Classifier: Intended Audience :: Developers
Classifier: Topic :: Education
Classifier: Topic :: System :: Hardware
Classifier: License :: OSI Approved :: BSD License
Classifier: Programming Language :: Python :: 3.9
Classifier: Programming Language :: Python :: 3.10
Classifier: Programming Language :: Python :: 3.11
Classifier: Programming Language :: Python :: 3.12
Classifier: Programming Language :: Python :: Implementation :: PyPy
Requires-Python: >=3.9
License-File: LICENSE.rst
Requires-Dist: colorzero
Requires-Dist: importlib-resources (~=5.0) ; python_version < "3.10"
Requires-Dist: importlib-metadata (~=4.6) ; python_version < "3.10"
Provides-Extra: doc
Requires-Dist: sphinx (>=4.0) ; extra == 'doc'
Requires-Dist: sphinx-rtd-theme (>=1.0) ; extra == 'doc'
Provides-Extra: test
Requires-Dist: pytest ; extra == 'test'
Requires-Dist: pytest-cov ; extra == 'test'

""")
    return archive.getvalue()


@pytest.fixture()
def mock_archive_pip_dependencies_download(request, bad_archive):
    source = io.BytesIO(bad_archive)
    archive = io.BytesIO()
    with zipfile.ZipFile(source, 'r') as src:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as dest:
            for info in src.infolist():
                dest.writestr(info, src.read(info))
            dest.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 1.2
Name: download
Version: 0.2.2
Summary: A tiny module to make downloading with python super easy.
Home-page: http://foo.com/
Author: Some foo
Author-email: foo@foo.com
Requires-Dist: 
Requires-Dist: tqdm
Requires-Dist: six

""")
    return archive.getvalue()


@pytest.fixture()
def mock_archive_pip_dependencies_aamm(request, bad_archive):
    source = io.BytesIO(bad_archive)
    archive = io.BytesIO()
    with zipfile.ZipFile(source, 'r') as src:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as dest:
            for info in src.infolist():
                dest.writestr(info, src.read(info))
            dest.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 2.4
Name: aa-market-manager
Version: 1.0.6
Summary: AllianceAuth Market Management Tool
Home-page: http://foo.com/
Author: Some foo
Author-email: foo@foo.com
Requires-Python: >=3.10
Requires-Dist: allianceauth>=4.6.4,<6
Requires-Dist: audioop-lts; python_version>='3.13'
Requires-Dist: django-eveuniverse
Requires-Dist: django-solo>=2,<3
Requires-Dist: ortools
Requires-Dist: py-cord>=2,<3

""")
    return archive.getvalue()


@pytest.fixture()
def mock_archive_pip_dependencies_ontology(request, bad_archive):
    source = io.BytesIO(bad_archive)
    archive = io.BytesIO()
    with zipfile.ZipFile(source, 'r') as src:
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as dest:
            for info in src.infolist():
                dest.writestr(info, src.read(info))
            dest.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 2.1
Name: ontology-processing
Version: 1.0.0
Summary: Climate Mind ontology processing code.
Home-page: http://foo.com/
Author: Some foo
Author-email: foo@foo.com
License: UNKNOWN
Platform: UNKNOWN
Classifier: Programming Language :: Python :: 3
Classifier: License :: OSI Approved :: MIT License
Classifier: Operating System :: OS Independent
Requires-Python: >=3.6
License-File: LICENSE
Requires-Dist: Brotliclickcyclerdashdash-core-componentsdash-html-componentsdash-rendererdash-tabledecoratorFlaskFlask-CompressfutureitsdangerousJinja2kiwisolverMarkupSafematplotlibnetworkxnumpyOwlready2pandasPillowplotlypyparsingpython-dateutilpytzretryingscipysixvalidatorsWerkzeug

""")
    return archive.getvalue()


@pytest.fixture()
def bad_package(request, bad_archive):
    with mock.patch('piwheels.slave.builder.Path.stat') as stat_mock, \
            mock.patch('piwheels.slave.builder.Path.open') as open_mock:
        stat_mock.return_value = os.stat_result(
            (0o644, 1, 1, 1, 1000, 1000, len(bad_archive), 0, 0, 0))
        open_mock.side_effect = lambda mode: io.BytesIO(bad_archive)
        h = sha256()
        h.update(bad_archive)
        yield len(bad_archive), h.hexdigest().lower()


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
def mock_package_requires_python(request, mock_archive_requires_python):
    with mock.patch('piwheels.slave.builder.Path.stat') as stat_mock, \
            mock.patch('piwheels.slave.builder.Path.open') as open_mock:
        stat_mock.return_value = os.stat_result(
            (0o644, 1, 1, 1, 1000, 1000, len(mock_archive_requires_python), 0, 0, 0))
        open_mock.side_effect = lambda mode: io.BytesIO(mock_archive_requires_python)
        h = sha256()
        h.update(mock_archive_requires_python)
        yield len(mock_archive_requires_python), h.hexdigest().lower()


@pytest.fixture()
def mock_package_pip_depdendencies_gpiozero_0(request, mock_archive_pip_dependencies_gpiozero_0):
    with mock.patch('piwheels.slave.builder.Path.stat') as stat_mock, \
            mock.patch('piwheels.slave.builder.Path.open') as open_mock:
        stat_mock.return_value = os.stat_result(
            (0o644, 1, 1, 1, 1000, 1000, len(mock_archive_pip_dependencies_gpiozero_0), 0, 0, 0))
        open_mock.side_effect = lambda mode: io.BytesIO(mock_archive_pip_dependencies_gpiozero_0)
        h = sha256()
        h.update(mock_archive_pip_dependencies_gpiozero_0)
        yield len(mock_archive_pip_dependencies_gpiozero_0), h.hexdigest().lower()


@pytest.fixture()
def mock_package_pip_depdendencies_gpiozero_2(request, mock_archive_pip_dependencies_gpiozero_2):
    with mock.patch('piwheels.slave.builder.Path.stat') as stat_mock, \
            mock.patch('piwheels.slave.builder.Path.open') as open_mock:
        stat_mock.return_value = os.stat_result(
            (0o644, 1, 1, 1, 1000, 1000, len(mock_archive_pip_dependencies_gpiozero_2), 0, 0, 0))
        open_mock.side_effect = lambda mode: io.BytesIO(mock_archive_pip_dependencies_gpiozero_2)
        h = sha256()
        h.update(mock_archive_pip_dependencies_gpiozero_2)
        yield len(mock_archive_pip_dependencies_gpiozero_2), h.hexdigest().lower()


@pytest.fixture()
def mock_package_pip_depdendencies_download(request, mock_archive_pip_dependencies_download):
    with mock.patch('piwheels.slave.builder.Path.stat') as stat_mock, \
            mock.patch('piwheels.slave.builder.Path.open') as open_mock:
        stat_mock.return_value = os.stat_result(
            (0o644, 1, 1, 1, 1000, 1000, len(mock_archive_pip_dependencies_download), 0, 0, 0))
        open_mock.side_effect = lambda mode: io.BytesIO(mock_archive_pip_dependencies_download)
        h = sha256()
        h.update(mock_archive_pip_dependencies_download)
        yield len(mock_archive_pip_dependencies_download), h.hexdigest().lower()


@pytest.fixture()
def mock_package_pip_depdendencies_aamm(request, mock_archive_pip_dependencies_aamm):
    with mock.patch('piwheels.slave.builder.Path.stat') as stat_mock, \
            mock.patch('piwheels.slave.builder.Path.open') as open_mock:
        stat_mock.return_value = os.stat_result(
            (0o644, 1, 1, 1, 1000, 1000, len(mock_archive_pip_dependencies_aamm), 0, 0, 0))
        open_mock.side_effect = lambda mode: io.BytesIO(mock_archive_pip_dependencies_aamm)
        h = sha256()
        h.update(mock_archive_pip_dependencies_aamm)
        yield len(mock_archive_pip_dependencies_aamm), h.hexdigest().lower()


@pytest.fixture()
def mock_package_pip_depdendencies_ontology(request, mock_archive_pip_dependencies_ontology):
    with mock.patch('piwheels.slave.builder.Path.stat') as stat_mock, \
            mock.patch('piwheels.slave.builder.Path.open') as open_mock:
        stat_mock.return_value = os.stat_result(
            (0o644, 1, 1, 1, 1000, 1000, len(mock_archive_pip_dependencies_ontology), 0, 0, 0))
        open_mock.side_effect = lambda mode: io.BytesIO(mock_archive_pip_dependencies_ontology)
        h = sha256()
        h.update(mock_archive_pip_dependencies_ontology)
        yield len(mock_archive_pip_dependencies_ontology), h.hexdigest().lower()


@pytest.fixture()
def transfer_thread(request, zmq_context, mock_systemd, mock_package):
    with zmq_context.socket(transport.DEALER) as server_sock, \
            zmq_context.socket(transport.DEALER) as client_sock:
        server_sock.bind('inproc://test-transfer')
        client_sock.connect('inproc://test-transfer')
        filesize, filehash = mock_package
        path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
        pkg = builder.Wheel(path)
        client_thread = Thread(target=pkg.transfer, args=(client_sock, 1))
        client_thread.start()
        yield server_sock
        client_thread.join(10)
        assert not client_thread.is_alive()


def test_package_init(mock_package):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.filename ==  'foo-0.1-cp34-cp34m-linux_armv7l.whl'
    assert pkg.filesize == filesize
    assert pkg.filehash == filehash
    assert pkg.package_tag == 'foo'
    assert pkg.package_version_tag == '0.1'
    assert pkg.platform_tag == 'linux_armv7l'
    assert pkg.abi_tag == 'cp34m'
    assert pkg.py_version_tag == 'cp34'
    assert pkg.build_tag is None
    assert pkg.pip_dependencies == set()


def test_package_noabi(mock_package):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-noabi-any.whl')
    pkg = builder.Wheel(path)
    assert pkg.filename ==  'foo-0.1-cp34-noabi-any.whl'
    assert pkg.filesize == filesize
    assert pkg.filehash == filehash
    assert pkg.package_tag == 'foo'
    assert pkg.package_version_tag == '0.1'
    assert pkg.platform_tag == 'any'
    assert pkg.abi_tag == 'none'
    assert pkg.py_version_tag == 'cp34'
    assert pkg.build_tag is None
    assert pkg.pip_dependencies == set()


def test_package_hash_cache(mock_package):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-noabi-any.whl')
    pkg = builder.Wheel(path)
    assert pkg.filehash == filehash
    # Second retrieval is cached
    assert pkg.filehash == filehash


def test_package_open(mock_package):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    with pkg.open() as f:
        with zipfile.ZipFile(f) as arc:
            assert len(arc.namelist()) == 4
            assert 'foo-0.1.dist-info/METADATA' in arc.namelist()
            assert 'foo/foo.cpython-34m-linux_armv7l-linux-gnu.so' in arc.namelist()
            assert 'foo/__init__.py' in arc.namelist()


def test_package_metadata(mock_package):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.metadata['Metadata-Version'] == '2.0'
    assert pkg.metadata['Name'] == 'foo'
    assert pkg.metadata['Version'] == '0.1'


def test_package_metadata_canon(mock_package):
    path = Path('/tmp/abc123/Foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.metadata['Metadata-Version'] == '2.0'
    assert pkg.metadata['Name'] == 'foo'
    assert pkg.metadata['Version'] == '0.1'


def test_package_metadata_requires_python(mock_package_requires_python):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.requires_python == '>=3.9'


def test_package_metadata_pip_depdendencies_gpiozero_0(mock_package_pip_depdendencies_gpiozero_0):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.pip_dependencies == {'rpi-gpio', 'w1thermsensor'}


def test_package_metadata_pip_depdendencies_gpiozero_2(mock_package_pip_depdendencies_gpiozero_2):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.pip_dependencies == {'colorzero', 'importlib-resources', 'importlib-metadata'}


def test_package_metadata_pip_depdendencies_download(mock_package_pip_depdendencies_download):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.pip_dependencies == {'tqdm', 'six'}


def test_package_metadata_pip_depdendencies_aamm(mock_package_pip_depdendencies_aamm):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.pip_dependencies == {
        'allianceauth',
        'audioop-lts',
        'django-eveuniverse',
        'django-solo',
        'ortools',
        'py-cord'
    }


def test_package_metadata_pip_depdendencies_ontology(mock_package_pip_depdendencies_ontology):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert pkg.pip_dependencies == set()


def test_package_bad_metadata(bad_package):
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    with pytest.raises(builder.BadWheel):
        builder.Wheel(path)


def test_package_transfer(mock_archive, mock_package, transfer_thread):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
    assert transfer_thread.recv_multipart() == [b'HELLO', b'1']
    transfer_thread.send_multipart([b'FETCH', b'0', str(filesize).encode('ascii')])
    assert transfer_thread.recv_multipart() == [b'CHUNK', b'0', mock_archive]
    transfer_thread.send_multipart([b'DONE'])


def test_package_transfer_nonsense(mock_archive, mock_package, transfer_thread):
    filesize, filehash = mock_package
    path = Path('/tmp/abc123/foo-0.1-cp34-cp34m-linux_armv7l.whl')
    pkg = builder.Wheel(path)
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


def test_builder_init(tmpdir):
    b = builder.Builder('foo', '0.1', dir=str(tmpdir))
    assert b.package == 'foo'
    assert b.version == '0.1'
    assert b.duration is None
    assert b.output == ''
    assert b.wheels == []
    assert b.status is False
    assert b.timeout == timedelta(minutes=5)


def test_builder_as_message():
    b = builder.Builder('foo', '0.1')
    assert b.as_message() == ['foo', '0.1', False, None, '', []]


def test_builder_build_success(mock_archive, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc') as proc_mock, \
            mock.patch('piwheels.slave.builder.Builder.calc_apt_dependencies') as dep_mock:
        tmpdir_mock().name = str(tmpdir)
        def call(*args, **kwargs):
            with tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl').open('wb') as f:
                f.write(mock_archive)
            return 0
        proc_mock.call.side_effect = call
        b = builder.Builder('foo', '0.1')
        b.start()
        b.join(1)
        assert not b.is_alive()
        assert b.status
        args, kwargs = proc_mock.call.call_args
        assert args[0][2] == 'foo==0.1'
        assert len(b.wheels) == 1
        assert b.wheels[0].filename == 'foo-0.1-cp34-cp34m-linux_armv7l.whl'


def test_builder_build_timeout(tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc') as proc_mock, \
            mock.patch('piwheels.slave.builder.datetime') as time_mock:
        tmpdir_mock().name = str(tmpdir)
        proc_mock.call.side_effect = proc.TimeoutExpired(['pip3'], 300)
        now = datetime.now(UTC)
        time_mock.now.side_effect = [
            now, now + timedelta(seconds=100), now + timedelta(seconds=1000),
            now + timedelta(seconds=1001)]
        b = builder.Builder('foo', '0.1')
        b.start()
        b.join(1)
        assert not b.is_alive()
        assert not b.status
        args, kwargs = proc_mock.call.call_args
        assert args[0][2] == 'foo==0.1'
        assert len(b.wheels) == 0


def test_builder_build_stop(tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc') as proc_mock, \
            mock.patch('piwheels.slave.builder.datetime') as time_mock:
        tmpdir_mock().name = str(tmpdir)
        def call(*args, **kwargs):
            assert b._stopped.wait(2)
            raise proc.ProcessTerminated('pip3', b._stopped)
        proc_mock.call.side_effect = call
        time_mock.now.return_value = datetime.now(UTC)
        b = builder.Builder('foo', '0.1')
        b.start()
        b.stop()
        b.join(1)
        assert not b.is_alive()
        assert not b.status
        assert b.output.endswith("Command 'pip3' was terminated early by event")
        assert len(b.wheels) == 0


def test_builder_build_close(tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc') as proc_mock:
        tmpdir_mock().name = str(tmpdir)
        proc_mock.call.return_value = 0
        b = builder.Builder('foo', '0.1')
        b.start()
        b.join(1)
        assert not b.is_alive()
        assert b.status
        b.close()
        assert tmpdir_mock().cleanup.call_args == mock.call()


def test_builder_calc_apt_dependencies(mock_archive, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc') as proc_mock, \
            mock.patch('piwheels.slave.builder.Path.resolve', lambda self: self), \
            mock.patch('piwheels.slave.builder.apt') as apt_mock:
        tmpdir_mock().name = str(tmpdir)
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        def call(*args, **kwargs):
            with tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl').open('wb') as f:
                f.write(mock_archive)
            return 0
        proc_mock.call.side_effect = call
        proc_mock.check_output.return_value = b"""\
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
"""
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
        b = builder.Builder('foo', '0.1')
        b.start()
        b.join(1)
        assert not b.is_alive()
        assert b.status
        print(b.wheels)
        assert b.wheels[0].apt_dependencies == {
            'libc6', 'libgcc1', 'libgfortran3', 'libopenblas-base'
        }


def test_builder_dependencies_missing(mock_archive, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc') as proc_mock, \
            mock.patch('piwheels.slave.builder.Path.resolve', side_effect=FileNotFoundError()), \
            mock.patch('piwheels.slave.builder.apt') as apt_mock:
        tmpdir_mock().name = str(tmpdir)
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        def call(*args, **kwargs):
            with tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl').open('wb') as f:
                f.write(mock_archive)
            return 0
        proc_mock.call.side_effect = call
        proc_mock.check_output.return_value = (
            b"libopenblas.so.0 => /usr/lib/libopenblas.so.0 (0x00007f7117fd4000)")
        b = builder.Builder('foo', '0.1')
        b.start()
        b.join(1)
        assert not b.is_alive()
        assert b.status
        assert b.wheels[0].dependencies == {'apt': [], 'pip': []}


def test_builder_dependencies_failed(mock_archive, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc.call') as call_mock, \
            mock.patch('piwheels.slave.builder.proc.check_output') as output_mock, \
            mock.patch('piwheels.slave.builder.apt') as apt_mock:
        tmpdir_mock().name = str(tmpdir)
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        def call(*args, **kwargs):
            with tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl').open('wb') as f:
                f.write(mock_archive)
            return 0
        call_mock.side_effect = call
        output_mock.side_effect = proc.TimeoutExpired('ldd', 30)
        b = builder.Builder('foo', '0.1')
        b.start()
        b.join(1)
        assert not b.is_alive()
        assert not b.status
        assert not b.wheels


def test_builder_dependencies_stopped(mock_archive, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc.call') as call_mock, \
            mock.patch('piwheels.slave.builder.proc.check_output') as output_mock, \
            mock.patch('piwheels.slave.builder.apt') as apt_mock, \
            mock.patch('piwheels.slave.builder.Path.resolve') as resolve_mock:
        tmpdir_mock().name = str(tmpdir)
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        def call(*args, **kwargs):
            with tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl').open('wb') as f:
                f.write(mock_archive)
            return 0
        def stop(*args, **kwargs):
            b.stop()
            return b"libopenblas.so.0 => /usr/lib/libopenblas.so.0 (0x00007f7117fd4000)"
        call_mock.side_effect = call
        output_mock.side_effect = stop
        resolve_mock.return_value = '/usr/lib/libopenblas.so.0'
        b = builder.Builder('foo', '0.1')
        b.start()
        b.join(1)
        assert not b.is_alive()
        assert not b.status
        assert re.search(r'Command .* was terminated early by event$', b.output)


def test_builder_bad_metadata(bad_archive, tmpdir):
    with mock.patch('tempfile.TemporaryDirectory') as tmpdir_mock, \
            mock.patch('piwheels.slave.builder.proc.call') as call_mock:
        tmpdir_mock().name = str(tmpdir)
        tmpdir_mock().__enter__.return_value = str(tmpdir)
        def call(*args, **kwargs):
            with tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl').open('wb') as f:
                f.write(bad_archive)
            return 0
        call_mock.side_effect = call
        b = builder.Builder('foo', '0.1')
        b.start()
        b.join(1)
        assert not b.is_alive()
        assert not b.status
        assert not b.wheels
        assert re.search(r'Unable to locate METADATA in', b.output)
