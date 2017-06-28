from tools import list_pypi_packages, get_package_versions

import os
import psycopg2
from psycopg2.extras import DictCursor


class PiWheelsDatabase:
    """
    PiWheels database connection bridge

    Store database credentials in environment variables: PW_DB, PW_USER,
    PW_HOST, PW_PASS.
    """
    def __init__(self):
        dbname = os.environ['PW_DB']
        user = os.environ['PW_USER']
        host = os.environ['PW_HOST']
        password = os.environ['PW_PASS']
        connect_str = "dbname='{}' user='{}' host='{}' password='{}'".format(
            dbname, user, host, password
        )
        self.conn = psycopg2.connect(connect_str)
        self.cursor = self.conn.cursor(cursor_factory=DictCursor)

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
        values = (package,)
        self.cursor.execute(query, values)
        self.conn.commit()

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
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

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
        values = (package, version)
        self.cursor.execute(query, values)
        self.conn.commit()

    def update_package_list(self):
        """
        Updates the list of known packages
        """
        pypi_packages = set(list_pypi_packages())
        known_packages = set(self.get_all_packages())
        missing_packages = pypi_packages.difference(known_packages)

        for package in missing_packages:
            self.add_new_package(package)

    def update_package_version_list(self):
        """
        Updates the list of known package versions
        """
        known_packages = self.get_all_packages()

        for package in known_packages:
            pypi_versions = set(get_package_versions(package))
            known_versions = set(self.get_package_versions(package))
            missing_versions = pypi_versions.difference(known_versions)

            for version in missing_versions:
                self.add_new_package_version(package, version)

    def get_total_number_of_package_versions(self):
        """
        Returns the total number of known package versions
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            package_versions
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

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
                platform_tag
            )
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        self.cursor.execute(query, values)
        self.conn.commit()

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
        self.cursor.execute(query)
        return self.cursor.fetchone()

    def get_all_packages(self):
        """
        Returns a list of all known packages
        """
        query = """
        SELECT
            package
        FROM
            packages
        ORDER BY
            package
        """
        self.cursor.execute(query)
        return self.cursor.fetchall()

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
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        return (result['package'] for result in results)

    def get_total_number_of_packages_with_versions(self):
        """
        Returns the number of packages which have published at least one version
        """
        query = """
        SELECT
            package
        FROM
            package_versions
        GROUP BY
            package
        """
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def get_build_queue(self):
        """
        Returns a list of package/version lists of all package versions
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
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def build_queue_generator(self):
        """
        Returns a generator yielding package/version lists from the build queue,
        one at a time
        """
        result = True
        while result:
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
            LIMIT
                1
            """
            self.cursor.execute(query)
            result = self.cursor.fetchone()
            if result:
                yield result

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
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

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
        values = (active,)
        self.cursor.execute(query, values)
        self.conn.commit()

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
        """
        values = (package,)
        self.cursor.execute(query, values)
        results = self.cursor.fetchall()
        return list(sorted(result[0] for result in results))

    ### untested methods

    def get_number_of_packages_processed_in_last_hour(self):
        query = """
        SELECT
            COUNT(*)
        FROM
            builds
        WHERE
            build_timestamp > NOW() - interval '1 hour'
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

    def get_total_number_of_packages_processed(self):
        """
        Legacy
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            (SELECT package FROM builds GROUP BY package) AS total
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

    def get_total_number_of_packages_successfully_built(self):
        """
        Legacy
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            (SELECT package FROM builds WHERE status GROUP BY package) AS total
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

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
        values = (package, )
        self.cursor.execute(query, values)
        result = self.cursor.fetchone()
        return result[0]

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
        values = (package, )
        self.cursor.execute(query, values)
        results = self.cursor.fetchall()
        return (result[0] for result in results)

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
        values = (package,)
        self.cursor.execute(query, values)
        return self.cursor.fetchall()

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
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

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
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]
