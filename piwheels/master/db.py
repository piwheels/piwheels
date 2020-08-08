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

import warnings
from datetime import datetime, timedelta, timezone
from itertools import chain, groupby
from operator import attrgetter
from collections import namedtuple

from sqlalchemy import MetaData, Table, select, create_engine, func, distinct
from sqlalchemy.exc import IntegrityError, SAWarning

from .. import __version__


UTC = timezone.utc


ProjectVersionsRow = namedtuple('ProjectVersionsRow', (
    'version', 'skipped', 'builds_succeeded', 'builds_failed', 'yanked'))
ProjectFilesRow = namedtuple('ProjectFilesRow', (
    'version', 'abi_tag', 'filename', 'filesize', 'filehash', 'yanked'))
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
                self._output = Table('output', self._meta, autoload=True)
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

    def add_new_package(self, package, skip='', description=''):
        """
        Insert a new package record into the database. Returns True if the row
        was inserted successfully, or False if a key violation occurred.
        """
        with self._conn.begin():
            return self._conn.execute(
                "VALUES (add_new_package(%s, %s, %s))", (package, skip,
                                                         description)).scalar()

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

    def set_package_description(self, package, description):
        """
        Update the description for *package* in the packages table.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (set_package_description(%s, %s))",
                (package, description))

    def get_package_description(self, package):
        """
        Retrieve the description for *package* in the packages table.
        """
        with self._conn.begin():
            return self._conn.execute(
                "VALUES (get_package_description(%s))", (package,)).scalar()

    def skip_package(self, package, reason):
        """
        Mark a package with a reason to prevent future builds of all versions
        (and all future versions).
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (skip_package(%s, %s))", (package, reason))

    def skip_package_version(self, package, version, reason):
        """
        Mark a version of a package with a reason to prevent future build
        attempts.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (skip_package_version(%s, %s, %s))",
                (package, version, reason))

    def delete_package(self, package):
        """
        Remove the specified package, along with all builds and files.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (delete_package(%s))", (package))

    def delete_version(self, package, version):
        """
        Remove the specified version of the specified package, along with all
        builds and files.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (delete_version(%s, %s))", (package, version))

    def yank_version(self, package, version):
        """
        Mark the specified version of the specified package version as "yanked".
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (yank_version(%s, %s))", (package, version))

    def unyank_version(self, package, version):
        """
        Mark the specified version of the specified package version as "unyanked".
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (unyank_version(%s, %s))", (package, version))

    def test_package(self, package):
        """
        Check whether *package* already exists in the database. Returns a
        boolean.
        """
        with self._conn.begin():
            return bool(self._conn.scalar(
                "VALUES (test_package(%s))", (package,)
            ))

    def package_marked_deleted(self, package):
        """
        Check whether *package* has been marked for deletion.
        """
        with self._conn.begin():
            return bool(self._conn.scalar(
                "VALUES (package_marked_deleted(%s))", (package,)
            ))

    def test_package_version(self, package, version):
        """
        Check whether *version* of *package* already exists in the database.
        Returns a boolean.
        """
        with self._conn.begin():
            return bool(self._conn.scalar(
                "VALUES (test_package_version(%s, %s))", (package, version)
            ))

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

    def log_build(self, build):
        """
        Log a build attempt in the database, including build output and wheel
        info if successful.
        """
        with self._conn.begin():
            if build.status:
                build_id = self._conn.execute(
                    "VALUES (log_build_success(%s, %s, %s, %s, %s, %s, "
                    "CAST(%s AS files ARRAY), CAST(%s AS dependencies ARRAY)"
                    "))",
                    (
                        build.package,
                        build.version,
                        build.slave_id,
                        build.duration,
                        build.abi_tag,
                        sanitize(build.output),
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
                    "VALUES (log_build_failure(%s, %s, %s, %s, %s, %s))",
                    (
                        build.package,
                        build.version,
                        build.slave_id,
                        build.duration,
                        build.abi_tag,
                        sanitize(build.output),
                    )).scalar()
            build.logged(build_id)

    def get_build_abis(self):
        """
        Return the set of ABIs that the master should attempt to build.
        """
        with self._conn.begin():
            return {
                rec.abi_tag
                for rec in self._conn.execute(self._build_abis.select())
            }

    def get_pypi_serial(self):
        """
        Return the serial number of the last PyPI event.
        """
        with self._conn.begin():
            return self._conn.scalar("VALUES (get_pypi_serial())")

    def set_pypi_serial(self, serial):
        """
        Update the serial number of the last PyPI event.
        """
        with self._conn.begin():
            self._conn.execute("VALUES (set_pypi_serial(%s))", (serial,))

    def get_all_packages(self):
        """
        Returns the set of all known package names.
        """
        with self._conn.begin():
            return {
                rec.package
                for rec in self._conn.execute(self._packages.select())
            }

    def get_all_package_versions(self):
        """
        Returns the set of all known (package, version) tuples.
        """
        with self._conn.begin():
            return {
                (rec.package, rec.version)
                for rec in self._conn.execute(self._versions.select())
            }

    def get_build_queue(self, limit=1000):
        """
        Returns a mapping of ABI tags to an ordered list of up to *limit*
        package version tuples which currently need building for that ABI.
        """
        # NOTE: This method is not exposed on TheOracle as it is only used by
        # TheArchitect task
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

    def get_statistics(self):
        """
        Return various build related statistics from the database.
        """
        with self._conn.begin():
            stats = dict(
                self._conn.execute(
                    "SELECT * FROM get_statistics()"
                ).first().items()
            )
            stats['builds_last_hour'] = {
                row.abi_tag: row.builds
                for row in self._conn.execute(
                    "SELECT * FROM get_builds_last_hour()"
                )
            }
            return stats

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

    def get_project_versions(self, package):
        """
        Returns all details required to build the versions table in the
        project page of the specified *package*.
        """
        with self._conn.begin():
            return [
                ProjectVersionsRow(*row)
                for row in self._conn.execute(
                    "SELECT version, skipped, builds_succeeded, builds_failed, yanked "
                    "FROM get_project_versions(%s)", (package,)
                )
            ]

    def get_project_files(self, package):
        """
        Returns all details required to build the files table in the project
        page of the specified *package*.
        """
        with self._conn.begin():
            return [
                ProjectFilesRow(*row)
                for row in self._conn.execute(
                    "SELECT version, abi_tag, filename, filesize, filehash, yanked "
                    "FROM get_project_files(%s)", (package,)
                )
            ]

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

    def get_file_apt_dependencies(self, filename):
        """
        Returns a set of the apt dependencies for the specified *filename*.
        """
        with self._conn.begin():
            return {
                row['dependency']
                for row in self._conn.execute(
                    "SELECT dependency "
                    "FROM get_file_apt_dependencies(%s)", (filename,)
                )
            }

    def delete_build(self, package, version):
        """
        Remove all builds for the specified package and version, along with
        all files records.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (delete_build(%s, %s))", (package, version))

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
