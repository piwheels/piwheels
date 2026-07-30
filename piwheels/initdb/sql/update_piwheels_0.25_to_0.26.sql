UPDATE configuration SET version = '0.26';

ALTER TABLE files ADD COLUMN deleted_at TIMESTAMP DEFAULT NULL;

CREATE FUNCTION mark_file_deleted(fn TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE files
    SET deleted_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
    WHERE filename = fn
    AND deleted_at IS NULL;
$sql$;

REVOKE ALL ON FUNCTION mark_file_deleted(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mark_file_deleted(TEXT) TO {username};

DROP FUNCTION get_project_data(TEXT);

CREATE FUNCTION get_project_data(pkg TEXT)
    RETURNS JSON
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH abi_scores AS (
        SELECT
            v.version,
            b.build_id,
            CASE
                WHEN ba.abi_tag = b.abi_tag THEN
                CASE
                    -- Best case: builder of requested ABI produced compiled
                    -- file of requested ABI
                    WHEN b.status AND f.abi_tag = ba.abi_tag THEN 5
                    -- Good case: builder of expected ABI produced 'none' ABI
                    -- build
                    WHEN b.status AND f.abi_tag = 'none' THEN 4
                    WHEN b.status AND f.abi_tag = 'abi3' THEN 4
                    -- Builder of requested ABI produced failure
                    WHEN NOT b.status THEN 2
                    -- Builder of requested ABI succeeded but produced no
                    -- files (or files were overwritten by duplicate attempt)
                    WHEN b.status AND f.abi_tag is NULL THEN 1
                    -- Pending build for the requested ABI
                    WHEN b.status IS NULL THEN 0
                    -- Unexpected case
                    ELSE -2
                END
                ELSE
                CASE
                    -- Weird case: builder of different ABI produced compiled
                    -- file with requested ABI
                    WHEN b.status AND f.abi_tag = ba.abi_tag THEN 4
                    -- Good case: builder of unexpected ABI produced compatible
                    -- build
                    WHEN b.status AND f.abi_tag = 'none' THEN 3
                    WHEN b.status AND f.abi_tag = 'abi3' THEN 3
                    -- Skipped package/version with no build, or pending build
                    WHEN b.status IS NULL THEN 1
                    -- Irrelevant cases
                    WHEN b.status THEN -1
                    WHEN NOT b.status THEN -1
                    -- Unexpected case
                    ELSE -2
                END
            END AS score,
            CASE f.abi_tag
                WHEN 'none' THEN ba.abi_tag
                WHEN 'abi3' THEN ba.abi_tag
                ELSE COALESCE(f.abi_tag, b.abi_tag, ba.abi_tag)
            END AS calc_abi_tag,
            CASE
                -- Check for actual successful files first, so that imported
                -- wheels on skipped versions/packages show as success not skip
                WHEN b.status AND f.build_id IS NOT NULL
                    AND f.deleted_at IS NULL THEN 'success'
                WHEN p.skip <> '' THEN 'skip'
                WHEN v.skip <> '' THEN 'skip'
                -- Build succeeded and produced a file, but the file has since
                -- been removed from disk (e.g. cleaned up for never having
                -- been downloaded); the build itself still "counts" so the
                -- version isn't re-queued
                WHEN b.status AND f.build_id IS NOT NULL THEN 'deleted'
                WHEN NOT b.status THEN 'fail'
                WHEN b.build_id IS NULL THEN 'pending'
                ELSE 'error'
            END AS calc_status
        FROM
            packages p
            JOIN versions v USING (package)
            CROSS JOIN build_abis ba
            LEFT JOIN builds b
                ON b.package = v.package
                AND b.version = v.version
                -- TODO The <= comparison is *way* too simplisitic
                AND b.abi_tag <= ba.abi_tag
            LEFT JOIN files f USING (build_id)
        WHERE ba.skip = ''
        AND v.package = pkg
    ),
    abi_parts AS (
        SELECT
            abi_scores.*,
            ROW_NUMBER() OVER (
                PARTITION BY version, calc_abi_tag
                ORDER BY score DESC
            ) AS num
        FROM abi_scores
    ),
    abi_objects AS (
        SELECT
            version,
            json_object_agg(
                calc_abi_tag,
                json_build_object(
                    'status', calc_status,
                    'build_id', build_id
                )
            ) AS obj
        FROM abi_parts
        WHERE score >= 0
        AND num = 1
        GROUP BY version
    ),
    file_objects AS (
        SELECT
            b.version,
            json_object_agg(
                f.filename,
                json_build_object(
                    'location', f.location,
                    'hash', f.filehash,
                    'size', f.filesize,
                    'abi_builder', b.abi_tag,
                    'abi_file', f.abi_tag,
                    'platform', f.platform_tag,
                    'requires_python', f.requires_python,
                    'apt_dependencies', (
                        SELECT
                            COALESCE(json_agg(dependency), '{{}}')
                        FROM (
                            SELECT dependency
                            FROM dependencies
                            WHERE filename = f.filename AND tool = 'apt'
                            EXCEPT ALL
                            SELECT apt_package
                            FROM preinstalled_apt_packages
                            WHERE abi_tag = f.abi_tag
                        ) AS d
                    ),
                    'pip_dependencies', (
                        SELECT
                            COALESCE(json_agg(dependency), '{{}}')
                        FROM (
                            SELECT dependency
                            FROM dependencies
                            WHERE filename = f.filename AND tool = 'pip'
                        ) AS d
                    )
                )
            ) AS obj
        FROM files f
        JOIN builds b USING (build_id)
        WHERE b.package = pkg
        AND f.deleted_at IS NULL
        GROUP BY b.version
    )
    VALUES (
        json_build_object(
            'name', (
                SELECT name
                FROM package_names
                WHERE package = pkg
                ORDER BY seen DESC
                LIMIT 1
            ),
            'description', (
                SELECT description
                FROM packages
                WHERE package = pkg
            ),
            'releases', (
                SELECT COALESCE(json_object_agg(
                    v.version,
                    json_build_object(
                        'yanked', v.yanked,
                        'released', v.released AT TIME ZONE 'UTC',
                        'skip', COALESCE(NULLIF(v.skip, ''), p.skip),
                        'files', COALESCE(f.obj, '{{}}'),
                        'abis', COALESCE(a.obj, '{{}}')
                    )
                ), '{{}}')
                FROM
                    packages p
                    JOIN versions v USING (package)
                    LEFT JOIN file_objects f USING (version)
                    LEFT JOIN abi_objects a USING (version)
                WHERE p.package = pkg
            )
        )
    );
$sql$;

REVOKE ALL ON FUNCTION get_project_data(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_data(TEXT) TO {username};

DROP FUNCTION get_statistics();

CREATE FUNCTION get_statistics()
    RETURNS TABLE(
        builds_time            INTERVAL,
        builds_size            BIGINT,
        packages_built         INTEGER,
        files_count            INTEGER,
        new_last_hour          INTEGER,
        downloads_last_month   INTEGER,
        downloads_last_hour    INTEGER
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH build_stats AS (
        SELECT
            COALESCE(SUM(CASE
                -- This guards against including insanely huge durations as
                -- happens when a builder starts without NTP time sync and
                -- records a start time of 1970-01-01 and a completion time
                -- sometime this millennium...
                WHEN duration < INTERVAL '1 week' THEN duration
                ELSE INTERVAL '0'
            END), INTERVAL '0') AS builds_time
        FROM
            builds
    ),
    file_count AS (
        SELECT
            COUNT(*) AS files_count,
            COUNT(DISTINCT package_tag) AS packages_built
        FROM files
        WHERE deleted_at IS NULL
    ),
    file_stats AS (
        -- Exclude armv6l packages as they're just hard-links to armv7l
        -- packages and thus don't really count towards space used ... in most
        -- cases anyway. Also exclude deleted files, as they no longer occupy
        -- any space.
        SELECT COALESCE(SUM(filesize), 0) AS builds_size
        FROM files
        WHERE platform_tag <> 'linux_armv6l'
        AND deleted_at IS NULL
    ),
    download_stats AS (
        SELECT
            COUNT(*) AS downloads_last_month,
            COUNT(*) FILTER (
                WHERE accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
            ) AS downloads_last_hour
        FROM downloads
        WHERE accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
    ),
    version_stats AS (
        SELECT COUNT(*) AS new_last_hour
        FROM versions
        WHERE released > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    )
    SELECT
        bs.builds_time,
        fs.builds_size,
        CAST(fc.packages_built AS INTEGER),
        CAST(fc.files_count AS INTEGER),
        CAST(vs.new_last_hour AS INTEGER),
        CAST(dl.downloads_last_month AS INTEGER),
        CAST(dl.downloads_last_hour AS INTEGER)
    FROM
        build_stats bs,
        file_count fc,
        file_stats fs,
        version_stats vs,
        download_stats dl;
$sql$;

REVOKE ALL ON FUNCTION get_statistics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_statistics() TO {username};
