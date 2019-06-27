UPDATE configuration SET version = '0.15';

REVOKE ALL PRIVILEGES ON DATABASE {dbname} FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;
GRANT CONNECT, TEMP ON DATABASE {dbname} TO {username};
GRANT USAGE ON SCHEMA public TO {username};

-- Fix some historic screw-ups in the privileges
GRANT SELECT ON configuration TO {username};
REVOKE INSERT ON dependencies FROM {username};

DROP VIEW statistics;
DROP VIEW downloads_recent;
DROP VIEW versions_detail;

ALTER TABLE build_abis
    ADD COLUMN skip VARCHAR(100) DEFAULT '' NOT NULL;

DROP FUNCTION delete_build(TEXT, TEXT);
CREATE FUNCTION delete_build(pkg TEXT, ver TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    -- Foreign keys take care of the rest
    DELETE FROM builds b WHERE b.package = pkg AND b.version = ver;
$sql$;
REVOKE ALL ON FUNCTION delete_build(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_build(TEXT, TEXT) TO {username};

DROP FUNCTION skip_package(TEXT, TEXT);
CREATE FUNCTION skip_package(pkg TEXT, reason TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE packages SET skip = reason WHERE package = pkg;
$sql$;
REVOKE ALL ON FUNCTION skip_package(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION skip_package(TEXT, TEXT) TO {username};

DROP FUNCTION skip_package_version(TEXT, TEXT, TEXT);
CREATE FUNCTION skip_package_version(pkg TEXT, ver TEXT, reason TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE versions SET skip = reason
    WHERE package = pkg AND version = ver;
$sql$;
REVOKE ALL ON FUNCTION skip_package_version(TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION skip_package_version(TEXT, TEXT, TEXT) TO {username};

CREATE FUNCTION get_pypi_serial()
    RETURNS BIGINT
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT pypi_serial FROM configuration WHERE id = 1;
$sql$;
REVOKE ALL ON FUNCTION get_pypi_serial() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_pypi_serial() TO {username};

CREATE FUNCTION test_package(pkg TEXT)
    RETURNS BOOLEAN
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT COUNT(*) = 1 FROM packages p WHERE p.package = pkg;
$sql$;
REVOKE ALL ON FUNCTION test_package(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION test_package(TEXT) TO {username};

CREATE FUNCTION test_package_version(pkg TEXT, ver TEXT)
    RETURNS BOOLEAN
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT COUNT(*) = 1 FROM versions v
    WHERE v.package = pkg AND v.version = ver;
$sql$;
REVOKE ALL ON FUNCTION test_package_version(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION test_package_version(TEXT, TEXT) TO {username};

CREATE TABLE rewrites_pending (
    package        VARCHAR(200) NOT NULL,
    added_at       TIMESTAMP NOT NULL,
    command        VARCHAR(8) NOT NULL,

    CONSTRAINT rewrites_pending_pk PRIMARY KEY (package),
    CONSTRAINT rewrites_pending_package_fk FOREIGN KEY (package)
        REFERENCES packages (package) ON DELETE CASCADE,
    CONSTRAINT rewrites_pending_command_ck CHECK
        (command IN ('PKGPROJ', 'PKGBOTH'))
);
CREATE INDEX rewrites_pending_added ON rewrites_pending(added_at);
GRANT SELECT ON rewrites_pending TO {username};

DROP VIEW builds_pending;
CREATE VIEW builds_pending AS
-- Finally, because I can't write this in order due to postgres' annoying
-- materialization of CTEs, the same set as below but augmented with a per-ABI
-- build queue position, based on version release date, primarily for the
-- purposes of filtering
SELECT
    abi_tag,
    ROW_NUMBER() OVER (PARTITION BY abi_tag ORDER BY released) AS position,
    package,
    version
FROM
    (
        -- The set of package versions against each ABI for which they haven't
        -- been attempted and for which no covering "none" ABI wheel exists
        SELECT
            q.package,
            q.version,
            v.released,
            MIN(q.abi_tag) AS abi_tag
        FROM
            (
                -- The set of package versions X build ABIs that we want to
                -- exist once the queue is complete
                SELECT
                    v.package,
                    v.version,
                    b.abi_tag
                FROM
                    packages AS p
                    JOIN versions AS v ON v.package = p.package
                    CROSS JOIN build_abis AS b
                WHERE
                    v.skip = ''
                    AND p.skip = ''
                    AND b.skip = ''

                EXCEPT ALL

                (
                    -- The set of package versions that successfully produced
                    -- wheels with ABI "none", and which therefore count as
                    -- all build ABIs
                    SELECT
                        b.package,
                        b.version,
                        v.abi_tag
                    FROM
                        builds AS b
                        JOIN files AS f ON b.build_id = f.build_id
                        CROSS JOIN build_abis AS v
                    WHERE f.abi_tag = 'none'

                    UNION ALL

                    -- The set of package versions that successfully produced a
                    -- wheel with a single ABI (abi_tag <> 'none') or which
                    -- were attempted but failed (build_id IS NULL)
                    SELECT
                        b.package,
                        b.version,
                        COALESCE(f.abi_tag, b.abi_tag) AS abi_tag
                    FROM
                        builds AS b
                        LEFT JOIN files AS f ON b.build_id = f.build_id
                    WHERE
                        f.build_id IS NULL
                        OR f.abi_tag <> 'none'
                )
            ) AS q
            JOIN versions v ON q.package = v.package AND q.version = v.version
        GROUP BY
            q.package,
            q.version,
            v.released
    ) AS t;
GRANT SELECT ON builds_pending TO {username};

CREATE FUNCTION get_build_queue(lim INTEGER)
    RETURNS TABLE(
        abi_tag builds_pending.abi_tag%TYPE,
        package builds_pending.package%TYPE,
        version builds_pending.version%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT abi_tag, package, version
    FROM builds_pending
    WHERE position <= lim
    ORDER BY abi_tag, position;
$sql$;
REVOKE ALL ON FUNCTION get_build_queue(INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_build_queue(INTEGER) TO {username};

CREATE FUNCTION get_statistics()
    RETURNS TABLE(
        packages_built         INTEGER,
        builds_count           INTEGER,
        builds_count_success   INTEGER,
        builds_count_last_hour INTEGER,
        builds_time            INTERVAL,
        files_count            INTEGER,
        builds_size            BIGINT,
        downloads_last_month   INTEGER,
        downloads_all          INTEGER
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH build_stats AS (
        SELECT
            COUNT(*) AS builds_count,
            COUNT(*) FILTER (WHERE status) AS builds_count_success,
            COALESCE(SUM(CASE
                -- This guards against including insanely huge durations as
                -- happens when a builder starts without NTP time sync and
                -- records a start time of 1970-01-01 and a completion time
                -- sometime this millenium...
                WHEN duration < INTERVAL '1 week' THEN duration
                ELSE INTERVAL '0'
            END), INTERVAL '0') AS builds_time
        FROM
            builds
    ),
    build_latest AS (
        SELECT COUNT(*) AS builds_count_last_hour
        FROM builds
        WHERE built_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    ),
    file_count AS (
        SELECT
            COUNT(*) AS files_count,
            COUNT(DISTINCT package_tag) AS packages_built
        FROM files
    ),
    file_stats AS (
        -- Exclude armv6l packages as they're just hard-links to armv7l
        -- packages and thus don't really count towards space used ... in most
        -- cases anyway
        SELECT COALESCE(SUM(filesize), 0) AS builds_size
        FROM files
        WHERE platform_tag <> 'linux_armv6l'
    ),
    download_stats AS (
        SELECT
            COUNT(*) FILTER (
                WHERE accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
            ) AS downloads_last_month,
            COUNT(*) AS downloads_all
        FROM downloads
    )
    SELECT
        CAST(fc.packages_built AS INTEGER),
        CAST(bs.builds_count AS INTEGER),
        CAST(bs.builds_count_success AS INTEGER),
        CAST(bl.builds_count_last_hour AS INTEGER),
        bs.builds_time,
        CAST(fc.files_count AS INTEGER),
        fs.builds_size,
        CAST(dl.downloads_last_month AS INTEGER),
        CAST(dl.downloads_all AS INTEGER)
    FROM
        build_stats bs,
        build_latest bl,
        file_count fc,
        file_stats fs,
        download_stats dl;
$sql$;
REVOKE ALL ON FUNCTION get_statistics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_statistics() TO {username};

CREATE FUNCTION get_search_index()
    RETURNS TABLE(
        package packages.package%TYPE,
        downloads_recent INTEGER,
        downloads_all INTEGER
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        p.package,
        CAST(COALESCE(COUNT(d.filename) FILTER (
            WHERE d.accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
        ), 0) AS INTEGER) AS downloads_recent,
        CAST(COALESCE(COUNT(d.filename), 0) AS INTEGER) AS downloads_all
    FROM
        packages AS p
        LEFT JOIN (
            builds AS b
            JOIN files AS f ON b.build_id = f.build_id
            JOIN downloads AS d ON d.filename = f.filename
        ) ON p.package = b.package
    GROUP BY p.package;
$sql$;
REVOKE ALL ON FUNCTION get_search_index() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_search_index() TO {username};

CREATE FUNCTION get_package_files(pkg TEXT)
    RETURNS TABLE(
        filename files.filename%TYPE,
        filehash files.filehash%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT f.filename, f.filehash
    FROM builds b JOIN files f USING (build_id)
    WHERE b.status AND b.package = pkg;
$sql$;
REVOKE ALL ON FUNCTION get_package_files(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_package_files(TEXT) TO {username};

CREATE FUNCTION get_version_files(pkg TEXT, ver TEXT)
    RETURNS TABLE(
        filename files.filename%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT f.filename
    FROM builds b JOIN files f USING (build_id)
    WHERE b.status AND b.package = pkg AND b.version = ver;
$sql$;
REVOKE ALL ON FUNCTION get_version_files(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_version_files(TEXT, TEXT) TO {username};

CREATE FUNCTION get_project_versions(pkg TEXT)
    RETURNS TABLE(
        version versions.version%TYPE,
        skipped versions.skip%TYPE,
        builds_succeeded TEXT,
        builds_failed TEXT
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        v.version,
        COALESCE(NULLIF(v.skip, ''), p.skip) AS skipped,
        COALESCE(STRING_AGG(DISTINCT b.abi_tag, ', ') FILTER (WHERE b.status), '') AS builds_succeeded,
        COALESCE(STRING_AGG(DISTINCT b.abi_tag, ', ') FILTER (WHERE NOT b.status), '') AS builds_failed
    FROM
        packages p
        JOIN versions v USING (package)
        LEFT JOIN builds b USING (package, version)
    WHERE v.package = pkg
    GROUP BY version, skipped;
$sql$;
REVOKE ALL ON FUNCTION get_project_versions(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_versions(TEXT) TO {username};

CREATE FUNCTION get_project_files(pkg TEXT)
    RETURNS TABLE(
        version builds.version%TYPE,
        abi_tag files.abi_tag%TYPE,
        filename files.filename%TYPE,
        filesize files.filesize%TYPE,
        filehash files.filehash%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        b.version,
        f.abi_tag,
        f.filename,
        f.filesize,
        f.filehash
    FROM
        builds b
        JOIN files f USING (build_id)
    WHERE b.status
    AND b.package = pkg;
$sql$;
REVOKE ALL ON FUNCTION get_project_files(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_files(TEXT) TO {username};

CREATE FUNCTION get_file_dependencies(fn TEXT)
    RETURNS TABLE(
        tool dependencies.tool%TYPE,
        dependency dependencies.dependency%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        d.tool,
        d.dependency
    FROM dependencies d
    WHERE d.filename = fn
    ORDER BY tool, dependency;
$sql$;
REVOKE ALL ON FUNCTION get_file_dependencies(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_file_dependencies(TEXT) TO {username};

CREATE FUNCTION save_rewrites_pending(data rewrites_pending ARRAY)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    DELETE FROM rewrites_pending;
    INSERT INTO rewrites_pending (
        package,
        added_at,
        command
    )
        SELECT
            d.package,
            d.added_at,
            d.command
        FROM
            UNNEST(data) AS d;
$sql$;
REVOKE ALL ON FUNCTION save_rewrites_pending(rewrites_pending ARRAY) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION save_rewrites_pending(rewrites_pending ARRAY) TO {username};

CREATE FUNCTION load_rewrites_pending()
    RETURNS TABLE(
        package rewrites_pending.package%TYPE,
        added_at rewrites_pending.added_at%TYPE,
        command rewrites_pending.command%TYPE
    )
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT package, added_at, command
    FROM rewrites_pending
    ORDER BY added_at;
$sql$;
REVOKE ALL ON FUNCTION load_rewrites_pending() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION load_rewrites_pending() TO {username};

DROP FUNCTION log_build_success(TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT,
                                files ARRAY, dependencies ARRAY);
CREATE FUNCTION log_build_success(
    package TEXT,
    version TEXT,
    built_by INTEGER,
    duration INTERVAL,
    abi_tag TEXT,
    output TEXT,
    build_files files ARRAY,
    build_deps dependencies ARRAY
)
    RETURNS INTEGER
    LANGUAGE plpgsql
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
DECLARE
    new_build_id INTEGER;
BEGIN
    IF ARRAY_LENGTH(build_files, 1) = 0 THEN
        RAISE EXCEPTION integrity_constraint_violation
            USING MESSAGE = 'Successful build must include at least one file';
    END IF;
    INSERT INTO builds (
            package,
            version,
            built_by,
            duration,
            status,
            abi_tag
        )
        VALUES (
            package,
            version,
            built_by,
            duration,
            TRUE,
            abi_tag
        )
        RETURNING build_id
        INTO new_build_id;
    INSERT INTO output (build_id, output) VALUES (new_build_id, output);
    -- We delete the existing entries from files rather than using INSERT..ON
    -- CONFLICT UPDATE because we need to delete dependencies associated with
    -- those files too. This is considerably simpler than a multi-layered
    -- upsert across tables.
    DELETE FROM files f
        USING UNNEST(build_files) AS b
        WHERE f.filename = b.filename;
    INSERT INTO files (
        filename,
        build_id,
        filesize,
        filehash,
        package_tag,
        package_version_tag,
        py_version_tag,
        abi_tag,
        platform_tag
    )
        SELECT
            b.filename,
            new_build_id,
            b.filesize,
            b.filehash,
            b.package_tag,
            b.package_version_tag,
            b.py_version_tag,
            b.abi_tag,
            b.platform_tag
        FROM
            UNNEST(build_files) AS b;
    INSERT INTO dependencies (
        filename,
        tool,
        dependency
    )
        SELECT
            d.filename,
            d.tool,
            d.dependency
        FROM
            UNNEST(build_deps) AS d;
    RETURN new_build_id;
END;
$sql$;
REVOKE ALL ON FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT, files ARRAY, dependencies ARRAY
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT, files ARRAY, dependencies ARRAY
    ) TO {username};

DROP FUNCTION log_build_failure(TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT);
CREATE FUNCTION log_build_failure(
    package TEXT,
    version TEXT,
    built_by INTEGER,
    duration INTERVAL,
    abi_tag TEXT,
    output TEXT
)
    RETURNS INTEGER
    LANGUAGE plpgsql
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
DECLARE
    new_build_id INTEGER;
BEGIN
    INSERT INTO builds (
            package,
            version,
            built_by,
            duration,
            status,
            abi_tag
        )
        VALUES (
            package,
            version,
            built_by,
            duration,
            FALSE,
            abi_tag
        )
        RETURNING build_id
        INTO new_build_id;
    INSERT INTO output (build_id, output) VALUES (new_build_id, output);
    RETURN new_build_id;
END;
$sql$;
REVOKE ALL ON FUNCTION log_build_failure(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_build_failure(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT
    ) TO {username};

COMMIT;
