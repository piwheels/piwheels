UPDATE configuration SET version = '0.21';

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

CREATE FUNCTION get_initial_statistics()
    RETURNS TABLE(
        downloads_all          BIGINT
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        COUNT(*) AS downloads_all
    FROM downloads;
$sql$;

REVOKE ALL ON FUNCTION get_initial_statistics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_initial_statistics() TO {username};
