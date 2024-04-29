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
This module defines the low level database API, :class:`Database`. This is a
simple core SQLAlchemy affair which runs trivial queries against the PostgreSQL
database.  All the serious logic is defined within views in the database
itself.

.. autoclass:: Database
    :members:
"""

import inspect
import warnings
from datetime import datetime, timedelta, timezone
from itertools import chain, groupby
from operator import attrgetter
from collections import namedtuple

from sqlalchemy import MetaData, Table, select, create_engine, func, distinct
from sqlalchemy.exc import IntegrityError, SAWarning

from .. import __version__, protocols
from ..states import (
    BuildState, DownloadState, SearchState, ProjectState, JSONState, PageState)


UTC = timezone.utc


RewritePendingRow = namedtuple('RewritePendingRow', (
    'package', 'added_at', 'command'))


CONTROL_CHARS = {
    c: '\N{REPLACEMENT CHARACTER}'
    for c in chain(
        range(0x00, 0x09),
        range(0x0e, 0x20),
        [0x0b, 0x7f]
    )
}

def sanitize(s):
    """
    A small routine for sanitizing the sometimes crazy stuff that winds up in
    build log output...
    """
    if s is None:
        return None
    else:
        return s.translate(CONTROL_CHARS)


def rpc(message, args_to_data=None, data_to_args=None):
    """
    Decorator for :class:`Database` methods that marks them as candidates for
    RPC calls by :class:`~piwheels.master.the_oracle.TheOracle` task.

    The decorator doesn't fundamentally change the method, but simply
    associates it with the message to be used to represent the call (see
    :mod:`piwheels.protocols`), and the routines used to serialize and
    de-serialize its parameters (in most cases these are automatically derived
    from the method's signature).

    If given, *args_to_data* must be a routine that takes one parameter,
    "args", representing the bound arguments the method was called with. It
    must return a CBOR-serializable object which will be transferred as the
    data along with the *message*.

    If given, *data_to_args* must be a routine that takes the data returned by
    *args_to_data* and converts it to a tuple of args which will be used to
    call the method on the receiving side.

    If the method only takes straight-forward scalar parameters, the default
    implementation of these methods is acceptable. Only override them if the
    method accepts more complex objects that don't have obvious serializations.
    """
    def wrap_rpc(method):
        sig = inspect.signature(method)
        if len(sig.parameters) == 1: # no args except self
            default_args_to_data = lambda args: protocols.NoData
            default_data_to_args = lambda data: ()
        elif len(sig.parameters) == 2: # one arg (other than self)
            default_args_to_data = lambda args: args[1]
            default_data_to_args = lambda data: (data,)
        else:
            default_args_to_data = lambda args: list(args[1:])
            default_data_to_args = lambda data: data
        method.args_to_data = (
            default_args_to_data if args_to_data is None else args_to_data)
        method.data_to_args = (
            default_data_to_args if data_to_args is None else data_to_args)
        method.message = message
        return method
    return wrap_rpc


class Database:
    """
    PiWheels database connection class
    """
    # pylint: disable=too-many-instance-attributes,no-value-for-parameter
    # SQLAlchemy does fun things with decorators which screws with pylint's
    # static analysis
    engines = {}

    def __init__(self, dsn):
        try:
            engine = Database.engines[dsn]
        except KeyError:
            engine = create_engine(dsn)
            Database.engines[dsn] = engine
        self._conn = engine.connect()
        try:
            self._meta = MetaData(bind=self._conn)
            with warnings.catch_warnings():
                # Ignore warnings about partial indexes (SQLAlchemy doesn't
                # know how to reflect them but that doesn't matter for our
                # purposes as we're not doing DDL translation)
                warnings.simplefilter('ignore', category=SAWarning)
                self._configuration = Table('configuration', self._meta,
                                            autoload=True)
                with self._conn.begin():
                    db_version = self._conn.scalar(
                        select([self._configuration.c.version])
                    )
                    if db_version != __version__:
                        raise RuntimeError(
                            'Database version (%s) does not match '
                            'software version (%s)' % (db_version, __version__)
                        )
                self._packages = Table('packages', self._meta, autoload=True)
                self._versions = Table('versions', self._meta, autoload=True)
                self._builds = Table('builds', self._meta, autoload=True)
                self._files = Table('files', self._meta, autoload=True)
                self._dependencies = Table(
                    'dependencies', self._meta, autoload=True)
                self._downloads = Table('downloads', self._meta, autoload=True)
                self._build_abis = Table(
                    'build_abis', self._meta, autoload=True)
        except:
            self._conn.close()
            raise

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @rpc('NEWPKG')
    def add_new_package(self, package, skip='', description=''):
        """
        Insert a new package record into the database. Returns True if the row
        was inserted successfully, or False if a key violation occurred.
        """
        with self._conn.begin():
            return self._conn.execute(
                "VALUES (add_new_package(%s, %s, %s))", (package, skip,
                                                         description)).scalar()

    @rpc('NEWVER')
    def add_new_package_version(self, package, version,
                                released=None, skip=''):
        """
        Insert a new package version record into the database. Returns True if
        the row was inserted successfully, or False if a key violation
        occurred.
        """
        with self._conn.begin():
            if released is None:
                released = datetime.now(tz=UTC)
            return self._conn.execute(
                "VALUES (add_new_package_version(%s, %s, %s, %s))",
                (package, version,
                 released.astimezone(UTC).replace(tzinfo=None), skip)
            ).scalar()

    @rpc('NEWPKGNAME')
    def add_package_name(self, package, name, seen=None):
        """
        Add a new package alias or update the last seen timestamp.
        """
        if seen is None:
            seen = datetime(1970, 1, 1, tzinfo=UTC)
        with self._conn.begin():
            self._conn.execute(
                "VALUES (add_package_name(%s, %s, %s))",
                (package, name, seen.astimezone(UTC).replace(tzinfo=None)))

    @rpc('GETPKGNAMES')
    def get_package_aliases(self, package):
        """
        Retrieve all aliases for *package* (not including the canonical name
        itself).
        """
        with self._conn.begin():
            return [
                row.name
                for row in self._conn.execute(
                    "SELECT name FROM get_package_aliases(%s)", (package, )
                )
            ]

    @rpc('SETDESC')
    def set_package_description(self, package, description):
        """
        Update the description for *package* in the packages table.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (set_package_description(%s, %s))",
                (package, description))

    @rpc('SKIPPKG')
    def skip_package(self, package, reason):
        """
        Mark a package with a reason to prevent future builds of all versions
        (and all future versions).
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (skip_package(%s, %s))", (package, reason))

    @rpc('SKIPVER')
    def skip_package_version(self, package, version, reason):
        """
        Mark a version of a package with a reason to prevent future build
        attempts.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (skip_package_version(%s, %s, %s))",
                (package, version, reason))

    @rpc('DELPKG')
    def delete_package(self, package):
        """
        Remove the specified package, along with all builds and files.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (delete_package(%s))", (package))

    @rpc('DELVER')
    def delete_version(self, package, version):
        """
        Remove the specified version of the specified package, along with all
        builds and files.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (delete_version(%s, %s))", (package, version))

    @rpc('YANKVER')
    def yank_version(self, package, version):
        """
        Mark the specified version of the specified package version as "yanked".
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (yank_version(%s, %s))", (package, version))

    @rpc('UNYANKVER')
    def unyank_version(self, package, version):
        """
        Mark the specified version of the specified package version as "unyanked".
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (unyank_version(%s, %s))", (package, version))

    @rpc('PKGEXISTS')
    def test_package(self, package):
        """
        Check whether *package* already exists in the database. Returns a
        boolean.
        """
        with self._conn.begin():
            return bool(self._conn.scalar(
                "VALUES (test_package(%s))", (package,)
            ))

    @rpc('PKGDELETED')
    def package_marked_deleted(self, package):
        """
        Check whether *package* has been marked for deletion.
        """
        with self._conn.begin():
            return bool(self._conn.scalar(
                "VALUES (package_marked_deleted(%s))", (package,)
            ))

    @rpc('VEREXISTS')
    def test_package_version(self, package, version):
        """
        Check whether *version* of *package* already exists in the database.
        Returns a boolean.
        """
        with self._conn.begin():
            return bool(self._conn.scalar(
                "VALUES (test_package_version(%s, %s))", (package, version)
            ))

    @rpc('VERSDELETED')
    def get_versions_deleted(self, package):
        """
        Return any versions of *package* which have been marked for deletion.
        """
        with self._conn.begin():
            return {
                row.version
                for row in self._conn.execute(
                    "SELECT version FROM get_versions_deleted(%s)", (package,)
                )
            }

    @rpc('LOGDOWNLOAD',
         lambda args: args[1].as_message(),
         lambda data: (DownloadState.from_message(data),))
    def log_download(self, download):
        """
        Log a download in the database, including data derived from JSON in
        pip's user-agent.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (log_download(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s))",
                (
                    sanitize(download.filename),
                    download.host,
                    download.timestamp.astimezone(UTC).replace(tzinfo=None),
                    sanitize(download.arch),
                    sanitize(download.distro_name),
                    sanitize(download.distro_version),
                    sanitize(download.os_name),
                    sanitize(download.os_version),
                    sanitize(download.py_name),
                    sanitize(download.py_version),
                    sanitize(download.installer_name),
                    sanitize(download.installer_version),
                    sanitize(download.setuptools_version),
                ))

    @rpc('LOGSEARCH',
         lambda args: args[1].as_message(),
         lambda data: (SearchState.from_message(data),))
    def log_search(self, search):
        """
        Log a search in the database, including data derived from JSON in
        pip's user-agent.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (log_search(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s))",
                (
                    sanitize(search.package),
                    search.host,
                    search.timestamp.astimezone(UTC).replace(tzinfo=None),
                    sanitize(search.arch),
                    sanitize(search.distro_name),
                    sanitize(search.distro_version),
                    sanitize(search.os_name),
                    sanitize(search.os_version),
                    sanitize(search.py_name),
                    sanitize(search.py_version),
                    sanitize(search.installer_name),
                    sanitize(search.installer_version),
                    sanitize(search.setuptools_version),
                ))

    @rpc('LOGPROJECT',
         lambda args: args[1].as_message(),
         lambda data: (ProjectState.from_message(data),))
    def log_project(self, project):
        """
        Log a project page hit in the database.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (log_project(%s, %s, %s, %s))",
                (
                    sanitize(project.package),
                    project.host,
                    project.timestamp.astimezone(UTC).replace(tzinfo=None),
                    sanitize(project.user_agent),
                ))

    @rpc('LOGJSON',
         lambda args: args[1].as_message(),
         lambda data: (JSONState.from_message(data),))
    def log_json(self, json):
        """
        Log a project's JSON page hit in the database.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (log_json(%s, %s, %s, %s))",
                (
                    sanitize(json.package),
                    json.host,
                    json.timestamp.astimezone(UTC).replace(tzinfo=None),
                    sanitize(json.user_agent),
                ))

    @rpc('LOGPAGE',
         lambda args: args[1].as_message(),
         lambda data: (PageState.from_message(data),))
    def log_page(self, page):
        """
        Log a web page hit in the database.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (log_page(%s, %s, %s, %s))",
                (
                    sanitize(page.page),
                    page.host,
                    page.timestamp.astimezone(UTC).replace(tzinfo=None),
                    sanitize(page.user_agent),
                ))

    @rpc('LOGBUILD',
         lambda args: args[1].as_message(),
         lambda data: (BuildState.from_message(data),))
    def log_build(self, build):
        """
        Log a build attempt in the database, including wheel info if
        successful.
        """
        with self._conn.begin():
            if build.status:
                build_id = self._conn.execute(
                    "VALUES (log_build_success(%s, %s, %s, %s, %s, "
                    "CAST(%s AS files ARRAY), CAST(%s AS dependencies ARRAY)"
                    "))",
                    (
                        build.package,
                        build.version,
                        build.slave_id,
                        build.duration,
                        build.abi_tag,
                        [(
                            file.filename,
                            None,
                            file.filesize,
                            file.filehash,
                            file.package_tag,
                            file.package_version_tag,
                            file.py_version_tag,
                            file.abi_tag,
                            file.platform_tag,
                            file.requires_python,
                        )
                        for file in build.files.values()],
                        [(
                            file.filename,
                            tool,
                            dependency,
                        )
                        for file in build.files.values()
                        for tool, dependencies in file.dependencies.items()
                        for dependency in dependencies]
                    )).scalar()
            else:
                build_id = self._conn.execute(
                    "VALUES (log_build_failure(%s, %s, %s, %s, %s))",
                    (
                        build.package,
                        build.version,
                        build.slave_id,
                        build.duration,
                        build.abi_tag,
                    )).scalar()
            build.logged(build_id)
            return build_id

    @rpc('GETABIS')
    def get_build_abis(self, exclude_skipped=False):
        """
        Return a set of ABIs. If **exclude_skipped** is ``False``, return all
        ABIs from the build_abis table, otherwise return only active ABIs (not
        skipped).
        """
        with self._conn.begin():
            return {
                rec.abi_tag
                for rec in self._conn.execute(self._build_abis.select())
                if rec.skip == '' or not exclude_skipped
            }

    @rpc('GETPYPI')
    def get_pypi_serial(self):
        """
        Return the serial number of the last PyPI event.
        """
        with self._conn.begin():
            return self._conn.scalar("VALUES (get_pypi_serial())")

    @rpc('SETPYPI')
    def set_pypi_serial(self, serial):
        """
        Update the serial number of the last PyPI event.
        """
        with self._conn.begin():
            self._conn.execute("VALUES (set_pypi_serial(%s))", (serial,))

    @rpc('ALLPKGS')
    def get_all_packages(self):
        """
        Returns the set of all known package names.
        """
        with self._conn.begin():
            return {
                rec.package
                for rec in self._conn.execute(self._packages.select())
            }

    @rpc('ALLVERS')
    def get_all_package_versions(self):
        """
        Returns the set of all known (package, version) tuples.
        """
        with self._conn.begin():
            return {
                (rec.package, rec.version)
                for rec in self._conn.execute(self._versions.select())
            }

    # NOTE: This method is not exposed on TheOracle as it is only used by
    # TheArchitect task
    def get_build_queue(self, limit=1000):
        """
        Returns a mapping of ABI tags to an ordered list of up to *limit*
        package version tuples which currently need building for that ABI.
        """
        with self._conn.begin():
            return {
                abi_tag: [
                    (row.package, row.version)
                    for row in rows
                ]
                for abi_tag, rows in groupby(
                    self._conn.execution_options(stream_results=True).\
                    execute("SELECT abi_tag, package, version "
                            "FROM get_build_queue(%s)", (limit,)),
                        key=attrgetter('abi_tag')
                )
            }

    @rpc('INITSTATS')
    def get_initial_statistics(self):
        """
        Return the initial (expensive to calculate) statistics from the
        database.
        """
        with self._conn.begin():
            stats = self._conn.execute(
                "SELECT * FROM get_initial_statistics()"
            ).first()._asdict()
            return stats

    @rpc('GETSTATS')
    def get_statistics(self):
        """
        Return various build related statistics from the database.
        """
        with self._conn.begin():
            stats = self._conn.execute(
                "SELECT * FROM get_statistics()"
            ).first()._asdict()
            stats['builds_last_hour'] = {
                row.abi_tag: row.builds
                for row in self._conn.execute(
                    "SELECT * FROM get_builds_last_hour()"
                )
            }
            return stats

    @rpc('GETSEARCH')
    def get_search_index(self):
        """
        Return a mapping of all packages to their download count for the last
        month. This is used to construct the searchable package index.
        """
        with self._conn.begin():
            return {
                rec.package: (rec.downloads_recent, rec.downloads_all)
                for rec in self._conn.execute(
                    "SELECT package, downloads_recent, downloads_all "
                    "FROM get_search_index()")
            }

    @rpc('PKGFILES')
    def get_package_files(self, package):
        """
        Returns a mapping of filenames to file hashes; this is all the data
        required to build the simple index.html for the specified package.
        """
        with self._conn.begin():
            return {
                row.filename: row.filehash
                for row in self._conn.execute(
                    "SELECT filename, filehash "
                    "FROM get_package_files(%s)", (package,)
                )
            }

    @rpc('VERFILES')
    def get_version_files(self, package, version):
        """
        Returns the names of all files for *version* of *package*.
        """
        with self._conn.begin():
            return {
                row.filename
                for row in self._conn.execute(
                    "SELECT filename "
                    "FROM get_version_files(%s, %s)", (package, version)
                )
            }

    @rpc('PROJDATA')
    def get_project_data(self, package):
        """
        Returns all details required to build the project page of the specified
        *package*.
        """
        with self._conn.begin():
            for row in self._conn.execute(
                "VALUES (get_project_data(%s))", (package,)
            ):
                # Fix up datetime and set types (which JSON doesn't support)
                data = row[0]
                for release in data['releases'].values():
                    release['released'] = datetime.fromisoformat(
                        release['released']).astimezone(tz=UTC)
                    for wheel in release['files'].values():
                        wheel['apt_dependencies'] = set(
                            wheel['apt_dependencies'])
                return data

    @rpc('GETSKIP')
    def get_version_skip(self, package, version):
        """
        Returns the reason for skipping *version* of *package*.
        """
        with self._conn.begin():
            return self._conn.scalar(
                select([self._versions.c.skip]).
                where(self._versions.c.package == package).
                where(self._versions.c.version == version)
            )

    @rpc('DELBUILD')
    def delete_build(self, package, version):
        """
        Remove all builds for the specified package and version, along with
        all files records.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (delete_build(%s, %s))", (package, version))

    @rpc('SAVERWP')
    def save_rewrites_pending(self, queue):
        """
        Save the rewrites-pending queue (the internal state of
        :class:`TheSecretary`) in the database. The *queue* parameter is
        expected to be a list of :class:`RewritePendingRow` tuples.
        """
        # NOTE: the double list below works around a conflict between
        # SQLAlchemy's execution modes and our parameter types. SA treats
        # .execute(sql_text, [(), (), (), ...]) as an attempt to execute
        # sql_text multiple times, binding each set of parameters in turn.
        # However, in our case we want to execute it once with a fat ARRAY
        # parameter. Hence, we use .execute(sql_text, [[(), (), (), ...]]) to
        # work around this
        with self._conn.begin():
            self._conn.execute(
                "VALUES (save_rewrites_pending("
                "CAST(%s AS rewrites_pending ARRAY)"
                "))", ([[
                    # Re-pack with tuples
                    (package, added_at, command)
                    for (package, added_at, command) in queue
                ]],))

    @rpc('LOADRWP')
    def load_rewrites_pending(self):
        """
        Loads the rewrites-pending queue (the internal state of
        :class:`TheSecretary`) from the database.
        """
        with self._conn.begin():
            return [
                RewritePendingRow(row.package, row.added_at.replace(tzinfo=UTC), row.command)
                for row in self._conn.execute(
                    "SELECT package, added_at, command "
                    "FROM load_rewrites_pending()"
                )
            ]
