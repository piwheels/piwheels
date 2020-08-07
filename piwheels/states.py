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
This module defines several classes which permit interested tasks to track the
state of build slaves (:class:`SlaveState`), file transfers
(:class:`TransferState`), build attempts (:class:`BuildState`), build
artifacts (:class:`FileState`) and various loggers.

.. autoclass:: FileState
    :members:

.. autoclass:: BuildState
    :members:

.. autoclass:: SlaveState
    :members:

.. autoclass:: TransferState
    :members:

.. autoclass:: DownloadState
    :members:

.. autoclass:: SearchState
    :members:

.. autoclass:: ProjectState
    :members:

.. autoclass:: JSONState
    :members:

.. autoclass:: PageState
    :members:

.. autoclass:: SlaveStats
    :members:

.. autoclass:: MasterStats
    :members:

.. autofunction:: mkdir_override_symlink
"""

import hashlib
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import namedtuple, deque

from .ranges import exclude, intersect


UTC = timezone.utc

# pylint complains about all these classes having too many attributes (and thus
# their constructors having too many arguments) and about the lack of (entirely
# pointless) docstrings on the various property getter methods. Most of the
# classes are tuple-esque; each operates as a *mostly* read-only collection of
# attributes but these classes aren't tuples because in each case there's
# usually one or two fields that can be twiddled (e.g. when a record gets
# inserted into the database, or a file transferred, etc).

# pylint: disable=too-many-instance-attributes,too-many-arguments
# pylint: disable=missing-docstring


class FileState:
    """
    Represents the state of an individual build artifact (a package file, or
    wheel) including its :attr:`filename`, :attr:`filesize`, the SHA256
    :attr:`filehash`, and various tags extracted from the build. Also tracks
    whether or not the file has been :attr:`transferred`.

    :param str filename:
        The original filename of the build artifact.

    :param int filesize:
        The size of the file in bytes.

    :param str filehash:
        The SHA256 hash of the file contents.

    :param str package_tag:
        The package tag extracted from the filename (first "-" separated
        component).

    :param str package_version_tag:
        The package version tag extracted from the filename (second "-"
        separated component).

    :param str py_version_tag:
        The python version tag extracted from the filename (third from last "-"
        separated component).

    :param str abi_tag:
        The python ABI tag extracted from the filename (second from last "-"
        separated component).

    :param str platform_tag:
        The platform tag extracted from the filename (last "-" separated
        component).

    :param set dependencies:
        The set of dependencies that are required to use this particular
        wheel.

    :param bool transferred:
        ``True`` if the file has been transferred from the build slave that
        generated it to the file server.
    """
    def __init__(self, filename, filesize, filehash, package_tag,
                 package_version_tag, py_version_tag, abi_tag, platform_tag,
                 dependencies, transferred=False):
        self._filename = filename
        self._filesize = filesize
        self._filehash = filehash
        self._package_tag = package_tag
        self._package_version_tag = package_version_tag
        self._py_version_tag = py_version_tag
        self._abi_tag = abi_tag
        self._platform_tag = platform_tag
        self._dependencies = dependencies
        self._transferred = transferred

    def as_message(self):
        """
        Convert the :class:`FileState` object into a simpler list for
        serialization and transport.
        """
        return list(self[:-1])  # never include transferred

    @classmethod
    def from_message(cls, value):
        """
        Convert the output from :meth:`as_message` back into a
        :class:`BuildState`.
        """
        return cls(*value)

    def __len__(self):
        return 10

    def __getitem__(self, index):
        return (
            self._filename,
            self._filesize,
            self._filehash,
            self._package_tag,
            self._package_version_tag,
            self._py_version_tag,
            self._abi_tag,
            self._platform_tag,
            self._dependencies,
            self._transferred,
        )[index]

    def __eq__(self, other):
        return (
            len(self) == len(other) and
            all(s == o for s, o in zip(self, other))
        )

    def __repr__(self):
        return "<FileState: {filename!r}, {filesize}Kb {transferred}>".format(
            filename=self.filename,
            filesize=self.filesize // 1024,
            transferred=('' if self.transferred else 'not ') + 'transferred'
        )

    @property
    def filename(self):
        return self._filename

    @property
    def filesize(self):
        return self._filesize

    @property
    def filehash(self):
        return self._filehash

    @property
    def package_tag(self):
        return self._package_tag

    @property
    def package_version_tag(self):
        return self._package_version_tag

    @property
    def py_version_tag(self):
        return self._py_version_tag

    @property
    def abi_tag(self):
        return self._abi_tag

    @property
    def platform_tag(self):
        return self._platform_tag

    @property
    def dependencies(self):
        return self._dependencies

    @property
    def transferred(self):
        return self._transferred

    def verified(self):
        """
        Called to set :attr:`transferred` to ``True`` after a file transfer has
        been successfully verified.
        """
        self._transferred = True


class BuildState:
    """
    Represents the state of a package build including the :attr:`package`,
    :attr:`version`, :attr:`status`, build :attr:`duration`, and all the lines
    of :attr:`output`. The :attr:`files` attribute is a mapping containing
    details of each successfully built package file.

    :param int slave_id:
        The master's identifier for the build slave.

    :param str package:
        The name of the package to build.

    :param str version:
        The version number of the package to build.

    :param str abi_tag:
        The ABI for which the build was attempted (must not be ``'none'``).

    :param bool status:
        ``True`` if the build succeeded, ``False`` if it failed.

    :param timedelta duration:
        The amount of time (in seconds) it took to complete the build.

    :param str output:
        The log output of the build.

    :param dict files:
        A mapping of filenames to :class:`FileState` objects for each artifact
        produced by the build.

    :param int build_id:
        The integer identifier generated for the build by the database
        (``None`` until the build has been inserted into the database).
    """
    def __init__(self, slave_id, package, version, abi_tag, status, duration,
                 output, files, build_id=None):
        assert abi_tag != 'none'
        self._slave_id = slave_id
        self._package = package
        self._version = version
        self._abi_tag = abi_tag
        self._status = status
        self._duration = duration
        self._output = output
        self._files = files
        self._build_id = build_id

    def as_message(self):
        """
        Convert the :class:`BuildState`, and its nested :class:`FileState`
        objects into simpler lists for serialization and transport.
        """
        # XXX Horrid hack: we only sort the file entries to make tests
        # predictable
        return [
            value if index != 7 else
            [value[filename].as_message() for filename in sorted(value)]
            for index, value in enumerate(self[:-1])  # never include build_id
        ]

    @classmethod
    def from_message(cls, value):
        """
        Convert the output from :meth:`as_message` back into a
        :class:`BuildState`.
        """
        value = list(value)
        value[7] = [FileState.from_message(f) for f in value[7]]
        value[7] = {f.filename: f for f in value[7]}
        return cls(*value)

    def __len__(self):
        return 9

    def __getitem__(self, index):
        return [
            self._slave_id,
            self._package,
            self._version,
            self._abi_tag,
            self._status,
            self._duration,
            self._output,
            self._files,
            self._build_id,
        ][index]

    def __setitem__(self, index, value):
        if index == 3:
            self._abi_tag = value
        else:
            raise AttributeError('index %d is immutable' % index)

    def __eq__(self, other):
        return (
            len(self) == len(other) and
            all(s == o for s, o in zip(self, other))
        )

    def __repr__(self):
        return (
            "<BuildState: id={build_id!r}, pkg={package} {version}, "
            "abi_tag={abi_tag}, {status}>".
            format(
                build_id=self.build_id, package=self.package,
                version=self.version, abi_tag=self.abi_tag, status=(
                    'failed' if not self.status else
                    '{count} files'.format(count=len(self.files))
                )
            )
        )

    @property
    def slave_id(self):
        return self._slave_id

    @property
    def build_id(self):
        return self._build_id

    @property
    def package(self):
        return self._package

    @property
    def version(self):
        return self._version

    @property
    def abi_tag(self):
        return self._abi_tag

    @abi_tag.setter
    def abi_tag(self, value):
        self._abi_tag = value

    @property
    def status(self):
        return self._status

    @property
    def duration(self):
        return self._duration

    @property
    def output(self):
        return self._output

    @property
    def files(self):
        """
        A mapping of filename to :class:`FileState` instances.
        """
        return self._files

    @property
    def transfers_done(self):
        """
        Returns ``True`` if all files have been transferred.
        """
        return all(f.transferred for f in self._files.values())

    @property
    def next_file(self):
        """
        Returns the filename of the next file that needs transferring or
        ``None`` if all files have been transferred.
        """
        # XXX This is a horrid hack; the ONLY reason we sort here is to make
        # certain tests predictable
        for filename, f in sorted(self._files.items()):
            if not f.transferred:
                return filename
        return None

    def logged(self, build_id):
        """
        Called to fill in the build's ID in the backend database.
        """
        self._build_id = build_id


class SlaveState:
    """
    Tracks the state of a build slave. The master updates this state with each
    request and reply sent to and received from the slave, and this class in
    turn manages the associated :class:`BuildState` (accessible from
    :attr:`build`) and :class:`TransferState` (accessible from
    :attr:`transfer`). The class also tracks the time a request was last seen
    from the build slave, and includes a :meth:`kill` method.

    :param bytes address:
        The slave's ephemeral 0MQ address.

        .. note::

            This is *not* the slave's IP address; it's a unique identifier
            generated on connection to the master's ROUTER socket. It will be
            different each time the slave re-connects (due to timeout, reboot,
            etc).

    :param int timeout:
        The number of seconds after which any build will be considered to have
        timed out (and the slave will be assumed crashed).

    :param str native_py_version:
        The slave's native Python version.

    :param str native_abi:
        The slave's native Python ABI.

    :param str native_platform:
        The slave's native platform.

    :param str label:
        A label representing the slave.
    """
    counter = 0
    status_queue = None

    def __init__(self, address, build_timeout, busy_timeout, native_py_version,
                 native_abi, native_platform, label, os_name, os_version,
                 board_revision, board_serial):
        SlaveState.counter += 1
        self._address = address
        self._slave_id = SlaveState.counter
        self._build_timeout = build_timeout
        self._busy_timeout = busy_timeout
        self._native_py_version = native_py_version
        self._native_abi = native_abi
        self._native_platform = native_platform
        self._label = label
        self._os_name = os_name
        self._os_version = os_version
        self._board_revision = board_revision
        self._board_serial = board_serial
        self._first_seen = self._last_seen = datetime.now(tz=UTC)
        self._request = None
        self._reply = None
        self._build = None
        self._stats = deque(maxlen=100)
        self._clock_skew = None
        self._killed = False
        self._skipped = False
        self._paused = False

    def __repr__(self):
        return (
            "<SlaveState: id={slave_id}, label={label}, "
            "last_seen={last_seen}, last_reply={reply}, {alive}>".format(
                slave_id=self.slave_id,
                label=self.label,
                last_seen=datetime.now(tz=UTC) - self.last_seen,
                reply='none' if self.reply is None else self.reply[0],
                alive='killed'
                if self.killed else 'expired'
                if self.expired else 'alive'
            )
        )

    def hello(self):
        SlaveState.status_queue.send_msg(
            'SLAVE', [
                self._slave_id, self._first_seen, 'HELLO', [
                    self._build_timeout, self._busy_timeout,
                    self._native_py_version, self._native_abi,
                    self._native_platform, self._label, self._os_name,
                    self._os_version, self._board_revision, self._board_serial,
                ]
            ]
        )
        # Replay the history stats and the last reply for the sake of monitors
        # that have just connected to the master
        for stat in self._stats:
            SlaveState.status_queue.send_msg(
                'SLAVE', [self._slave_id, self._last_seen,
                          'STATS', stat.as_message()])
        msg, data = self._reply
        SlaveState.status_queue.send_msg(
            'SLAVE', [self._slave_id, self._last_seen, msg, data])

    def kill(self):
        self._killed = True

    def skip(self):
        self._skipped = True

    def sleep(self):
        self._paused = True

    def wake(self):
        self._killed, self._skipped, self._paused = False, False, False

    @property
    def killed(self):
        return self._killed

    @property
    def skipped(self):
        return self._skipped

    @property
    def paused(self):
        return self._paused

    @property
    def address(self):
        return self._address

    @property
    def slave_id(self):
        return self._slave_id

    @property
    def label(self):
        return self._label

    @property
    def build_timeout(self):
        return self._build_timeout

    @property
    def busy_timeout(self):
        return self._busy_timeout

    @property
    def native_platform(self):
        return self._native_platform

    @property
    def native_abi(self):
        return self._native_abi

    @property
    def native_py_version(self):
        return self._native_py_version

    @property
    def os_name(self):
        return self._os_name

    @property
    def os_version(self):
        return self._os_version

    @property
    def board_revision(self):
        return self._board_revision

    @property
    def board_serial(self):
        return self._board_serial

    @property
    def first_seen(self):
        return self._first_seen

    @property
    def last_seen(self):
        return self._last_seen

    @property
    def expired(self):
        return (datetime.now(tz=UTC) - self._last_seen) > self._busy_timeout

    @property
    def build(self):
        return self._build

    @property
    def stats(self):
        return self._stats

    @property
    def clock_skew(self):
        return self._clock_skew

    @property
    def request(self):
        return self._request

    @request.setter
    def request(self, value):
        self._last_seen = datetime.now(tz=UTC)
        self._request = value
        msg, data = value
        if msg == 'BUILT':
            if self._reply[0] == 'BUILD':
                try:
                    status, duration, output, files = data
                    files = [FileState.from_message(f) for f in files]
                    msg, (package, version) = self._reply
                    self._build = BuildState(
                        self._slave_id, package, version,
                        self.native_abi, status, duration, output, files={
                            f.filename: f for f in files
                        }
                    )
                except (ValueError, TypeError):
                    logging.error('Invalid BUILT data: %r', data)
                    self._build = None
            else:
                logging.error('Invalid BUILT after %s', self._reply[0])
                self._build = None
        elif msg in ('IDLE', 'BUSY'):
            self._stats.append(SlaveStats.from_message(data))
            self._clock_skew = self._last_seen - self._stats[-1].timestamp
            SlaveState.status_queue.send_msg(
                'SLAVE', [self._slave_id, self._last_seen, 'STATS', data])

    @property
    def reply(self):
        return self._reply

    @reply.setter
    def reply(self, value):
        msg, data = value
        if msg != 'CONT':
            self._reply = value
        if msg == 'DONE':
            self._build = None
            self._skipped = False
        if msg == 'ACK':
            self.hello()
        elif msg != 'CONT':
            SlaveState.status_queue.send_msg(
                'SLAVE', [self._slave_id, self._last_seen, msg, data])


class TransferState:
    """
    Tracks the state of a file transfer. All file transfers are held in
    temporary locations until :meth:`verify` indicates the transfer was
    successful, at which point they are atomically renamed into their final
    location.

    The state is intimately tied to the file transfer protocol and includes
    methods to write a recevied :meth:`chunk`, and to determine the next chunk
    to :meth:`fetch`, as well as a property to determine when the transfer is
    :attr:`done`.

    :param str slave_id:
        The ID number of the slave which built the file.

    :param FileState file_state:
        The details of the file to be transferred (filename, size, hash, etc.)
    """

    chunk_size = 65536
    pipeline_size = 10
    output_path = Path('.')

    def __init__(self, slave_id, file_state):
        self._slave_id = slave_id
        self._file_state = file_state
        try:
            (self.output_path / 'simple').mkdir()
        except FileExistsError:
            pass
        self._file = tempfile.NamedTemporaryFile(
            dir=str(self.output_path / 'simple'), delete=False)
        self._file.seek(self._file_state.filesize)
        self._file.truncate()
        # See 0MQ guide's File Transfers section for more on the credit-driven
        # nature of this interaction
        self._credit = 0
        # _offset is the position that we will next return when the fetch()
        # method is called (or rather, it's the minimum position we'll return)
        # whilst _map is a sorted list of ranges indicating which bytes of the
        # file we have yet to received; this is manipulated by chunk()
        self._offset = 0
        self._map = [range(self._file_state.filesize)]
        self.reset_credit()

    def __repr__(self):
        return "<TransferState: offset={offset} map={_map}>".format(
            offset=self._offset, _map=self._map)

    @property
    def slave_id(self):
        return self._slave_id

    @property
    def file_state(self):
        return self._file_state

    @property
    def done(self):
        return not self._map

    def fetch(self):
        if self._credit:
            self._credit -= 1
            assert self._credit >= 0
            fetch_range = range(self._offset, self._offset + self.chunk_size)
            while True:
                for map_range in self._map:
                    result = intersect(map_range, fetch_range)
                    if result:
                        self._offset = result.stop
                        return result
                try:
                    fetch_range = range(self._map[0].start,
                                        self._map[0].start + self.chunk_size)
                except IndexError:
                    return None

    def chunk(self, offset, data):
        # XXX Check we actually still need this chunk? I/O is expensive after all
        self._file.seek(offset)
        self._file.write(data)
        self._map = list(exclude(self._map, range(offset, offset + len(data))))
        if not self._map:
            self._credit = 0
        else:
            self._credit += 1

    def reset_credit(self):
        self._credit = max(1, min(self.pipeline_size,
                           self._file_state.filesize // self.chunk_size))

    def verify(self):
        # XXX Would be nicer to construct the hash from the transferred chunks
        # with a tree, but this potentially costs quite a bit of memory
        self._file.seek(0)
        body = hashlib.sha256()
        while True:
            buf = self._file.read(self.chunk_size)
            if buf:
                body.update(buf)
            else:
                break
        size = self._file.tell()
        self._file.close()
        if size != self._file_state.filesize:
            raise IOError('wrong size for transfer at %s' % self._file.name)
        if body.hexdigest().lower() != self._file_state.filehash:
            raise IOError('failed to verify transfer at %s' % self._file.name)

    def commit(self, package):
        tmp_file = Path(self._file.name)
        tmp_file.chmod(0o644)
        pkg_dir = tmp_file.with_name(package)
        mkdir_override_symlink(pkg_dir)
        final_name = pkg_dir / self._file_state.filename
        # rename() will replace any existing file *or* symlink. This means in
        # the case of an actual armv6 build being uploaded, it will (rightly)
        # clobber any symlink currently in place
        tmp_file.rename(final_name)
        if self._file_state.platform_tag == 'linux_armv7l':
            # NOTE: dirty hack to symlink the armv7 wheel to the armv6 name;
            # the slave_driver task expects us to have done this
            arm6_name = final_name.with_name(
                final_name.name[:-16] + 'linux_armv6l.whl')
            try:
                arm6_name.symlink_to(final_name.name)
            except FileExistsError:
                # If the symlink already exists, or if a file with the same
                # name already exists, ignore the error. In particular, if an
                # actual file exists (a specific armv6 build) we must NOT
                # overwrite it
                pass
        self._file_state.verified()

    def rollback(self):
        Path(self._file.name).unlink()


class MasterStats(namedtuple('MasterStats', (
    'timestamp',
    'packages_built',
    'builds_last_hour',
    'builds_time',
    'builds_size',
    'builds_pending',
    'new_last_hour',
    'files_count',
    'downloads_last_hour',
    'downloads_last_month',
    'downloads_all',
    'disk_size',
    'disk_free',
    'mem_size',
    'mem_free',
    'swap_size',
    'swap_free',
    'load_average',
    'cpu_temp',
))):
    __slots__ = ()

    def as_message(self):
        return list(self)

    @classmethod
    def from_message(cls, value):
        return cls(*value)


class SlaveStats(namedtuple('SlaveStats', (
    'timestamp',
    'disk_size',
    'disk_free',
    'mem_size',
    'mem_free',
    'swap_size',
    'swap_free',
    'load_average',
    'cpu_temp',
))):
    __slots__ = ()

    def as_message(self):
        return list(self)

    @classmethod
    def from_message(cls, value):
        return cls(*value)


class DownloadState(namedtuple('DownloadState', (
    'filename',
    'host',
    'timestamp',
    'arch',
    'distro_name',
    'distro_version',
    'os_name',
    'os_version',
    'py_name',
    'py_version',
    'installer_name',
    'installer_version',
    'setuptools_version',
))):
    """
    Represents the state of the log entry for a download of a package wheel
    file, including its :attr:`filename`, the user's :attr:`host` IP, access
    :attr:`timestamp` and information about the operating system and installer.

    :param str filename:
        The filename of the downloaded wheel file.

    :param host:
        The hostname or IP address of the user.

    :param datetime.datetime timestamp:
        The timestamp at which the file was downloaded.

    :type arch: str or None
    :param str or None arch:
        The architecture of the user's computer system (usually armv6 or
        armv7).

    :type distro_name: str or None
    :param distro_name:
        The user's operating system distribution name (e.g. Raspbian).

    :type distro_version: str or None
    :param distro_version:
        The version of the user's operating system distribution.

    :type os_name: str or None
    :param os_name:
        The name of the user's operating system (e.g. Linux).

    :type os_version: str or None
    :param os_version:
        The version of the user's operating system (e.g. Linux kernel version).

    :type py_name: str or None
    :param py_name:
        The Python implementation used (e.g. CPython).

    :type py_version: str or None
    :param py_version:
        The Python version used (e.g. 3.7.3).

    :type installer_name: str or None
    :param installer_name:
        The name of the tool used to install the file (e.g. pip).

    :type installer_version: str or None
    :param installer_version:
        The version of the tool (e.g. pip) used to install the file.

    :type setuptools_version: str or None
    :param setuptools_version:
        The version of setuptools used.
    """
    __slots__ = ()

    def as_message(self):
        return list(self)

    @classmethod
    def from_message(cls, value):
        return cls(*value)


class SearchState(namedtuple('SearchState', (
    'package',
    'host',
    'timestamp',
    'arch',
    'distro_name',
    'distro_version',
    'os_name',
    'os_version',
    'py_name',
    'py_version',
    'installer_name',
    'installer_version',
    'setuptools_version',
))):
    """
    Represents the state of the log entry for an instance of a package search,
    including the :attr:`package` name, user's :attr:`host` IP, access
    :attr:`timestamp` and information about the operating system and installer.

    :param str package:
        The name of the package searched for.

    :param str host:
        The hostname or IP address of the user.

    :param datetime.datetime timestamp:
        The timestamp at which the search occurred.

    :type arch: str or None
    :param arch:
        The architecture of the user's computer system (usually armv6 or armv7).

    :type distro_name: str or None
    :param distro_name:
        The user's operating system distribution name (e.g. Raspbian).

    :type distro_version: str or None
    :param distro_version:
        The version of the user's operating system distribution.

    :type os_name: str or None
    :param os_name:
        The name of the user's operating system (e.g. Linux).

    :type os_version: str or None
    :param os_version:
        The version of the user's operating system (e.g. Linux kernel version).

    :type py_name: str or None
    :param py_name:
        The Python implementation used (e.g. CPython).

    :type py_version: str or None
    :param py_version:
        The Python version used (e.g. 3.7.3).

    :type installer_name: str or None
    :param installer_name:
        The name of the tool used (e.g. pip).

    :type installer_version: str or None
    :param installer_version:
        The version of the tool (e.g. pip) used.

    :type setuptools_version: str or None
    :param setuptools_version:
        The version of setuptools used.
    """
    __slots__ = ()

    def as_message(self):
        return list(self)

    @classmethod
    def from_message(cls, value):
        return cls(*value)


class ProjectState(namedtuple('ProjectState', (
    'package',
    'host',
    'timestamp',
    'user_agent',
))):
    """
    Represents the state of the log entry for an instance of project page hit,
    including the :attr:`page` name, the user's :attr:`host` IP, access
    :attr:`timestamp` and the user's :attr:`user_agent`.

    :param str package:
        The name of the package searched for.

    :param str host:
        The hostname or IP address of the user.

    :type timestamp: :class:`datetime.datetime`
    :param timestamp:
        The timestamp at which the page was accessed.

    :type host: str
    :param str user_agent:
        The user agent of the page request.
    """
    __slots__ = ()

    def as_message(self):
        return list(self)

    @classmethod
    def from_message(cls, value):
        return cls(*value)


class JSONState(namedtuple('JSONState', (
    'package',
    'host',
    'timestamp',
    'user_agent',
))):
    """
    Represents the state of the log entry for an instance of project JSON
    download, including the :attr:`page` name, the user's :attr:`host` IP,
    access :attr:`timestamp` and the user's :attr:`user_agent`.

    :param str package:
        The name of the package whose JSON file was accessed.

    :param str host:
        The hostname or IP address of the user.

    :param datetime.datetime timestamp:
        The timestamp at which the page was accessed.

    :param str user_agent:
        The user agent of the request.
    """
    __slots__ = ()

    def as_message(self):
        return list(self)

    @classmethod
    def from_message(cls, value):
        return cls(*value)


class PageState(namedtuple('PageState', (
    'page',
    'host',
    'timestamp',
    'user_agent',
))):
    """
    Represents the state of the log entry for an instance of web page hit,
    including the :attr:`page` name, the user's :attr:`host` IP, access
    :attr:`timestamp` and the user's :attr:`user_agent`.

    :param str page:
        The name of the page accessed.

    :param str host:
        The IP address of the user.

    :param datetime.datetime timestamp:
        The timestamp at which the page was accessed.

    :param str user_agent:
        The user agent of the page request.
    """
    __slots__ = ()

    def as_message(self):
        return list(self)

    @classmethod
    def from_message(cls, value):
        return cls(*value)


def mkdir_override_symlink(pkg_dir):
    """
    Make *pkg_dir*, replacing any existing symlink in its place. See the
    notes in :meth:`TheScribe.write_package_index` for more information.
    """
    # There is a tiny possibility of a race here between two threads wanting
    # to replace a symlinked dir with a "real" dir, hence the loop below
    while True:
        try:
            pkg_dir.mkdir()
        except FileExistsError:
            if pkg_dir.is_symlink():
                # There is another tiny possibility that, in racing another
                # thread replacing the symlinked dir, the other thread wins
                # and this unlink fails because it's now a "real" dir
                try:
                    pkg_dir.unlink()
                    continue
                except IsADirectoryError:
                    pass
        break
