import os

from sqlalchemy import MetaData, Table, func

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
        self.conn.close()

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

    def update_package_version_list(self):
        """
        Updates the list of known package versions
        """
        with self.conn.begin():
            for package in self.get_all_packages():
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
                select([func.count('*')]).select_from(self.packages)
            )

    def get_total_package_versions(self):
        """
        Returns the total number of known package versions
        """
        with self.conn.begin():
            return self.conn.scalar(
                select([func.count('*')]).select_from(self.versions)
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
                package=build.package, version=build.version,
                built_at=build.build_time, built_by=build.built_by
            )
            build_id, = result.fetchone()
            if build.status:
                self.conn.execute(
                    self.files.insert(),
                    filename=build.filename, build_id=build_id,
                    filesize=build.filesize, filehash=build.filehash,
                    package_version_tag=build.package_version_tag,
                    py_version_tag=build.py_version_tag, abi_tag=build.abi_tag,
                    platform_tag=build.platform_tag)

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
            for package in self.conn.execute(select([self.packages.c.package])):
                yield package

    def get_total_number_of_packages_with_versions(self):
        """
        Returns the number of packages which have published at least one version
        """
        query = """
        SELECT DISTINCT
            package
        FROM
            package_versions
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()

    def get_build_queue(self):
        """
        Generator yielding package/version tuples of all package versions
        requiring building
        """
        query = """
        SELECT
            pv.package, pv.version
        FROM
            builds b
        RIGHT JOIN
            package_versions pv
        ON
            b.package = pv.package
        AND
            b.version = pv.version
        WHERE
            b.build_id IS NULL
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                for rec in cur:
                    yield rec['package'], rec['version']

    def build_active(self):
        """
        Checks whether the build is set to active. Returns True if active,
        otherwise False
        """
        query = """
        SELECT
            value
        FROM
            metadata
        WHERE
            key = 'active'
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]

    def _set_build_active_status(self, active=True):
        """
        Sets the build status
        """
        query = """
        UPDATE
            metadata
        SET
            value = %s
        WHERE
            key = 'active'
        """
        with self.conn:
            with self.conn.cursor() as cur:
                values = (active,)
                cur.execute(query, values)

    def activate_build(self):
        """
        Sets the build status to active
        """
        self._set_build_active_status(active=True)

    def deactivate_build(self):
        """
        Sets the build status to inactive
        """
        self._set_build_active_status(active=False)

    def get_package_versions(self, package):
        """
        Returns a list of all known versions of a given package
        """
        query = """
        SELECT
            version
        FROM
            package_versions
        WHERE
            package = %s
        ORDER BY
            version
        """
        with self.conn:
            with self.conn.cursor() as cur:
                values = (package,)
                cur.execute(query, values)
                return [rec[0] for rec in cur]

    ### untested methods

    def get_builds_processed_in_interval(self, interval):
        """
        Return the number of builds processed in a given interval.

        e.g. db.get_builds_processed_in_interval('1 hour')
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            builds
        WHERE
            build_timestamp > NOW() - interval %s
        """
        values = (interval, )
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query, values)
                return cur.fetchone()[0]

    def get_total_packages_processed(self):
        """
        Returns the total number of packages processed
        """
        query = """
        SELECT
            COUNT(DISTINCT package)
        FROM
            builds
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]

    def get_total_package_versions_processed(self):
        """
        Returns the total number of package versions processed
        """
        query = """
        SELECT
            COUNT(DISTINCT (package, version))
        FROM
            builds
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]

    def get_total_successful_builds(self):
        """
        Returns the total number of successful builds
        """
        query = """
        SELECT
            COUNT(DISTINCT (package, version))
        FROM
            builds
        WHERE
            status
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]

    def get_package_build_status(self, package):
        """
        Legacy
        """
        query = """
        SELECT
            status
        FROM
            builds
        WHERE
            package = %s
        ORDER BY
            build_timestamp DESC
        LIMIT
            1
        """
        with self.conn:
            with self.conn.cursor() as cur:
                values = (package, )
                cur.execute(query, values)
                return cur.fetchone()[0]

    def get_package_wheels(self, package):
        """
        Legacy
        """
        query = """
        SELECT
            filename
        FROM
            builds
        WHERE
            package = %s
        ORDER BY
            build_timestamp DESC
        """
        with self.conn:
            with self.conn.cursor() as cur:
                values = (package, )
                cur.execute(query, values)
                return [rec[0] for rec in cur]

    def get_package_output(self, package):
        """
        Legacy
        """
        query = """
        SELECT
            TO_CHAR(build_timestamp, 'YY-MM-DD HH24:MI') as build_datetime,
            status, output
        FROM
            builds
        WHERE
            package = %s
        ORDER BY
            build_timestamp DESC
        """
        with self.conn:
            with self.conn.cursor() as cur:
                values = (package,)
                cur.execute(query, values)
                return cur.fetchall()

    def get_total_build_time(self):
        """
        Legacy
        """
        query = """
        SELECT
            SUM(build_time)
        FROM
            builds
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]

    def get_total_wheel_filesize(self):
        """
        Legacy
        """
        query = """
        SELECT
            SUM(filesize)
        FROM
            builds
        WHERE
            status
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]
