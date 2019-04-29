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
CONTROL_CHARS = {
    c: '?'
    for c in chain(
        range(0x00, 0x09),
        range(0x0e, 0x20),
        [0x0b, 0x7f]
    )
}


ProjectVersionsRow = namedtuple('ProjectVersionsRow', (
    'version', 'skipped', 'builds_succeeded', 'builds_failed'))
ProjectFilesRow = namedtuple('ProjectFilesRow', (
    'version', 'abi_tag', 'filename', 'filesize', 'filehash'))


def sanitize(s):
    """
    A small routine for sanitizing the sometimes crazy stuff that winds up in
    build log output...
    """
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

    def add_new_package(self, package, skip=''):
        """
        Insert a new package record into the database. Returns True if the row
        was inserted successfully, or False if a key violation occurred.
        """
        with self._conn.begin():
            return self._conn.execute(
                "VALUES (add_new_package(%s, %s))", (package, skip)).scalar()

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

    def test_package(self, package):
        """
        Check whether *package* already exists in the database. Returns a
        boolean.
        """
        with self._conn.begin():
            return bool(self._conn.scalar(
                "VALUES (test_package(%s))", (package,)
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

    def log_download(self, download):
        """
        Log a download in the database, including data derived from JSON in
        pip's user-agent.
        """
        with self._conn.begin():
            self._conn.execute(
                "VALUES (log_download(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s))",
                (
                    download.filename,
                    download.host,
                    download.timestamp.astimezone(UTC).replace(tzinfo=None),
                    download.arch,
                    download.distro_name,
                    download.distro_version,
                    download.os_name,
                    download.os_version,
                    download.py_name,
                    download.py_version,
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
                        build.output,
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
                        build.output,
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
            return dict(
                self._conn.execute(
                    "SELECT * FROM get_statistics()"
                ).first().items()
            )

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
                    "SELECT version, skipped, builds_succeeded, builds_failed "
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
                    "SELECT version, abi_tag, filename, filesize, filehash "
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

    def get_file_dependencies(self, filename):
        """
        Returns the dependencies for the specified *filename* as a map of
        tool names to dependency sets.
        """
        with self._conn.begin():
            return {
                tool: {row.dependency for row in rows}
                for tool, rows in groupby(
                    self._conn.execute(
                        "SELECT tool, dependency "
                        "FROM get_file_dependencies(%s)", (filename,)
                    ),
                    key=attrgetter('tool')
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
