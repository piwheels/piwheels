import os
import psycopg2
from psycopg2.extras import DictCursor


class PiWheelsDatabase:
    """
    PiWheels database connection bridge

    Pass in DB credentials directly or store in environment variables: PW_DB,
    PW_USER, PW_HOST, PW_PASS.
    """
    def __init__(self, dbname=None, user=None, host=None, password=None):
        if dbname is None:
            dbname = os.environ['PW_DB']
        if user is None:
            user = os.environ['PW_USER']
        if host is None:
            host = os.environ['PW_HOST']
        if password is None:
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
                build_time, py_version_tag, abi_tag, platform_tag
            )
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        self.cursor.execute(query, values)
        self.conn.commit()

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

    def get_last_package_processed(self):
        """
        Legacy
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
        values = (package, )
        self.cursor.execute(query, values)
        return self.cursor.fetchall()

    def _get_packages_by_build_status(self, build_status=None):
        """
        Legacy
        """
        where_clause = {
            True: 'status',
            False: 'NOT status',
            None: '1',
        }[build_status]
        query = """
        SELECT
            package
        FROM
            builds
        WHERE
            {}
        ORDER BY
            package
        """.format(where_clause)
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        return results

    def get_all_packages(self):
        """
        Legacy
        """
        return self._get_packages_by_build_status()

    def get_built_packages(self):
        """
        Legacy
        """
        return self._get_packages_by_build_status(True)

    def get_failed_packages(self):
        """
        Legacy
        """
        return self._get_packages_by_build_status(False)

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
            package_versions pv
        LEFT JOIN
            builds b
        ON
            b.package = pv.package
        WHERE
            b.package IS NULL
        """
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def get_previously_failed_packages(self):
        """
        Legacy
        """
        query = """
        SELECT
            package
        FROM
            builds
        WHERE NOT
            status
        """
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        return (result['package'] for result in results)

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

    def wheel_is_processed(self, wheel):
        """
        Sets the build status
        """
        query = """
        SELECT
            COUNT(*)
        FROM
            builds
        WHERE
            filename = %s
        """
        values = (wheel,)
        self.cursor.execute(query, values)
        result = self.cursor.fetchone()
        print(wheel, result)
        return result[0] == 1

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

    def get_package_version(self, package):
        query = """
        SELECT
            version
        FROM
            packages
        WHERE
            package = %s
        """
        values = (package,)
        self.cursor.execute(query, values)
        result = self.cursor.fetchone()
        return result['version']

    def get_packages_with_update_available(self):
        query = """
        SELECT
            package
        FROM
            packages
        WHERE
            update_required
        """
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        return (result['package'] for result in results)


if __name__ == '__main__':
    from auth import dbname, user, host, password
    db = PiWheelsDatabase(dbname, user, host, password)
