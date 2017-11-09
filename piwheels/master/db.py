"""
This module defines the low level database API. This is a simple core
SQLAlchemy affair which runs trivial queries against the PostgreSQL database.
All the serious logic is defined within views in the database itself.
"""

import warnings
from datetime import timedelta
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
        self._meta = MetaData(bind=self._conn)
        with warnings.catch_warnings():
            # Ignore warnings about partial indexes (SQLAlchemy doesn't know
            # how to reflect them but that doesn't matter for our purposes as
            # we're not doing DDL translation)
            warnings.simplefilter('ignore', category=SAWarning)
            self._configuration = Table('configuration', self._meta,
                                        autoload=True)
            with self._conn.begin():
                def close(self):
                    super().close()
                    self.db.close()

                db_version = self._conn.scalar(
                    select([self._configuration.c.version])
                )
                if db_version != __version__:
                    raise RuntimeError('Database version (%s) does not match '
                                       'software version (%s)' %
                                       (db_version, __version__))
            self._packages = Table('packages', self._meta, autoload=True)
            self._versions = Table('versions', self._meta, autoload=True)
            self._builds = Table('builds', self._meta, autoload=True)
            self._output = Table('output', self._meta, autoload=True)
            self._files = Table('files', self._meta, autoload=True)
            self._build_abis = Table('build_abis', self._meta, autoload=True)
            # The following are views on the tables above
            self._builds_pending = Table('builds_pending', self._meta,
                                         autoload=True)
            self._statistics = Table('statistics', self._meta, autoload=True)

    def add_new_package(self, package):
        """
        Insert a new package record into the database. Key violations are
        ignored as packages is effectively an append-only table.
        """
        with self._conn.begin():
            try:
                self._conn.execute(
                    self._packages.insert(),
                    package=package
                )
            except IntegrityError:
                return False
            else:
                return True

    def add_new_package_version(self, package, version):
        """
        Insert a new package version record into the database. Key violations
        are ignored as versions is effectively an append-only table.
        """
        with self._conn.begin():
            try:
                self._conn.execute(
                    self._versions.insert(),
                    package=package, version=version
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
                built_by=build.slave_id,
                duration=timedelta(seconds=build.duration),
                output=sanitize(build.output),
                status=build.status
            ))
            if build.status:
                for f in build.files.values():
                    self.log_file(build, f)

    def log_file(self, build, file):
        """
        Log a pending file transfer in the database, including file-size, hash,
        and various tags
        """
        with self._conn.begin():
            try:
                with self._conn.begin_nested():
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
            except IntegrityError:
                self._conn.execute(
                    self._files.update().
                    where(self._files.c.filename == file.filename),

                    build_id=build.build_id,
                    filesize=file.filesize,
                    filehash=file.filehash,
                    package_tag=file.package_tag,
                    package_version_tag=file.package_version_tag,
                    py_version_tag=file.py_version_tag,
                    abi_tag=file.abi_tag,
                    platform_tag=file.platform_tag
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
            for rec in self._conn.execute(self._statistics.select()):
                return rec

    def get_build(self, build_id):
        """
        Return all details about a given build.
        """
        with self._conn.begin():
            return self._conn.execute(
                self._builds.select().
                where(self._builds.c.build_id == build_id)
            )

    def get_files(self, build_id):
        """
        Return all details about the files generated by a given build.
        """
        with self._conn.begin():
            return self._conn.execute(
                self._files.select().
                where(self._files.c.build_id == build_id)
            )

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

    def get_package_versions(self, package):
        """
        Returns the set of all known versions of a given package
        """
        with self._conn.begin():
            result = self._conn.execute(
                select([self._versions.c.version]).
                where(self._versions.c.package == package).
                order_by(self._versions.c.version)
            )
            return {rec.version for rec in result}
