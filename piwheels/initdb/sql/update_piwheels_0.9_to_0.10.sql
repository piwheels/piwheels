UPDATE configuration SET version = '0.10';

GRANT SELECT ON configuration TO {username};
GRANT UPDATE ON packages TO {username};
GRANT UPDATE ON versions TO {username};
GRANT DELETE ON builds TO {username};
REVOKE DELETE ON versions FROM {username};

CREATE TABLE downloads (
    filename            VARCHAR(255) NOT NULL,
    accessed_by         INET NOT NULL,
    accessed_at         TIMESTAMP NOT NULL,
    arch                VARCHAR(100) DEFAULT NULL,
    distro_name         VARCHAR(100) DEFAULT NULL,
    distro_version      VARCHAR(100) DEFAULT NULL,
    os_name             VARCHAR(100) DEFAULT NULL,
    os_version          VARCHAR(100) DEFAULT NULL,
    py_name             VARCHAR(100) DEFAULT NULL,
    py_version          VARCHAR(100) DEFAULT NULL,

    CONSTRAINT downloads_filename_fk FOREIGN KEY (filename)
        REFERENCES files (filename) ON DELETE CASCADE
);

CREATE INDEX downloads_files ON downloads(filename);
CREATE INDEX downloads_accessed_at ON downloads(accessed_at DESC);
GRANT SELECT,INSERT ON downloads TO {username};

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
    ),
    download_stats AS (
        SELECT COUNT(*) AS downloads_last_month
        FROM downloads
        WHERE accessed_at > CURRENT_TIMESTAMP - INTERVAL '1 month'
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
        fs.builds_size,
        dl.downloads_last_month
    FROM
        package_stats p,
        version_stats v,
        build_pkgs bp,
        build_vers bv,
        build_stats bs,
        build_latest bl,
        file_count fc,
        file_stats fs,
        download_stats dl;

GRANT SELECT ON statistics TO {username};
