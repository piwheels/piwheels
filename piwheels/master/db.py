import os
import logging
from datetime import timedelta

from sqlalchemy import MetaData, Table, select, func, text, distinct
from sqlalchemy.exc import DBAPIError

from . import pypi


class Database():
    """
    PiWheels database connection class
    """
    def __init__(self, engine):
        self.conn = engine.connect()
        self.meta = MetaData(bind=self.conn)
        self.packages = Table('packages', self.meta, autoload=True)
        self.versions = Table('versions', self.meta, autoload=True)
        self.builds = Table('builds', self.meta, autoload=True)
        self.files = Table('files', self.meta, autoload=True)
        # The following are views on the tables above
        self.builds_pending = Table('builds_pending', self.meta, autoload=True)
        self.statistics = Table('statistics', self.meta, autoload=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    def close(self):
        """
        Explicitly close the database connection
        """
        self.conn.close()

    def add_new_package(self, package):
        """
        Insert a new package record into the database
        """
        with self.conn.begin():
            self.conn.execute(
                self.packages.insert(),
                package=package
            )

    def add_new_package_version(self, package, version):
        """
        Insert a new package version record into the database
        """
        with self.conn.begin():
            self.conn.execute(
                self.versions.insert(),
                package=package, version=version
            )

    def update_package_list(self, packages):
        """
        Merges *packages* (an iterable of package names) into the known set of
        packages.
        """
        known_packages = set(self.get_all_packages())
        missing_packages = packages - known_packages

        if missing_packages:
            logging.info('Adding %d new packages', len(missing_packages))

            with self.conn.begin():
                for package in missing_packages:
                    if len(package) > 200:
                        logging.warning('Ignoring stupid package name: %s', package)
                    else:
                        self.add_new_package(package)

    def update_package_version_list(self, package, versions):
        """
        Merges *versions* (an iterable of version strings) into the known set
        of versions of *package* (a package name).
        """
        known_versions = set(self.get_package_versions(package))
        missing_versions = versions - known_versions

        if missing_versions:
            with self.conn.begin():
                logging.info('Adding new versions for package %s: %s',
                             package, ', '.join(missing_versions))

                for version in missing_versions:
                    if len(version) > 200:
                        logging.warning('Ignoring stupid version: %s', version)
                    else:
                        self.add_new_package_version(package, version)

    def log_build(self, build):
        """
        Log a build attempt in the database, including build output and wheel
        info if successful
        """
        with self.conn.begin():
            build.logged(self.conn.scalar(
                self.builds.insert().returning(self.builds.c.build_id),
                package=build.package,
                version=build.version,
                built_by=build.slave_id,
                duration=timedelta(seconds=build.duration),
                output=build.output,
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
        with self.conn.begin():
            try:
                with self.conn.begin_nested():
                    self.conn.execute(
                        self.files.insert(),

                        filename=file.filename,
                        build_id=build.build_id,
                        filesize=file.filesize,
                        filehash=file.filehash,
                        package_version_tag=file.package_version_tag,
                        py_version_tag=file.py_version_tag,
                        abi_tag=file.abi_tag,
                        platform_tag=file.platform_tag
                    )
            except DBAPIError:
                self.conn.execute(
                    self.files.update().
                    where(self.files.c.filename == file.filename),

                    build_id=build.build_id,
                    filesize=file.filesize,
                    filehash=file.filehash,
                    package_version_tag=file.package_version_tag,
                    py_version_tag=file.py_version_tag,
                    abi_tag=file.abi_tag,
                    platform_tag=file.platform_tag
                )

    def get_all_packages(self):
        """
        Returns a list of all known package names
        """
        with self.conn.begin():
            return [rec.package for rec in self.conn.execute(select([self.packages]))]

    def get_build_queue(self):
        """
        Generator yielding package/version tuples of all package versions
        requiring building
        """
        with self.conn.begin():
            for rec in self.conn.execute(select([self.builds_pending])):
                yield rec.package, rec.version

    def get_statistics(self):
        """
        Return various build related statistics from the database (see the
        definition of the ``statistics`` view in the database creation script
        for more information.
        """
        with self.conn.begin():
            for rec in self.conn.execute(select([self.statistics])):
                return rec

    def get_build(self, build_id):
        """
        Return all details about a given build.
        """
        with self.conn.begin():
            return self.conn.execute(
                select([self.builds]).
                where(self.builds.c.build_id == build_id)
            )

    def get_files(self, build_id):
        """
        Return all details about the files generated by a given build.
        """
        with self.conn.begin():
            return self.conn.execute(
                select([self.files]).
                where(self.files.c.build_id == build_id)
            )

    def get_package_files(self, package):
        """
        Returns all details required to build the index.html for the specified
        package.
        """
        with self.conn.begin():
            return self.conn.execute(
                select([self.files.c.filename, self.files.c.filehash]).
                select_from(self.builds.join(self.files)).
                where(self.builds.c.status).
                where(self.builds.c.package == package)
            )

    def get_package_versions(self, package):
        """
        Returns a list of all known versions of a given package
        """
        with self.conn.begin():
            result = self.conn.execute(
                select([self.versions.c.version]).
                where(self.versions.c.package == package).
                order_by(self.versions.c.version)
            )
            return [rec.version for rec in result]

    def get_package_output(self, package):
        """
        Legacy
        """
        with self.conn.begin():
            return self.conn.execute(
                select([self.builds.c.built_at, self.builds.c.status, self.builds.c.output]).
                where(self.builds.c.package == package).
                order_by(self.builds.c.built_at.desc())
            ).fetchall()

