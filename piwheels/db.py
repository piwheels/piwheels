import psycopg2
from psycopg2.extras import DictCursor


class PiWheelsDatabase:
    def __init__(self, dbname, user, host, password):
        connect_str = "dbname='{}' user='{}' host='{}' password='{}'".format(
            dbname, user, host, password
        )
        self.conn = psycopg2.connect(connect_str)
        self.cursor = self.conn.cursor(cursor_factory=DictCursor)

    def log_build_run(self, *values):
        query = """
        INSERT INTO
            build_runs
        VALUES (
            now(),
            %s,
            %s,
            %s,
            %s
        )
        """
        self.cursor.execute(query, values)
        self.conn.commit()

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
            timestamp
            DESC
        LIMIT
            1
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0]


if __name__ == '__main__':
    from auth import *
    db = PiWheelsDatabase(dbname, user, host, password)
    result = db.get_last_package_built()
    print(result)
