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

.. autoclass:: PiWheelsPackage
    :members:

.. autoclass:: PiWheelsBuilder
    :members:
"""

import io
import os
import json
import tempfile
import zipfile
import hashlib
import resource
from subprocess import Popen, DEVNULL, TimeoutExpired
from time import time
from pathlib import Path


class PiWheelsPackage:
    """
    Records the state of a build artifact, i.e. a wheel package. The filename
    is deconstructed into the fields specified by :pep:`425`.

    :param pathlib.Path path:
        The path to the wheel on the local filesystem.
    """
    def __init__(self, path):
        self.wheel_file = path
        self._filesize = path.stat().st_size
        self._filehash = None
        self._metadata = None
        self._parts = list(path.stem.split('-'))
        # Fix up retired tags (noabi->none)
        if self._parts[-2] == 'noabi':
            self._parts[-2] = 'none'

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

    def open(self, mode='rb'):
        """
        Open the wheel in binary mode and return the open file object.
        """
        return self.wheel_file.open(mode)

    @property
    def metadata(self):
        """
        Return the contents of the :file:`metadata.json` file inside the wheel.
        """
        if self._metadata is None:
            with zipfile.ZipFile(self.wheel_file.open('rb')) as wheel:
                filename = (
                    '{self.package_tag}-'
                    '{self.package_version_tag}.dist-info/'
                    'metadata.json'.format(self=self)
                )
                with wheel.open(filename) as metadata:
                    wrapper = io.TextIOWrapper(metadata, encoding='utf-8')
                    self._metadata = json.load(wrapper)
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
                    timeout = 5000
                req, *args = queue.recv_multipart()
                if req == b'DONE':
                    return
                elif req == b'FETCH':
                    offset, size = args
                    f.seek(int(offset))
                    queue.send_multipart([b'CHUNK', offset, f.read(int(size))])


class PiWheelsBuilder:
    """
    Class responsible for building wheels for a given *version* of a *package*.

    :param str package:
        The name of the package to attempt to build wheels for.

    :param str version:
        The version of the package to attempt to build.
    """
    def __init__(self, package, version):
        self.wheel_dir = None
        self.package = package
        self.version = version
        self.duration = None
        self.output = ''
        self.files = []
        self.status = False

    @property
    def as_message(self):
        """
        Return the state as a list suitable for use in several protocol
        messages (specifically those used by :program:`piw-slave` and
        :program:`piw-import`).
        """
        return [
            self.package, self.version, self.status, self.duration,
            self.output, {
                pkg.filename: (
                    pkg.filesize,
                    pkg.filehash,
                    pkg.package_tag,
                    pkg.package_version_tag,
                    pkg.py_version_tag,
                    pkg.abi_tag,
                    pkg.platform_tag,
                )
                for pkg in self.files
            }
        ]

    def build(self, timeout=None, pypi_index='https://pypi.python.org/simple'):
        """
        Attempt to build the package within the specified *timeout*.

        :param float timeout:
            The number of seconds to wait for ``pip`` to finish before raising
            :exc:`subprocess.TimeoutExpired`.

        :param str pypi_index:
            The URL of the :pep:`503` compliant repository from which to fetch
            packages for building.
        """
        self.wheel_dir = tempfile.TemporaryDirectory()
        with tempfile.NamedTemporaryFile('w+', dir=self.wheel_dir.name,
                                         suffix='.log',
                                         encoding='utf-8') as log_file:
            env = os.environ.copy()
            # Force git to fail if it needs to prompt for anything (a
            # disturbing minority of packages try to run git clone during their
            # setup.py)
            env['GIT_ALLOW_PROTOCOL'] = 'file'
            args = [
                'pip3', 'wheel',
                '--index-url={}'.format(pypi_index),
                '--wheel-dir={}'.format(self.wheel_dir.name),
                '--log={}'.format(log_file.name),
                '--no-deps',                    # don't build dependencies
                '--no-cache-dir',               # disable the cache directory
                '--exists-action=w',            # wipe existing paths
                '--disable-pip-version-check',  # don't check for new pip
                '{}=={}'.format(self.package, self.version),
            ]
            # Limit the data segment of this process (and all children) to 1Gb
            # in size. This doesn't guarantee that stuff can't grow until it
            # crashes (multiple children can violate the limit together while
            # obeying it individually), but it should reduce the incidence of
            # huge C++ compiles killing the build slaves
            resource.setrlimit(resource.RLIMIT_DATA, (1024**3, 1024**3))
            start = time()
            try:
                proc = Popen(
                    args,
                    stdin=DEVNULL,     # ensure stdin is /dev/null; this causes
                                       # anything stupid enough to use input()
                                       # in its setup.py to fail immediately
                    stdout=DEVNULL,    # also ignore all output
                    stderr=DEVNULL,
                    env=env
                )
                # If the build times out attempt to kill it with SIGTERM; if
                # that hasn't worked after 10 seconds, resort to SIGKILL
                try:
                    proc.wait(timeout)
                except TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(10)
                    except TimeoutExpired:
                        proc.kill()
                    raise
            except Exception as exc:
                error = exc
            else:
                error = None
            self.duration = time() - start
            self.status = proc.returncode == 0
            if error is not None:
                log_file.seek(0, os.SEEK_END)
                log_file.write('\n' + str(error))
            log_file.seek(0)
            self.output = log_file.read()

            if self.status:
                for path in Path(self.wheel_dir.name).glob('*.whl'):
                    self.files.append(PiWheelsPackage(path))
            return self.status

    def clean(self):
        """
        Remove the temporary build directory and all its contents.
        """
        if self.wheel_dir is not None:
            self.wheel_dir.cleanup()
            self.wheel_dir = None
