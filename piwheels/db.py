import psycopg2
from psycopg2.extras import DictCursor


class PiWheelsDatabase:
    def __init__(self, dbname, user, host, password):
        connect_str = "dbname='{}' user='{}' host='{}' password='{}'".format(
            dbname, user, host, password
        )
        self.conn = psycopg2.connect(connect_str)
        self.cursor = self.conn.cursor(cursor_factory=DictCursor)

    def log_build(self, *values):
        query = """
        INSERT INTO
            builds
        VALUES (
            now(),
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        """
        self.cursor.execute(query, values)
        self.conn.commit()

    def get_package_summary(self):
        query = """
        SELECT
            COUNT(CASE WHEN status THEN 1 END) as success,
            COUNT(CASE WHEN NOT status THEN 1 END) as fail,
            COUNT(*) as total
        FROM
            builds
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result

    def get_last_package_built(self):
        query = """
        SELECT
            package
        FROM
            builds
        ORDER BY
            build_timestamp
            DESC
        LIMIT
            1
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

    def _get_packages_by_build_status(self, build_status=None):
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
        return self._get_packages_by_build_status()

    def get_built_packages(self):
        return self._get_packages_by_build_status(True)

    def get_failed_packages(self):
        return self._get_packages_by_build_status(False)

    def get_total_build_time(self):
        query = """
        SELECT
            SUM(build_time)
        FROM
            builds
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

    def get_longest_build(self):
        query = """
        SELECT
            package, build_time
        FROM
            builds
        ORDER BY
            build_time DESC
        LIMIT
            1
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result

    def get_total_wheel_filesize(self):
        query = """
        SELECT
            SUM(filesize)
        FROM
            builds
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]

    def add_new_package(self, package, version):
        query = """
        INSERT INTO
            packages
        VALUES (
            %s,
            %s
        )
        """
        values = (package, version)
        self.cursor.execute(query, values)
        self.conn.commit()

    def update_package_version(self, package, version):
        query = """
        UPDATE
            packages
        SET
            version = %s
        WHERE
            package = %s
        """
        values = (version, package)
        self.cursor.execute(query, values)
        self.conn.commit()

    def get_all_packages(self):
        query = """
        SELECT
            package
        FROM
            packages
        """
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        return (result['package'] for result in results)

    def get_unattempted_packages(self):
        query = """
        SELECT
            package
        FROM
            packages
        WHERE
            package
        NOT IN
            (SELECT package FROM builds)
        ORDER BY
            package
        """
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        return (result['package'] for result in results)

    def get_previously_failed_packages(self):
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

    def set_build_active_status(self, active=True):
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
        self.set_build_active_status(active=True)

    def deactivate_build(self):
        self.set_build_active_status(active=False)

    def wheel_is_processed(self, wheel):
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
        return result[0] == 1


if __name__ == '__main__':
    from auth import dbname, user, host, password
    db = PiWheelsDatabase(dbname, user, host, password)
    print(db.build_active())
