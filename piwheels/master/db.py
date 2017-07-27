import os
import logging

from sqlalchemy import MetaData, Table, select, func, text, distinct
from sqlalchemy.exc import DBAPIError

from . import pypi


class PiWheelsDatabase:
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

    def update_package_list(self):
        """
        Updates the list of known packages
        """
        pypi_packages = set(pypi.get_all_packages())
        known_packages = set(self.get_all_packages())
        missing_packages = pypi_packages - known_packages

        with self.conn.begin():
            logging.info('Adding %d new packages', len(missing_packages))
            for package in missing_packages:
                logging.info('    Adding new package: %s', package)
                self.add_new_package(package)

    def update_package_version_list(self, package):
        """
        Updates the list of known package versions for the specified package
        """
        with self.conn.begin():
            pypi_versions = set(pypi.get_package_versions(package))
            known_versions = set(self.get_package_versions(package))
            missing_versions = pypi_versions - known_versions

            if missing_versions:
                logging.info('Adding %d new versions for package %s',
                                len(missing_versions), package)

                for version in missing_versions:
                    logging.info('    Adding new package version: %s %s',
                                    package, version)
                    self.add_new_package_version(package, version)

    def get_total_packages(self):
        """
        Returns the total number of known packages
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.count('*')]).
                select_from(self.packages)
            )

    def get_total_package_versions(self):
        """
        Returns the total number of known package versions
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.count('*')]).
                select_from(self.versions)
            )

    def log_build(self, build):
        """
        Log a build attempt in the database, including build output and wheel
        info if successful
        """
        logging.info('Package %s %s %s',
                     ('failed', 'built')[build.status], build.package, build.version)
        with self.conn.begin():
            result = self.conn.execute(
                self.builds.insert().returning(self.builds.c.build_id),
                package=build.package,
                version=build.version,
                built_by=build.built_by,
                duration=build.duration
            )
            build_id, = result.fetchone()
            if build.status:
                try:
                    with self.conn.begin_nested():
                        self.conn.execute(
                            self.files.insert(),
                            filename=build.filename,
                            build_id=build_id,
                            filesize=build.filesize,
                            filehash=build.filehash,
                            package_version_tag=build.package_version_tag,
                            py_version_tag=build.py_version_tag,
                            abi_tag=build.abi_tag,
                            platform_tag=build.platform_tag
                        )
                except DBAPIError:
                    self.conn.execute(
                        self.files.update().where(filename=build.filename),
                        build_id=build_id,
                        filesize=build.filesize,
                        filehash=build.filehash,
                        package_version_tag=build.package_version_tag,
                        py_version_tag=build.py_version_tag,
                        abi_tag=build.abi_tag,
                        platform_tag=build.platform_tag
                    )


    def get_last_package_processed(self):
        """
        Returns the name and build timestamp of the last package processed
        """
        with self.conn.begin():
            return self.conn.execute(
                select([self.builds.c.package, self.builds.c.built_at]).
                order_by(self.builds.c.built_at.desc()).limit(1)
            ).fetchone()

    def get_all_packages(self):
        """
        Returns a generator of all known package names
        """
        with self.conn.begin():
            for rec in self.conn.execute(
                select([self.packages.c.package])
            ):
                yield rec.package

    def get_total_number_of_packages_with_versions(self):
        """
        Returns the number of packages which have published at least one version
        """
        with self.conn.begin():
            return self.conn.execute(
                select([self.versions.c.package]).distinct()
            ).fetchall()

    def get_build_queue(self):
        """
        Generator yielding package/version tuples of all package versions
        requiring building
        """
        with self.conn.begin():
            for rec in self.conn.execute(
                select([self.versions.c.package, self.versions.c.version]).
                select_from(self.versions.outerjoin(self.builds)).
                where(self.builds.c.package == None)
            ):
                yield rec.package, rec.version

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

    def get_builds_processed_in_interval(self, interval):
        """
        Return the number of builds processed in a given interval.

        e.g. db.get_builds_processed_in_interval('1 hour')
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.count('*')]).
                select_from(self.builds).
                where(self.builds.c.built_at > text("NOW() - INTERVAL '1 HOUR'"))
            )

    def get_total_packages_processed(self):
        """
        Returns the total number of packages processed
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.count(distinct(self.builds.c.package))])
            )

    def get_total_package_versions_processed(self):
        """
        Returns the total number of package versions processed
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.count('*')]).
                select_from(self.builds)
            )

    def get_total_successful_builds(self):
        """
        Returns the total number of successful builds
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.count('*')]).
                select_from(self.builds).
                where(self.builds.c.status)
            )

    def get_package_build_status(self, package):
        """
        Legacy
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([self.builds.c.status]).
                where(self.builds.c.package == package).
                order_by(self.builds.c.built_at.desc()).
                limit(1)
            )

    def get_package_wheels(self, package):
        """
        Legacy
        """
        with self.conn.begin():
            result = self.conn.execute(
                select([self.builds.c.filename]).
                where(self.builds.c.package == package).
                where(self.builds.c.filename != None).
                order_by(self.builds.c.built_at.desc())
            )
            return [rec.filename for rec in result]

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

    def get_total_build_time(self):
        """
        Legacy
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.sum(self.builds.c.duration)])
            )

    def get_total_wheel_filesize(self):
        """
        Legacy
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.sum(self.files.c.filesize)])
            )
