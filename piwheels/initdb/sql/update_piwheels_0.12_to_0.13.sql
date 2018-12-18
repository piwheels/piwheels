UPDATE configuration SET version = '0.13';

-- Drop all the views we're going to be re-building anyway and all the foreign
-- keys we're about to break
DROP VIEW builds_pending;
DROP VIEW statistics;
DROP VIEW downloads_recent;
ALTER TABLE builds DROP CONSTRAINT builds_versions_fk;
ALTER TABLE searches DROP CONSTRAINT packages_package_fk;

-- Create the newly structured packages and versions tables with no constraints
-- initially and fill them from the existing data
CREATE TABLE packages_new (
    package VARCHAR(200) NOT NULL,
    skip    VARCHAR(100) DEFAULT NULL
);

CREATE TABLE versions_new (
    package  VARCHAR(200) NOT NULL,
    version  VARCHAR(200) NOT NULL,
    released TIMESTAMP DEFAULT '1970-01-01 00:00:00' NOT NULL,
    skip     VARCHAR(100) DEFAULT NULL
);

INSERT INTO packages_new
SELECT package, CASE skip WHEN TRUE THEN 'skip requested' END AS skip
FROM packages;

INSERT INTO versions_new(package, version, skip)
SELECT package, version, CASE skip WHEN TRUE THEN 'binary only' END AS skip
FROM versions;

DROP TABLE versions;
DROP TABLE packages;

ALTER TABLE packages_new RENAME TO packages;
ALTER TABLE packages
    ADD CONSTRAINT packages_pk PRIMARY KEY (package);

ALTER TABLE versions_new RENAME TO versions;
ALTER TABLE versions
    ADD CONSTRAINT versions_pk PRIMARY KEY (package, version),
    ADD CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE RESTRICT;

GRANT SELECT,INSERT,UPDATE ON packages TO {username};
CREATE INDEX versions_package ON versions(package);
CREATE INDEX versions_skip ON versions((skip IS NULL), package);
GRANT SELECT,INSERT,UPDATE ON versions TO {username};

-- Finally, re-instate the foreign keys and views we removed
ALTER TABLE builds
    ADD CONSTRAINT builds_versions_fk FOREIGN KEY (package, version)
        REFERENCES versions ON DELETE CASCADE;
ALTER TABLE searches
    ADD CONSTRAINT searches_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE CASCADE;

CREATE VIEW builds_pending AS
SELECT
    package,
    version,
    MIN(abi_tag) AS abi_tag
FROM (
    SELECT
        v.package,
        v.version,
        b.abi_tag
    FROM
        packages AS p
        JOIN versions AS v ON v.package = p.package
        CROSS JOIN build_abis AS b
    WHERE
        v.skip IS NULL
        AND p.skip IS NULL

    EXCEPT ALL

    (
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
) AS t
GROUP BY
    package,
    version;

GRANT SELECT ON builds_pending TO {username};

CREATE VIEW statistics AS
    WITH package_stats AS (
        SELECT COUNT(*) AS packages_count
        FROM packages
        WHERE skip IS NULL
    ),
    version_stats AS (
        SELECT COUNT(*) AS versions_count
        FROM packages p JOIN versions v ON p.package = v.package
        WHERE p.skip IS NULL AND v.skip IS NULL
    ),
    build_vers AS (
        SELECT COUNT(*) AS versions_tried
        FROM (SELECT DISTINCT package, version FROM builds) AS t
    ),
    build_stats AS (
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

CREATE VIEW downloads_recent AS
SELECT
    p.package,
    COUNT(*) AS downloads
FROM
    packages AS p
    LEFT JOIN (
        builds AS b
        JOIN files AS f ON b.build_id = f.build_id
        JOIN downloads AS d ON d.filename = f.filename
    ) ON p.package = b.package
WHERE
    d.accessed_at IS NULL
    OR d.accessed_at > CURRENT_TIMESTAMP - INTERVAL '1 month'
GROUP BY p.package;

GRANT SELECT ON downloads_recent TO {username};

COMMIT;
