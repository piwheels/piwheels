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

"""
Defines the classes which use ``pip`` to build wheels.

.. autoclass:: Wheel
    :members:

.. autoclass:: Builder
    :members:
"""

import os
import re
import zipfile
import hashlib
import resource
import tempfile
import warnings
import email.parser
from pathlib import Path
from datetime import datetime, timedelta
from threading import Thread, Event
from collections import defaultdict

import apt

from .. import proc


class BuildTerminated(Exception):
    pass


class Wheel:
    """
    Records the state of a build artifact, i.e. a wheel package. The filename
    is deconstructed into the fields specified by :pep:`425`.

    :param pathlib.Path path:
        The path to the wheel on the local filesystem.
    """
    def __init__(self, path, dependencies=None):
        self.wheel_file = path
        self._filesize = path.stat().st_size
        self._filehash = None
        self._metadata = None
        if dependencies is None:
            dependencies = {}
        self._dependencies = dependencies
        self._parts = list(path.stem.split('-'))
        # Fix up retired tags (noabi->none)
        if self._parts[-2] == 'noabi':
            self._parts[-2] = 'none'

    def as_message(self):
        """
        Return the state as a list suitable for use in the ``BUILT`` message
        of :program:`piw-slave`.
        """
        return (
            self.filename,
            self.filesize,
            self.filehash,
            self.package_tag,
            self.package_version_tag,
            self.py_version_tag,
            self.abi_tag,
            self.platform_tag,
            self.dependencies
        )

    @property
    def filename(self):
        """
        Return the filename of the wheel as a simple string (with no path
        components).
        """
        return self.wheel_file.name

    @property
    def filesize(self):
        """
        Return the size of the wheel in bytes.
        """
        return self._filesize

    @property
    def filehash(self):
        """
        Return an SHA256 digest of the wheel's contents.
        """
        if self._filehash is None:
            s = hashlib.sha256()
            with self.wheel_file.open('rb') as f:
                while True:
                    buf = f.read(65536)
                    if buf:
                        s.update(buf)
                    else:
                        break
            self._filehash = s.hexdigest().lower()
        return self._filehash

    @property
    def package_tag(self):
        """
        Return the package part of the wheel's filename (the first "-"
        separated element).
        """
        return self._parts[0]

    @property
    def package_version_tag(self):
        """
        Return the version part of the wheel's filename (the second "-"
        separated element).
        """
        return self._parts[1]

    @property
    def platform_tag(self):
        """
        Return the platform part of the wheel's filename (the last "-"
        separated element).
        """
        return self._parts[-1]

    @property
    def abi_tag(self):
        """
        Return the ABI part of the wheel's filename (the penultimate "-"
        separated element).
        """
        return self._parts[-2]

    @property
    def py_version_tag(self):
        """
        Return the python version part of the wheel's filename (third from last
        "-" separated element).
        """
        return self._parts[-3]

    @property
    def build_tag(self):
        """
        Return the optional build part of the wheel's filename (the third "-"
        separated element when 6 elements exist in total).
        """
        return self._parts[2] if len(self._parts) == 6 else None

    def open(self):
        """
        Open the wheel in binary mode and return the open file object.
        """
        return self.wheel_file.open('rb')

    @property
    def dependencies(self):
        """
        Return the dependencies required by the wheel as a mapping of
        dependency system (e.g. "apt", "pip", etc.) to set of package names for
        that system.
        """
        return self._dependencies

    @property
    def metadata(self):
        """
        Return the contents of the :file:`METADATA` file inside the wheel.
        """
        if self._metadata is None:
            with zipfile.ZipFile(self.open()) as wheel:
                filename = (
                    '{self.package_tag}-'
                    '{self.package_version_tag}.dist-info/'
                    'METADATA'.format(self=self)
                )
                with wheel.open(filename) as metadata:
                    parser = email.parser.BytesParser()
                    self._metadata = parser.parse(metadata)
        return self._metadata

    def transfer(self, queue, slave_id):
        """
        Transfer the wheel via the specified *queue*. This is the client side
        implementation of the :class:`.file_juggler.FileJuggler` protocol.
        """
        with self.open() as f:
            timeout = 0
            while True:
                if not queue.poll(timeout):
                    # Initially, send HELLO immediately; in subsequent loops if
                    # we hear nothing from the server for 5 seconds then it's
                    # dropped a *lot* of packets; prod the master with HELLO
                    queue.send_multipart(
                        [b'HELLO', str(slave_id).encode('ascii')]
                    )
                    timeout = 5
                else:
                    req, *args = queue.recv_multipart()
                    if req == b'DONE':
                        return
                    elif req == b'FETCH':
                        offset, size = args
                        f.seek(int(offset))
                        queue.send_multipart([b'CHUNK', offset, f.read(int(size))])


