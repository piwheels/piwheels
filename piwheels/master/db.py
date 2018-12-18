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
from datetime import datetime, timedelta
from itertools import chain

from sqlalchemy import MetaData, Table, select, create_engine
from sqlalchemy.exc import IntegrityError, SAWarning

from .. import __version__


CONTROL_CHARS = {
    c: '?'
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
                # The following are views on the tables above
                self._builds_pending = Table(
                    'builds_pending', self._meta, autoload=True)
                self._statistics = Table(
                    'statistics', self._meta, autoload=True)
                self._downloads_recent = Table(
                    'downloads_recent', self._meta, autoload=True)
        except:
            self._conn.close()
            raise

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def add_new_package(self, package, skip=None):
        """
        Insert a new package record into the database. Returns True if the row
        was inserted successfully, or False if a key violation occurred.
        """
        with self._conn.begin():
            try:
                self._conn.execute(
                    self._packages.insert(),
                    package=package,
                    skip=skip
                )
            except IntegrityError:
                return False
            else:
                return True

    def add_new_package_version(self, package, version,
                                released=None, skip=None):
        """
        Insert a new package version record into the database. Returns True if
        the row was inserted successfully, or False if a key violation
        occurred.
        """
        with self._conn.begin():
            try:
                if released is None:
                    released = datetime.utcnow()
                self._conn.execute(
                    self._versions.insert(),
                    package=package,
                    version=version,
                    released=released,
                    skip=skip
                )
            except IntegrityError:
                return False
            else:
                return True

    def skip_package(self, package, reason):
        """
        Mark a package with a reason to prevent future builds of all versions
        (and all future versions).
        """
        with self._conn.begin():
            self._conn.execute(
                self._packages.update().
                where(self._packages.c.package == package),
                skip=reason
            )

    def skip_package_version(self, package, version, reason):
        """
        Mark a version of a package with a reason to prevent future build
        attempts.
        """
        with self._conn.begin():
            self._conn.execute(
                self._versions.update().
                where(self._versions.c.package == package).
                where(self._versions.c.version == version),
                skip=reason
            )

    def test_package_version(self, package, version):
        """
        Check whether *version* of *package* already exists in the database.
        Returns a boolean.
        """
        with self._conn.begin():
            return bool(self._conn.scalar(
                self._versions.select().
                where(self._versions.c.package == package).
                where(self._versions.c.version == version)
            ))

    def log_download(self, download):
        """
        Log a download in the database, including data derived from JSON in
        pip's user-agent.
        """
        with self._conn.begin():
            try:
                self._conn.execute(
                    self._downloads.insert(),
                    filename=download.filename,
                    accessed_by=download.host,
                    accessed_at=download.timestamp,
                    arch=download.arch,
                    distro_name=download.distro_name,
                    distro_version=download.distro_version,
                    os_name=download.os_name,
                    os_version=download.os_version,
                    py_name=download.py_name,
                    py_version=download.py_version,
                )
            except IntegrityError:
                return False
            else:
                return True

    def log_build(self, build):
        """
        Log a build attempt in the database, including build output and wheel
        info if successful
        """
        with self._conn.begin():
            build.logged(self._conn.scalar(
                self._builds.insert().returning(self._builds.c.build_id),
                package=build.package,
                version=build.version,
                abi_tag=build.abi_tag,
                built_by=build.slave_id,
                duration=timedelta(seconds=build.duration),
                status=build.status
            ))
            self._conn.execute(
                self._output.insert(),
                build_id=build.build_id,
                output=sanitize(build.output)
            )
            if build.status:
                for f in build.files.values():
                    self.log_file(build, f)

    def log_file(self, build, file):
        """
        Log a pending file transfer in the database, including file-size, hash,
        and various tags
        """
        # NOTE: This method is not exposed on TheOracle as it is only required
        # by log_build above
        with self._conn.begin():
            self._conn.execute(
                self._files.delete().
                where(self._files.c.filename == file.filename)
            )
            self._conn.execute(
                self._files.insert(),
                filename=file.filename,
                build_id=build.build_id,
                filesize=file.filesize,
                filehash=file.filehash,
                package_tag=file.package_tag,
                package_version_tag=file.package_version_tag,
                py_version_tag=file.py_version_tag,
                abi_tag=file.abi_tag,
                platform_tag=file.platform_tag
            )
            for tool, dependency in file.dependencies:
                self._conn.execute(
                    self._dependencies.insert(),
                    filename=file.filename,
                    tool=tool,
                    dependency=dependency
                )

    def get_build_abis(self):
        """
        Return the set of ABIs that the master should attempt to build
        """
        with self._conn.begin():
            return {
                rec.abi_tag
                for rec in self._conn.execute(self._build_abis.select())
            }

    def get_pypi_serial(self):
        """
        Return the serial number of the last PyPI event
        """
        with self._conn.begin():
            return self._conn.scalar(
                select([self._configuration.c.pypi_serial]).
                where(self._configuration.c.id == 1)
            )

    def set_pypi_serial(self, serial):
        """
        Update the serial number of the last PyPI event
        """
        with self._conn.begin():
            self._conn.execute(
                self._configuration.update().
                where(self._configuration.c.id == 1),
                pypi_serial=serial
            )

    def get_all_packages(self):
        """
        Returns the set of all known package names
        """
        with self._conn.begin():
            return {
                rec.package
                for rec in self._conn.execute(self._packages.select())
            }

    def get_all_package_versions(self):
        """
        Returns the set of all known (package, version) tuples
        """
        with self._conn.begin():
            return {
                (rec.package, rec.version)
                for rec in self._conn.execute(self._versions.select())
            }

    def get_build_queue(self):
        """
        Returns a generator covering the entire builds_pending view; streaming
        results are activated for this query as it's more important to get the
        first result quickly than it is to retrieve the entire set.
        """
        # NOTE: This method is not exposed on TheOracle as it is only used by
        # TheArchitect task
        with self._conn.begin():
            for row in self._conn.\
                    execution_options(stream_results=True).\
                    execute(self._builds_pending.select()):
                yield row

    def get_statistics(self):
        """
        Return various build related statistics from the database (see the
        definition of the ``statistics`` view in the database creation script
        for more information.
        """
        with self._conn.begin():
            return self._conn.execute(self._statistics.select()).first()

    def get_downloads_recent(self):
        """
        Return a mapping of all packages to their download count for the last
        month. This is used to construct the searchable package index.
        """
        with self._conn.begin():
            return {
                rec.package: rec.downloads
                for rec in self._conn.execute(self._downloads_recent.select())
            }

    def get_package_files(self, package):
        """
        Returns all details required to build the index.html for the specified
        package.
        """
        with self._conn.begin():
            return self._conn.execute(
                select([self._files.c.filename, self._files.c.filehash]).
                select_from(self._builds.join(self._files)).
                where(self._builds.c.status).
                where(self._builds.c.package == package)
            )

    def get_version_files(self, package, version):
        """
        Returns the names of all files for *version* of *package*
        """
        with self._conn.begin():
            return {
                rec.filename
                for rec in self._conn.execute(
                    select([self._files.c.filename]).
                    select_from(self._builds.join(self._files)).
                    where(self._builds.c.status).
                    where(self._builds.c.package == package).
                    where(self._builds.c.version == version)
                )
            }

    def get_version_skip(self, package, version):
        """
        Returns the reason for skipping *version* of *package*
        """
        with self._conn.begin():
            return self._conn.scalar(
                select([self._versions.c.skip]).
                where(self._versions.c.package == package).
                where(self._versions.c.version == version)
            )

    def delete_build(self, package, version):
        """
        Remove all builds for the specified package and version, along with
        all files and download records
        """
        with self._conn.begin():
            self._conn.execute(
                self._builds.delete().
                where(self._builds.c.package == package).
                where(self._builds.c.version == version)
            )
