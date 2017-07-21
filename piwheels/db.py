from tools import list_pypi_packages, get_package_versions

import os
import psycopg2
import psycopg2.extensions
from psycopg2.extras import DictCursor


class NestedConnection(psycopg2.extensions.connection):
    """
    Derivative of psycopg2's connection object that, when used as a context
    manager, only commits/rolls back with the outer most level.

    A more nuanced implementation would use actual nested transactions (which
    Postgres does support), but I don't need them and I'm too lazy.
    """
    def __init__(self, dsn, **kwargs):
        super().__init__(dsn, **kwargs)
        self._nesting = 0

    def __enter__(self):
        self._nesting += 1
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        assert self._nesting > 0
        self._nesting -= 1
        if not self._nesting:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()


class PiWheelsDatabase:
    """
    PiWheels database connection class

    Store database credentials in environment variables: PW_DB, PW_USER,
    PW_HOST, PW_PASS.
    """
    def __init__(self):
        if 'PW_HOST' in os.environ:
            dsn = "dbname='{PW_DB}' user='{PW_USER}' host='{PW_HOST}' password='{PW_PASS}'"
        else:
            dsn = "dbname='{PW_DB}'"
        dsn = dsn.format(**os.environ)
        self.conn = psycopg2.connect(
            dsn, connection_factory=NestedConnection, cursor_factory=DictCursor)

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
        query = """
        INSERT INTO
            packages (package)
        VALUES
            (%s)
        """
        with self.conn:
            values = (package,)
            with self.conn.cursor() as cur:
                cur.execute(query, values)

    def get_total_number_of_packages(self):
        """
        Returns the total number of known packages
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            packages
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]

    def add_new_package_version(self, package, version):
        """
        Insert a new package version record into the database
        """
        query = """
        INSERT INTO
            package_versions (package, version)
        VALUES
            (%s, %s)
        """
        with self.conn:
            values = (package, version)
            with self.conn.cursor() as cur:
                cur.execute(query, values)

    def update_package_list(self):
        """
        Updates the list of known packages
        """
        pypi_packages = set(list_pypi_packages())
        known_packages = set(self.get_all_packages())
        missing_packages = pypi_packages.difference(known_packages)

        with self.conn:
            print('\n*** Adding {} new packages ***\n'.format(len(missing_packages)))
            for package in missing_packages:
                print('    Adding new package: {}'.format(package))
                self.add_new_package(package)
        print()

    def update_package_version_list(self):
        """
        Updates the list of known package versions
        """
        with self.conn:
            for package in self.get_all_packages():
                pypi_versions = set(get_package_versions(package))
                known_versions = set(self.get_package_versions(package))
                missing_versions = pypi_versions.difference(known_versions)

                if missing_versions:
                    print('Adding {} new versions for package {}'.format(
                        len(missing_versions), package
                    ))

                for version in missing_versions:
                    print('    Adding new package version: {} {}'.format(
                        package, version
                    ))
                    self.add_new_package_version(package, version)

    def get_total_packages(self):
        """
        Returns the total number of known packages
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            packages
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]

    def get_total_package_versions(self):
        """
        Returns the total number of known package versions
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            package_versions
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]

    def log_build(self, *values):
        """
        Log a build attempt in the database, including build output and wheel
        info if successful
        """
        query = """
        INSERT INTO
            builds (
                package, version, status, output, filename, filesize,
                build_time, package_version_tag, py_version_tag, abi_tag,
                platform_tag, built_by
            )
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        print('### Package {} {} build rc: {}'.format(*values))
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query, values)

    def get_last_package_processed(self):
        """
        Returns the name and build timestamp of the last package processed
        """
        query = """
        SELECT
            package,
            TO_CHAR(build_timestamp, 'DD Mon HH24:MI') as build_datetime
        FROM
            builds
        ORDER BY
            build_timestamp DESC
        LIMIT
            1
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()

    def get_all_packages(self):
        """
        Returns a generator of all known package names
        """
        query = """
        SELECT
            package
        FROM
            packages
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                for rec in cur:
                    yield rec['package']

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

    def get_builds_processed_in_last_hour(self):
        """
        Return the number of builds processed in the last hour
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            builds
        WHERE
            build_timestamp > NOW() - interval '1 hour'
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
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
            COUNT(*)
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
            COUNT(*)
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
        """
        with self.conn:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()[0]