class Builder(Thread):
    """
    Class responsible for building wheels for a given *version* of a *package*.
    Note that this class derives from :class:`~threading.Thread` and hence is
    expected to run in the background after calling
    :meth:`~threading.Thread.start`.

    :param str package:
        The name of the package to attempt to build wheels for.

    :param str version:
        The version of the package to attempt to build.

    :param datetime.timedelta timeout:
        The number of seconds to wait for ``pip`` to finish before raising
        :exc:`subprocess.TimeoutExpired`.

    :param str pypi_index:
        The URL of the :pep:`503` compliant repository from which to fetch
        packages for building.

    :param str dir:
        The directory in which to store wheel and log output.
    """
    apt_cache = None

    def __init__(self, package, version, timeout=timedelta(minutes=5),
                 pypi_index='https://pypi.python.org/simple', dir=None):
        super().__init__()
        self._wheel_dir = tempfile.TemporaryDirectory(dir=dir)
        self._package = package
        self._version = version
        self._timeout = timeout
        self._pypi_index = pypi_index
        self._duration = None
        self._output = ''
        self._wheels = []
        self._status = False
        self._stopped = Event()

    def close(self):
        """
        Remove the temporary build directory and all its contents.
        """
        if self._wheel_dir is not None:
            self._wheel_dir.cleanup()
            self._wheel_dir = None

    @property
    def package(self):
        """
        The package that the builder will attempt to build.
        """
        return self._package

    @property
    def version(self):
        """
        The version of :attr:`package` that the builder will attempt to build.
        """
        return self._version

    @property
    def timeout(self):
        """
        The :class:`~datetime.timedelta` after which the builder will assume
        the build has failed.
        """
        return self._timeout

    @property
    def pypi_index(self):
        """
        The URL of the PyPI server from which the builder will attempt to
        obtain the source to build.
        """
        return self._pypi_index

    @property
    def wheels(self):
        """
        A list of :class:`Wheel` instances generated by the build.
        """
        return [] if self.is_alive() else self._wheels

    @property
    def output(self):
        """
        The log output from the build.
        """
        return None if self.is_alive() else self._output

    @property
    def duration(self):
        """
        The :class:`~datetime.timedelta` indicating how long the actual build
        took (without any extraneous tasks like dependency calculation). This
        is an indication of how long a user would spend installing the package
        without piwheels.
        """
        return None if self.is_alive() else self._duration

    @property
    def status(self):
        """
        A :class:`bool` indicating if the build succeeded or failed. If the
        build is still on-going, returns :data:`None`.
        """
        return None if self.is_alive() else self._status

    def stop(self):
        """
        Tell the build to stop prematurely.
        """
        self._stopped.set()

    def as_message(self):
        """
        Return the state as a list suitable for use in the ``BUILT`` message
        of :program:`piw-slave`.
        """
        return [
            self.package,
            self.version,
            self.status,
            self.duration,
            self.output,
            [pkg.as_message() for pkg in self._wheels]
        ]

    def build_environment(self):
        """
        Configure the environment for the build.
        """
        # Limit the data segment of this process (and all children) to 1Gb
        # in size. This doesn't guarantee that stuff can't grow until it
        # crashes (multiple children can violate the limit together while
        # obeying it individually), but it should reduce the incidence of
        # huge C++ compiles killing the build slaves
        resource.setrlimit(resource.RLIMIT_DATA, (1024**3, 1024**3))
        env = os.environ.copy()
        # Force git to fail if it needs to prompt for anything (a
        # disturbing minority of packages try to run git clone during their
        # setup.py)
        env['GIT_ALLOW_PROTOCOL'] = 'file'
        return env

    def build_command(self, log_file):
        """
        Generate the pip command line used to run the build.
        """
        return [
            'pip3', 'wheel',
            '--index-url={}'.format(self.pypi_index),
            '--wheel-dir={}'.format(self._wheel_dir.name),
            '--log={}'.format(log_file.name),
            '--no-deps',                    # don't build dependencies
            '--no-cache-dir',               # disable the cache directory
            '--exists-action=w',            # wipe existing paths
            '--disable-pip-version-check',  # don't check for new pip
            '{}=={}'.format(self.package, self.version),
        ]

    def build_wheel(self, log_file):
        """
        Call pip and attempt to build the wheel; handle killing the subprocess
        if termination is requested, and watch the clock for a build timeout.
        """
        # Ensure stdin is /dev/null; this causes anything stupid enough
        # to use input() in its setup.py to fail immediately. Also
        # ignore all output (goes to log_file instead)
        return proc.call(
            self.build_command(log_file),
            env=self.build_environment(), event=self._stopped,
            stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL)

    def build_dependencies(self, wheel):
        """
        Calculate the apt dependencies of *wheel* (which is a :class:`Wheel`
        instance representing a built wheel).
        """
        apt_cache = apt.cache.Cache()
        find_re = re.compile(r'^\s*(.*)\s=>\s(/.*)\s\(0x[0-9a-fA-F]+\)$')
        deps = defaultdict(set)
        whl_libs = set()
        dep_libs = set()
        with tempfile.TemporaryDirectory() as tempdir:
            with zipfile.ZipFile(wheel.open()) as zip_dir:
                for info in zip_dir.infolist():
                    if info.filename.endswith('.so') or '.so.' in info.filename:
                        with zip_dir.open(info) as testfile:
                            is_elf = testfile.read(4) == b'\x7FELF'
                        if is_elf:
                            whl_libs.add(zip_dir.extract(info, path=tempdir))
            for lib in whl_libs:
                out = proc.check_output(['ldd', lib],
                                        timeout=30, event=self._stopped)
                out = out.decode('ascii', 'replace')
                for line in out.splitlines():
                    match = find_re.search(line)
                    if match is not None:
                        try:
                            lib_path = Path(match.group(2))
                            # This nonsense is purely because Py3.6 introduced
                            # the "strict" parameter for Path.resolve, with a
                            # default *different* to the behaviour of Py3.5!
                            try:
                                lib_path = str(lib_path.resolve(strict=True))
                            except TypeError:
                                lib_path = str(lib_path.resolve())
                        except FileNotFoundError:
                            continue
                        dep_libs.add(lib_path)
        for lib in dep_libs:
            providers = {
                pkg.name for pkg in apt_cache
                if pkg.installed is not None
                and lib in pkg.installed_files}
            assert len(providers) <= 1
            try:
                deps['apt'].add(providers.pop())
            except KeyError:
                deps[''].add(lib)
            if self._stopped.wait(0):
                raise proc.ProcessTerminated(['dpkg', '--search', lib],
                                             self._stopped)
        wheel._dependencies = {
            tool: sorted(deps)
            for tool, deps in deps.items()
        }

    def run(self):
        """
        Attempt to build the package within the configured timeout.
        """
        with tempfile.NamedTemporaryFile('w+', dir=self._wheel_dir.name,
                                         suffix='.log',
                                         encoding='utf-8') as log_file:
            start = datetime.utcnow()
            try:
                rc = self.build_wheel(log_file)
            except Exception as exc:
                log_file.seek(0, os.SEEK_END)
                log_file.write('\n' + str(exc))
                self._status = False
            else:
                self._status = rc == 0
            finally:
                # Build duration is purely the time to build the wheel; it
                # does not include time to calculate the dependencies (which
                # users wouldn't have to do)
                self._duration = datetime.utcnow() - start
            if self._status:
                try:
                    for path in Path(self._wheel_dir.name).glob('*.whl'):
                        wheel = Wheel(path)
                        self.build_dependencies(wheel)
                        self._wheels.append(wheel)
                except (proc.TimeoutExpired, proc.ProcessTerminated) as exc:
                    self.stop()
                    log_file.seek(0, os.SEEK_END)
                    if exc.output is not None:
                        log_file.write('\n')
                        log_file.write(exc.output.decode('ascii', 'replace'))
                    log_file.write('\n')
                    log_file.write(str(exc))
                if self._stopped.wait(0):
                    self._status = False
                    self._wheels.clear()
            log_file.seek(0)
            self._output = log_file.read()
