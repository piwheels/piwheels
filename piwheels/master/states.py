"""
This module defines several classes which permit interested tasks to track the
state of build slaves (:class:`SlaveState`), file transfers
(:class:`TransferState`), build attempts (:class:`BuildState`) and build
artifacts (:class:`FileState`).
"""

import hashlib
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from .ranges import exclude, intersect

# pylint complains about all these classes having too many attributes (and thus
# their constructors having too many arguments) and about the lack of (entirely
# pointless) docstrings on the various property getter methods. Most of the
# classes are tuple-esque; each operates as *mostly* read-only collection of
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

    :param bool transferred:
        ``True`` if the file has been transferred from the build slave that
        generated it to the file server.
    """
    def __init__(self, filename, filesize, filehash, package_tag,
                 package_version_tag, py_version_tag, abi_tag, platform_tag,
                 transferred=False):
        self._filename = filename
        self._filesize = filesize
        self._filehash = filehash
        self._package_tag = package_tag
        self._package_version_tag = package_version_tag
        self._py_version_tag = py_version_tag
        self._abi_tag = abi_tag
        self._platform_tag = platform_tag
        self._transferred = transferred

    def __len__(self):
        return 9

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
            self._transferred,
        )[index]

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

    :param bool status:
        ``True`` if the build succeeded, ``False`` if it failed.

    :param datetime.timedelta duration:
        The amount of time it took to complete the build.

    :param str output:
        The log output of the build.

    :param dict files:
        A mapping of filenames to :class:`FileState` objects for each artifact
        produced by the build.

    :param int build_id:
        The integer identifier generated for the build by the database
        (``None`` until the build has been inserted into the database).
    """
    def __init__(self, slave_id, package, version, status, duration, output,
                 files, build_id=None):
        self._slave_id = slave_id
        self._package = package
        self._version = version
        self._status = status
        self._duration = duration
        self._output = output
        self._files = files
        self._build_id = build_id

    def __len__(self):
        return 8

    def __getitem__(self, index):
        return [
            self._slave_id,
            self._package,
            self._version,
            self._status,
            self._duration,
            self._output,
            self._files,
            self._build_id,
        ][index]

    def __repr__(self):
        return (
            "<BuildState: id={build_id!r}, pkg={package} {version}, {status}>".
            format(
                build_id=self.build_id, package=self.package,
                version=self.version, status=(
                    'failed' if not self.status else
                    '{count} files'.format(count=len(self.files))
                )
            )
        )

    @classmethod
    def from_db(cls, db, build_id):
        """
        Construct an instance by querying the database for the specified
        *build_id*.

        :param Database db:
            A :class:`Database` instance to query.

        :param int build_id:
            The integer identifier of an attempted build.
        """
        for brec in db.get_build(build_id):
            return BuildState(
                brec.built_by,
                brec.package,
                brec.version,
                brec.status,
                brec.duration,
                brec.output,
                {
                    frec.filename: FileState(
                        frec.filename,
                        frec.filesize,
                        frec.filehash,
                        frec.package_tag,
                        frec.package_version_tag,
                        frec.py_version_tag,
                        frec.abi_tag,
                        frec.platform_tag,
                        transferred=True
                    )
                    for frec in db.get_files(build_id)
                },
                build_id
            )
        raise ValueError('Unknown build id %d' % build_id)

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
        for filename, f in self._files.items():
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
    Tracks the state of a build slave. The master updates this state which each
    request and reply sent to and received from the slave, and this class in
    turn manages the associated :class:`BuildState` (accessible from
    :attr:`build`) and :class:`TransferState` (accessible from
    :attr:`transfer`). The class also tracks the time a request was last seen
    from the build slave, and includes a :meth:`kill` method.
    """
    counter = 0
    status_queue = None

    def __init__(self, address, timeout, native_py_version, native_abi,
                 native_platform):
        SlaveState.counter += 1
        self._address = address
        self._slave_id = SlaveState.counter
        self._timeout = timedelta(seconds=timeout)
        self._native_py_version = native_py_version
        self._native_abi = native_abi
        self._native_platform = native_platform
        self._first_seen = datetime.utcnow()
        self._last_seen = None
        self._request = None
        self._reply = None
        self._build = None
        self._terminated = False

    def __repr__(self):
        return (
            "<SlaveState: id={slave_id}, last_seen={last_seen}, "
            "last_reply={reply}, {alive}>".format(
                slave_id=self.slave_id,
                last_seen=datetime.utcnow() - self.last_seen,
                reply='none' if self.reply is None else self.reply[0],
                alive='killed' if self.terminated else 'alive'
            )
        )

    def hello(self):
        SlaveState.status_queue.send_pyobj(
            [self._slave_id, self._first_seen, 'HELLO',
             self._native_py_version, self._native_abi, self._native_platform])
        if self._reply is not None and self._reply[0] != 'HELLO':
            SlaveState.status_queue.send_pyobj(
                [self._slave_id, self._last_seen] + self._reply)

    def kill(self):
        self._terminated = True

    @property
    def terminated(self):
        return self._terminated

    @property
    def address(self):
        return self._address

    @property
    def slave_id(self):
        return self._slave_id

    @property
    def timeout(self):
        return self._timeout

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
    def first_seen(self):
        return self._first_seen

    @property
    def last_seen(self):
        return self._last_seen

    @property
    def build(self):
        return self._build

    @property
    def request(self):
        return self._request

    @request.setter
    def request(self, value):
        self._last_seen = datetime.utcnow()
        self._request = value
        if value[0] == 'BUILT':
            self._build = BuildState(self._slave_id, *value[1:6], files={
                filename: FileState(filename, *filestate)
                for filename, filestate in value[-1].items()
            })

    @property
    def reply(self):
        return self._reply

    @reply.setter
    def reply(self, value):
        self._reply = value
        if value[0] == 'DONE':
            self._build = None
        if value[0] == 'HELLO':
            self.hello()
        else:
            SlaveState.status_queue.send_pyobj(
                [self._slave_id, self._last_seen] + value)


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
    """

    chunk_size = 65536
    pipeline_size = 10
    output_path = Path('.')

    def __init__(self, slave_id, file_state):
        self._slave_id = slave_id
        self._file_state = file_state
        self._file = tempfile.NamedTemporaryFile(
            dir=str(self.output_path / 'simple'), delete=False)
        self._file.seek(self._file_state.filesize)
        self._file.truncate()
        # See 0MQ guide's File Transfers section for more on the credit-driven
        # nature of this interaction
        self._credit = min(self.pipeline_size,
                           self._file_state.filesize // self.chunk_size)
        self._credit = max(1, self._credit)
        # _offset is the position that we will next return when the fetch()
        # method is called (or rather, it's the minimum position we'll return)
        # whilst _map is a sorted list of ranges indicating which bytes of the
        # file we have yet to received; this is manipulated by chunk()
        self._offset = 0
        self._map = [range(self._file_state.filesize)]

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
                    elif map_range.start > fetch_range.start:
                        fetch_range = range(map_range.start,
                                            map_range.start + self.chunk_size)
                try:
                    fetch_range = range(self._map[0].start,
                                        self._map[0].start + self.chunk_size)
                except IndexError:
                    return None

    def chunk(self, offset, data):
        self._file.seek(offset)
        self._file.write(data)
        self._map = list(exclude(self._map, range(offset, offset + len(data))))
        if not self._map:
            self._credit = 0
        else:
            self._credit += 1

    def reset_credit(self):
        if self._credit == 0:
            # NOTE: We don't bother with the filesize here; if we're dropping
            # that many packets we should max out "in-flight" packets for this
            # transfer anyway
            self._credit = self.pipeline_size
        else:
            logging.warning('Transfer still has credit; no need for reset')

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
        self._file.close()
        if body.hexdigest().lower() != self._file_state.filehash:
            raise IOError('failed to verify transfer at %s' % self._file.name)

    def commit(self, package):
        tmp_file = Path(self._file.name)
        tmp_file.chmod(0o644)
        pkg_dir = tmp_file.with_name(package)
        try:
            pkg_dir.mkdir()
        except FileExistsError:
            # See notes in IndexScribe.write_package_index
            if pkg_dir.is_symlink():
                pkg_dir.unlink()
                pkg_dir.mkdir()
        final_name = pkg_dir / self._file_state.filename
        tmp_file.rename(final_name)
        if self._file_state.platform_tag == 'linux_armv7l':
            # NOTE: dirty hack to symlink the armv7 wheel to the armv6 name;
            # the slave_driver task expects us to have done this
            arm6_name = final_name.with_name(
                final_name.name[:-16] + 'linux_armv6l.whl')
            try:
                arm6_name.symlink_to(final_name.name)
            except FileExistsError:
                pass
        self._file_state.verified()

    def rollback(self):
        Path(self._file.name).unlink()
