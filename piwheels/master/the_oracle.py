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
Defines :class:`TheOracle` task and the :class:`DbClient` RPC class for talking
to it.

.. autoclass:: TheOracle
    :members:

.. autoclass:: DbClient
    :members:
"""

import pickle

import zmq
import zmq.error

from .. import const, protocols, transport, tasks
from .states import BuildState, DownloadState
from .db import Database, ProjectVersionsRow, ProjectFilesRow


class TheOracle(tasks.Task):
    """
    This task provides an RPC-like interface to the database; it handles
    requests such as registering a new package, version, or build, and
    answering queries about the hashes of files. The primary clients of this
    class are :class:`~.slave_driver.SlaveDriver`,
    :class:`~.the_scribe.TheScribe`, and :class:`~.cloud_gazer.CloudGazer`.

    Note that because database requests are notoriously variable in length the
    client RPC class (:class:`DbClient`) doesn't *directly* talk to
    :class:`TheOracle`. Rather, multiple instances of :class:`TheOracle` are
    spawned and :class:`~.seraph.Seraph` sits in front of these acting as a
    simple load-sharing router for the RPC clients.
    """
    name = 'master.the_oracle'
    instance = 0

    def __init__(self, config):
        TheOracle.instance += 1
        self.name = '%s_%d' % (TheOracle.name, TheOracle.instance)
        super().__init__(config)
        self.db = Database(config.dsn)
        db_queue = self.ctx.socket(zmq.REQ, protocol=protocols.the_oracle)
        db_queue.hwm = 10
        db_queue.connect(const.ORACLE_QUEUE)
        self.register(db_queue, self.handle_db_request)
        db_queue.send(b'READY')

    def close(self):
        self.db.close()
        super().close()

    def handle_db_request(self, queue):
        """
        Handle incoming requests from :class:`DbClient` instances.
        """
        try:
            addr, empty, buf = queue.recv_multipart()
        except ValueError as exc:
            self.logger.error(str(exc))
            # REQ sockets *must* send a reply even when stuff goes wrong
            # otherwise the send/recv cycle that REQ/REP depends upon breaks.
            # Here we've got a badly formed request and we can't even get the
            # reply address, so we just make one up (empty). This message
            # won't go anywhere (bogus address) but that doesn't matter as we
            # just want to get the socket back to receiving state
            addr, msg, data = b'', 'ERROR', str(exc)
        else:
            try:
                msg, data = queue.load_msg(buf)
            except IOError as exc:
                self.logger.error(str(exc))
                msg, data = 'ERROR', str(exc)
            else:
                try:
                    handler = {
                        'ALLPKGS':     lambda: self.do_allpkgs(),
                        'ALLVERS':     lambda: self.do_allvers(),
                        'NEWPKG':      lambda: self.do_newpkg(*data),
                        'NEWVER':      lambda: self.do_newver(*data),
                        'SKIPPKG':     lambda: self.do_skippkg(*data),
                        'SKIPVER':     lambda: self.do_skipver(*data),
                        'LOGDOWNLOAD': lambda: self.do_logdownload(data),
                        'LOGBUILD':    lambda: self.do_logbuild(data),
                        'DELBUILD':    lambda: self.do_delbuild(*data),
                        'PKGFILES':    lambda: self.do_pkgfiles(data),
                        'PROJVERS':    lambda: self.do_projvers(data),
                        'PROJFILES':   lambda: self.do_projfiles(data),
                        'VERFILES':    lambda: self.do_verfiles(*data),
                        'GETSKIP':     lambda: self.do_getskip(*data),
                        'PKGEXISTS':   lambda: self.do_pkgexists(data),
                        'VEREXISTS':   lambda: self.do_verexists(*data),
                        'GETABIS':     lambda: self.do_getabis(),
                        'GETPYPI':     lambda: self.do_getpypi(),
                        'SETPYPI':     lambda: self.do_setpypi(data),
                        'GETSTATS':    lambda: self.do_getstats(),
                        'GETDL':       lambda: self.do_getdl(),
                        'FILEDEPS':    lambda: self.do_filedeps(data),
                    }[msg]
                    result = handler()
                except Exception as exc:
                    self.logger.error('Error handling db request: %s', msg)
                    msg, data = 'ERROR', str(exc)
                else:
                    msg, data = 'OK', result
        queue.send_addr_msg(addr, msg, data)  # see note above

    def do_allpkgs(self):
        """
        Handler for "ALLPKGS" message, sent by :class:`DbClient` to request the
        set of all packages define known to the database.
        """
        return self.db.get_all_packages()

    def do_allvers(self):
        """
        Handler for "ALLVERS" message, sent by :class:`DbClient` to request the
        set of all (package, version) tuples known to the database.
        """
        return self.db.get_all_package_versions()

    def do_newpkg(self, package, skip):
        """
        Handler for "NEWPKG" message, sent by :class:`DbClient` to register a
        new package.
        """
        return self.db.add_new_package(package)

    def do_newver(self, package, version, released, skip):
        """
        Handler for "NEWVER" message, sent by :class:`DbClient` to register a
        new (package, version) tuple.
        """
        return self.db.add_new_package_version(package, version, released, skip)

    def do_skippkg(self, package, reason):
        """
        Handler for "SKIPPKG" message, sent by :class:`DbClient` to skip
        building all versions of a package.
        """
        self.db.skip_package(package, reason)

    def do_skipver(self, package, version, reason):
        """
        Handler for "SKIPVER" message, sent by :class:`DbClient` to skip
        building a specific version of a package.
        """
        self.db.skip_package_version(package, version, reason)

    def do_logdownload(self, download):
        """
        Handler for "LOGDOWNLOAD" message, sent by :class:`DbClient` to
        register a new download.
        """
        self.db.log_download(DownloadState.from_message(download))

    def do_logbuild(self, build):
        """
        Handler for "LOGBUILD" message, sent by :class:`DbClient` to register a
        new build result.
        """
        build = BuildState.from_message(build)
        self.db.log_build(build)
        return build.build_id

    def do_delbuild(self, package, version):
        """
        Handler for "DELBUILD" message, sent by :class:`DbClient` to remove all
        builds (and files and downloads by cascade) for *version* of *package*.
        """
        self.db.delete_build(package, version)

    def do_pkgfiles(self, package):
        """
        Handler for "PKGFILES" message, sent by :class:`DbClient` to request
        details of all wheels assocated with *package*.
        """
        return self.db.get_package_files(package)

    def do_projvers(self, package):
        """
        Handler for "PROJVERS" message, sent by :class:`DbClient` to request
        build and skip details of all versions of *package*.
        """
        return self.db.get_project_versions(package)

    def do_projfiles(self, package):
        """
        Handler for "PROJFILES" message, sent by :class:`DbClient` to request
        file details of all versions of *package*.
        """
        return list(self.db.get_project_files(package))

    def do_verfiles(self, package, version):
        """
        Handler for "VERFILES" message, sent by :class:`DbClient` to request
        the filenames of all wheels associated with *version* of *package*.
        """
        return set(self.db.get_version_files(package, version))

    def do_getskip(self, package, version):
        """
        Handler for "GETSKIP" message, send by :class:`DbClient` to request
        the reason for skipping builds of *version* of *package*.
        """
        return self.db.get_version_skip(package, version)

    def do_pkgexists(self, package):
        """
        Handler for "PKGEXISTS" message, sent by :class:`DbClient` to request
        whether or not the specified *package* exists.
        """
        return self.db.test_package(package)

    def do_verexists(self, package, version):
        """
        Handler for "VEREXISTS" message, sent by :class:`DbClient` to request
        whether or not the specified *version* of *package* exists.
        """
        return self.db.test_package_version(package, version)

    def do_getabis(self):
        """
        Handler for "GETABIS" message, sent by :class:`DbClient` to request the
        list of all ABIs to build for.
        """
        return self.db.get_build_abis()

    def do_getpypi(self):
        """
        Handler for "GETPYPI" message, sent by :class:`DbClient` to request the
        record of the last serial number from the PyPI changelog.
        """
        return self.db.get_pypi_serial()

    def do_setpypi(self, serial):
        """
        Handler for "SETPYPI" message, sent by :class:`DbClient` to update the
        last seen serial number from the PyPI changelog.
        """
        self.db.set_pypi_serial(serial)

    def do_getstats(self):
        """
        Handler for "GETSTATS" message, sent by :class:`DbClient` to request
        the latest database statistics, returned as a list of (field, value)
        tuples.
        """
        return self.db.get_statistics()

    def do_getdl(self):
        """
        Handler for "GETDL" message, sent by :class:`DbClient` to request
        the recent download statistics, returned as a list of (name, count)
        tuples.
        """
        return self.db.get_downloads_recent()

    def do_filedeps(self, filename):
        """
        Handler for "FILEDEPS" message, sent by :class:`DbClient` to request
        dependencies for *filename*, returned as a dict mapping tool names
        to dependency sets.
        """
        return self.db.get_file_dependencies(filename)


class DbClient:
    """
    RPC client class for talking to :class:`TheOracle`.
    """
    def __init__(self, config):
        self.ctx = transport.Context.instance()
        self.db_queue = self.ctx.socket(
            zmq.REQ, protocol=reversed(protocols.the_oracle))
        self.db_queue.hwm = 10
        self.db_queue.connect(config.db_queue)

    def close(self):
        self.db_queue.close()

    def _execute(self, msg, data=protocols.NoData):
        # If sending blocks this either means we're shutting down, or
        # something's gone horribly wrong (either way, raising EAGAIN is fine)
        self.db_queue.send_msg(msg, data, flags=zmq.NOBLOCK)
        status, result = self.db_queue.recv_msg()
        if status == 'OK':
            return result
        else:
            raise IOError(result)

    def add_new_package(self, package, skip=''):
        """
        See :meth:`.db.Database.add_new_package`.
        """
        return self._execute('NEWPKG', [package, skip])

    def add_new_package_version(self, package, version, released=None, skip=''):
        """
        See :meth:`.db.Database.add_new_package_version`.
        """
        return self._execute('NEWVER', [package, version, released, skip])

    def skip_package(self, package, reason):
        """
        See :meth:`.db.Database.skip_package`.
        """
        self._execute('SKIPPKG', [package, reason])

    def skip_package_version(self, package, version, reason):
        """
        See :meth:`.db.Database.skip_package_version`.
        """
        self._execute('SKIPVER', [package, version, reason])

    def test_package(self, package):
        """
        See :meth:`.db.Database.test_package`.
        """
        return self._execute('PKGEXISTS', package)

    def test_package_version(self, package, version):
        """
        See :meth:`.db.Database.test_package_version`.
        """
        return self._execute('VEREXISTS', [package, version])

    def log_download(self, download):
        """
        See :meth:`.db.Database.log_download`.
        """
        self._execute('LOGDOWNLOAD', download.as_message())

    def log_build(self, build):
        """
        See :meth:`.db.Database.log_build`.
        """
        build_id = self._execute('LOGBUILD', build.as_message())
        build.logged(build_id)

    def get_build_abis(self):
        """
        See :meth:`.db.Database.get_build_abis`.
        """
        return self._execute('GETABIS')

    def get_pypi_serial(self):
        """
        See :meth:`.db.Database.get_pypi_serial`.
        """
        return self._execute('GETPYPI')

    def set_pypi_serial(self, serial):
        """
        See :meth:`.db.Database.set_pypi_serial`.
        """
        self._execute('SETPYPI', serial)

    def get_all_packages(self):
        """
        See :meth:`.db.Database.get_all_packages`.
        """
        return self._execute('ALLPKGS')

    def get_all_package_versions(self):
        """
        See :meth:`.db.Database.get_all_package_versions`.
        """
        return self._execute('ALLVERS')

    def get_statistics(self):
        """
        See :meth:`.db.Database.get_statistics`.
        """
        return self._execute('GETSTATS')

    def get_downloads_recent(self):
        """
        See :meth:`.db.Database.get_downloads_recent`.
        """
        return self._execute('GETDL')

    def get_package_files(self, package):
        """
        See :meth:`.db.Database.get_package_files`.
        """
        return self._execute('PKGFILES', package)

    def get_project_versions(self, package):
        """
        See :meth:`.db.Database.get_project_versions`.
        """
        return [
            ProjectVersionsRow(*row)
            for row in self._execute('PROJVERS', package)
        ]

    def get_project_files(self, package):
        """
        See :meth:`.db.Database.get_project_files`.
        """
        return [
            ProjectFilesRow(*row)
            for row in self._execute('PROJFILES', package)
        ]

    def get_version_files(self, package, version):
        """
        See :meth:`.db.Database.get_version_files`.
        """
        return self._execute('VERFILES', [package, version])

    def get_version_skip(self, package, version):
        """
        See :meth:`.db.Database.get_version_skip`.
        """
        return self._execute('GETSKIP', [package, version])

    def get_file_dependencies(self, filename):
        """
        See :meth:`.db.Database.get_file_dependencies`.
        """
        return self._execute('FILEDEPS', filename)

    def delete_build(self, package, version):
        """
        See :meth:`.db.Database.delete_build`.
        """
        self._execute('DELBUILD', [package, version])
