UPDATE configuration SET version = '0.8';

DROP VIEW statistics;
CREATE VIEW statistics AS
    WITH package_stats AS (
        SELECT COUNT(*) AS packages_count
        FROM packages
        WHERE NOT skip
    ),
    version_stats AS (
        SELECT COUNT(*) AS versions_count
        FROM packages p JOIN versions v ON p.package = v.package
        WHERE NOT p.skip AND NOT v.skip
    ),
    build_vers AS (
        SELECT COUNT(*) AS versions_tried
        FROM (SELECT DISTINCT package, version FROM builds) AS t
    ),
    build_stats AS (
        SELECT
            COUNT(*) AS builds_count,
            COUNT(*) FILTER (WHERE status) AS builds_count_success,
            COALESCE(SUM(duration), INTERVAL '0') AS builds_time
        FROM
            builds
    ),
    build_latest AS (
        SELECT COUNT(*) AS builds_count_last_hour
        FROM builds
        WHERE built_at > CURRENT_TIMESTAMP - INTERVAL '1 hour'
    ),
    build_pkgs AS (
        SELECT COUNT(*) AS packages_built
        FROM (
            SELECT DISTINCT package
            FROM builds b JOIN files f ON b.build_id = f.build_id
            WHERE b.status
        ) AS t
    ),
    file_count AS (
        SELECT COUNT(*) AS files_count
        FROM files
    ),
    file_stats AS (
        -- Exclude armv6l packages as they're just hard-links to armv7l packages
        -- and thus don't really count towards space used
        SELECT COALESCE(SUM(filesize), 0) AS builds_size
        FROM files
        WHERE platform_tag <> 'linux_armv6l'
    )
    SELECT
        p.packages_count,
        bp.packages_built,
        v.versions_count,
        bv.versions_tried,
        bs.builds_count,
        bs.builds_count_success,
        bl.builds_count_last_hour,
        bs.builds_time,
        fc.files_count,
        fs.builds_size
    FROM
        package_stats p,
        version_stats v,
        build_pkgs bp,
        build_vers bv,
        build_stats bs,
        build_latest bl,
        file_count fc,
        file_stats fs;

GRANT SELECT ON statistics TO {username};
