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

from .. import const, protocols, transport, tasks
from ..states import (
    BuildState, DownloadState, SearchState, ProjectState, JSONState, PageState)
from .db import Database, ProjectVersionsRow, ProjectFilesRow, RewritePendingRow


class TheOracle(tasks.NonStopTask):
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
        db_queue = self.socket(
            transport.REQ, protocol=protocols.the_oracle)
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
            addr, msg, data = queue.recv_addr_msg()
        except IOError as exc:
            self.logger.error(str(exc))
            # REQ sockets *must* send a reply even when stuff goes wrong
            # otherwise the send/recv cycle that REQ/REP depends upon breaks.
            # Here we've got a badly formed request and we can't even get the
            # reply address, so we just make one up (empty). This message
            # won't go anywhere (bogus address) but that doesn't matter as we
            # just want to get the socket back to receiving state
            addr, msg, data = b'', '', str(exc)
        try:
            handler = {
                'ALLPKGS':     lambda: self.do_allpkgs(),
                'ALLVERS':     lambda: self.do_allvers(),
                'NEWPKG':      lambda: self.do_newpkg(*data),
                'NEWVER':      lambda: self.do_newver(*data),
                'SETDESC':     lambda: self.do_setdesc(*data),
                'GETDESC':     lambda: self.do_getdesc(data),
                'SKIPPKG':     lambda: self.do_skippkg(*data),
                'SKIPVER':     lambda: self.do_skipver(*data),
                'DELPKG':      lambda: self.do_delpkg(data),
                'DELVER':      lambda: self.do_delver(*data),
                'YANKVER':     lambda: self.do_yankver(*data),
                'UNYANKVER':   lambda: self.do_unyankver(*data),
                'LOGDOWNLOAD': lambda: self.do_logdownload(data),
                'LOGSEARCH':   lambda: self.do_logsearch(data),
                'LOGPROJECT':  lambda: self.do_logproject(data),
                'LOGJSON':     lambda: self.do_logjson(data),
                'LOGPAGE':     lambda: self.do_logpage(data),
                'LOGBUILD':    lambda: self.do_logbuild(data),
                'DELBUILD':    lambda: self.do_delbuild(*data),
                'PKGFILES':    lambda: self.do_pkgfiles(data),
                'PROJVERS':    lambda: self.do_projvers(data),
                'PROJFILES':   lambda: self.do_projfiles(data),
                'VERFILES':    lambda: self.do_verfiles(*data),
                'GETSKIP':     lambda: self.do_getskip(*data),
                'PKGEXISTS':   lambda: self.do_pkgexists(data),
                'PKGDELETED':  lambda: self.do_pkgdeleted(data),
                'VEREXISTS':   lambda: self.do_verexists(*data),
                'VERSDELETED': lambda: self.do_versdeleted(data),
                'GETABIS':     lambda: self.do_getabis(),
                'GETPYPI':     lambda: self.do_getpypi(),
                'SETPYPI':     lambda: self.do_setpypi(data),
                'GETSTATS':    lambda: self.do_getstats(),
                'GETSEARCH':   lambda: self.do_getsearch(),
                'FILEDEPS':    lambda: self.do_filedeps(data),
                'SAVERWP':     lambda: self.do_saverwp(data),
                'LOADRWP':     lambda: self.do_loadrwp(),
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

    def do_newpkg(self, package, skip, description):
        """
        Handler for "NEWPKG" message, sent by :class:`DbClient` to register a
        new package.
        """
        return self.db.add_new_package(package, skip, description)

    def do_newver(self, package, version, released, skip):
        """
        Handler for "NEWVER" message, sent by :class:`DbClient` to register a
        new (package, version) tuple.
        """
        return self.db.add_new_package_version(package, version, released, skip)

    def do_setdesc(self, package, description):
        """
        Handler for "SETDESC" message, sent by :class:`DbClient` to update a
        package's project description.
        """
        return self.db.set_package_description(package, description)

    def do_getdesc(self, package):
        """
        Handler for "GETDESC" message, sent by :class:`DbClient` to retrieve
        a package's project description.
        """
        return self.db.get_package_description(package)

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

    def do_delpkg(self, package):
        """
        Handler for "DELPKG" message, sent by :class:`DbClient` to delete a
        package.
        """
        self.db.delete_package(package)

    def do_delver(self, package, version):
        """
        Handler for "DELVER" message, sent by :class:`DbClient` to delete
        a specific version of a package.
        """
        self.db.delete_version(package, version)

    def do_yankver(self, package, version):
        """
        Handler for "YANKVER" message, sent by :class:`DbClient` to mark
        a specific version of a package as "yanked".
        """
        self.db.yank_version(package, version)

    def do_unyankver(self, package, version):
        """
        Handler for "UNYANKVER" message, sent by :class:`DbClient` to mark
        a specific version of a package as not "yanked".
        """
        self.db.unyank_version(package, version)

    def do_logdownload(self, download):
        """
        Handler for "LOGDOWNLOAD" message, sent by :class:`DbClient` to register
        a new download.
        """
        self.db.log_download(DownloadState.from_message(download))

    def do_logsearch(self, search):
        """
        Handler for "LOGSEARCH" message, sent by :class:`DbClient` to
        register a new search.
        """
        self.db.log_search(SearchState.from_message(search))

    def do_logproject(self, project):
        """
        Handler for "LOGPROJECT" message, sent by :class:`DbClient` to register
        a new project page hit.
        """
        self.db.log_project(ProjectState.from_message(project))

    def do_logjson(self, json):
        """
        Handler for "LOGJSON" message, sent by :class:`DbClient` to register a
        new project JSON download.
        """
        self.db.log_json(JSONState.from_message(json))

    def do_logpage(self, page):
        """
        Handler for "LOGPAGE" message, sent by :class:`DbClient` to register a
        new web page hit.
        """
        self.db.log_page(PageState.from_message(page))

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
        return self.db.get_project_files(package)

    def do_verfiles(self, package, version):
        """
        Handler for "VERFILES" message, sent by :class:`DbClient` to request
        the filenames of all wheels associated with *version* of *package*.
        """
        return self.db.get_version_files(package, version)

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

    def do_pkgdeleted(self, package):
        """
        Handler for "PKGDELETED" message, sent by :class:`DbClient` to request
        whether or not the specified *package* has been marked for deletion.
        """
        return self.db.package_marked_deleted(package)

    def do_verexists(self, package, version):
        """
        Handler for "VEREXISTS" message, sent by :class:`DbClient` to request
        whether or not the specified *version* of *package* exists.
        """
        return self.db.test_package_version(package, version)

    def do_versdeleted(self, package):
        """
        Handler for "VERSDELETED" message, sent by :class:`DbClient` to request
        any versions for *package* which have been marked for deletion.
        """
        return self.db.get_versions_deleted(package)

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

    def do_getsearch(self):
        """
        Handler for "GETSEARCH" message, sent by :class:`DbClient` to request
        the recent download statistics, returned as a mapping of package to
        (downloads_recent, downloads_all) tuples.
        """
        return self.db.get_search_index()

    def do_filedeps(self, filename):
        """
        Handler for "FILEDEPS" message, sent by :class:`DbClient` to request
        apt dependencies for *filename*, returned as a set of dependencies
        excluding those which are preinstalled in the distro version with the
        corresponding ABI tag.
        """
        return self.db.get_file_apt_dependencies(filename)

    def do_saverwp(self, queue):
        """
        Handler for "SAVERWP" message, sent by :class:`DbClient` to request
        that *queue* is saved to the ``rewrites_pending`` table.
        """
        return self.db.save_rewrites_pending(queue)

    def do_loadrwp(self):
        """
        Handler for "LOADRWP" message, sent by :class:`DbClient` to request
        the content of the ``rewrites_pending`` table.
        """
        return self.db.load_rewrites_pending()


class DbClient:
    """
    RPC client class for talking to :class:`TheOracle`.
    """
    def __init__(self, config, logger=None):
        self.ctx = transport.Context()
        self.db_queue = self.ctx.socket(
            transport.REQ, protocol=reversed(protocols.the_oracle),
            logger=logger)
        self.db_queue.hwm = 10
        self.db_queue.connect(config.db_queue)

    def close(self):
        self.db_queue.close()

    def _execute(self, msg, data=protocols.NoData):
        # If sending blocks this either means we're shutting down, or
        # something's gone horribly wrong (either way, raising EAGAIN is fine)
        self.db_queue.send_msg(msg, data, flags=transport.NOBLOCK)
        status, result = self.db_queue.recv_msg()
        if status == 'OK':
            return result
        else:
            raise IOError(result)

    def add_new_package(self, package, skip='', description=''):
        """
        See :meth:`.db.Database.add_new_package`.
        """
        return self._execute('NEWPKG', [package, skip, description])

    def add_new_package_version(self, package, version, released=None, skip=''):
        """
        See :meth:`.db.Database.add_new_package_version`.
        """
        return self._execute('NEWVER', [package, version, released, skip])

    def set_package_description(self, package, description):
        """
        See :meth:`.db.Database.update_project_description`.
        """
        return self._execute('SETDESC', [package, description])

    def get_package_description(self, package):
        """
        See :meth:`.db.Database.get_project_description`.
        """
        return self._execute('GETDESC', package)

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

    def delete_package(self, package):
        """
        See :meth:`.db.Database.delete_package`.
        """
        self._execute('DELPKG', package)

    def delete_version(self, package, version):
        """
        See :meth:`.db.Database.delete_version`.
        """
        self._execute('DELVER', [package, version])

    def yank_version(self, package, version):
        """
        See :meth:`.db.Database.yank_version`.
        """
        self._execute('YANKVER', [package, version])

    def unyank_version(self, package, version):
        """
        See :meth:`.db.Database.unyank_version`.
        """
        self._execute('UNYANKVER', [package, version])

    def test_package(self, package):
        """
        See :meth:`.db.Database.test_package`.
        """
        return self._execute('PKGEXISTS', package)

    def package_marked_deleted(self, package):
        """
        See :meth:`.db.Database.package_marked_deleted`.
        """
        return self._execute('PKGDELETED', package)

    def test_package_version(self, package, version):
        """
        See :meth:`.db.Database.test_package_version`.
        """
        return self._execute('VEREXISTS', [package, version])

    def get_versions_deleted(self, package):
        """
        See :meth:`.db.Database.get_versions_deleted`.
        """
        return self._execute('VERSDELETED', package)

    def log_download(self, download):
        """
        See :meth:`.db.Database.log_download`.
        """
        self._execute('LOGDOWNLOAD', download.as_message())

    def log_search(self, search):
        """
        See :meth:`.db.Database.log_search`.
        """
        self._execute('LOGSEARCH', search.as_message())

    def log_project(self, project):
        """
        See :meth:`.db.Database.log_project`.
        """
        self._execute('LOGPROJECT', project.as_message())

    def log_json(self, json):
        """
        See :meth:`.db.Database.log_json`.
        """
        self._execute('LOGJSON', json.as_message())

    def log_page(self, page):
        """
        See :meth:`.db.Database.log_page`.
        """
        self._execute('LOGPAGE', page.as_message())

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

    def get_search_index(self):
        """
        See :meth:`.db.Database.get_search_index`.
        """
        return self._execute('GETSEARCH')

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

    def get_file_apt_dependencies(self, filename):
        """
        See :meth:`.db.Database.get_file_apt_dependencies`.
        """
        return self._execute('FILEDEPS', filename)

    def delete_build(self, package, version):
        """
        See :meth:`.db.Database.delete_build`.
        """
        self._execute('DELBUILD', [package, version])

    def save_rewrites_pending(self, queue):
        """
        See :meth:`.db.Database.save_rewrites_pending`.
        """
        self._execute('SAVERWP', queue)

    def load_rewrites_pending(self):
        """
        See :meth:`.db.Database.load_rewrites_pending`.
        """
        return [
            RewritePendingRow(*row)
            for row in self._execute('LOADRWP')
        ]
