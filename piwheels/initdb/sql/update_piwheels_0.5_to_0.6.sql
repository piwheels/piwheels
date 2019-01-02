CREATE TABLE configuration (
    id INTEGER DEFAULT 1 NOT NULL,
    version VARCHAR(16) DEFAULT '0.6' NOT NULL,
    pypi_serial BIGINT DEFAULT 0 NOT NULL,

    CONSTRAINT config_pk PRIMARY KEY (id)
);
INSERT INTO configuration(id) VALUES (1);
GRANT UPDATE ON configuration TO {username};

DROP INDEX packages_skip;
CREATE INDEX packages_skip ON packages(package) WHERE NOT skip;

DROP INDEX versions_skip;
CREATE INDEX versions_package ON versions(package);
CREATE INDEX versions_skip ON versions(package, version) WHERE NOT skip;
GRANT DELETE ON versions TO {username};

CREATE TABLE build_abis (
    abi_tag         VARCHAR(100) NOT NULL,

    CONSTRAINT build_abis_pk PRIMARY KEY (abi_tag),
    CONSTRAINT build_abis_none_ck CHECK (abi_tag <> 'none')
);
GRANT SELECT ON build_abis TO {username};

CREATE INDEX builds_pkgverid ON builds(build_id, package, version);

DROP VIEW builds_pending;
DROP VIEW statistics;

CREATE TABLE files2 (
    filename            VARCHAR(255) NOT NULL,
    build_id            INTEGER NOT NULL,
    filesize            INTEGER NOT NULL,
    filehash            CHAR(64) NOT NULL,
    package_tag         VARCHAR(200) NOT NULL,
    package_version_tag VARCHAR(200) NOT NULL,
    py_version_tag      VARCHAR(100) NOT NULL,
    abi_tag             VARCHAR(100) NOT NULL,
    platform_tag        VARCHAR(100) NOT NULL
);
INSERT INTO files2 (
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
    filename,
    build_id,
    filesize,
    filehash,
    regexp_replace(filename, '([^-]*)-.*$', E'\\1'),
    package_version_tag,
    py_version_tag,
    abi_tag,
    platform_tag
FROM files;
DROP TABLE files;
ALTER TABLE files2 RENAME TO files;
ALTER TABLE files
    ADD CONSTRAINT files_pk PRIMARY KEY (filename),
    ADD CONSTRAINT files_builds_fk FOREIGN KEY (build_id)
        REFERENCES builds (build_id) ON DELETE CASCADE;
CREATE INDEX files_builds ON files(build_id);
CREATE INDEX files_size ON files(platform_tag, filesize) WHERE platform_tag <> 'linux_armv6l';
CREATE INDEX files_abi ON files(build_id, abi_tag) WHERE abi_tag <> 'none';
GRANT SELECT ON files TO {username};

CREATE VIEW builds_pending AS
    SELECT
        v.package,
        v.version,
        a.abi_tag
    FROM
        packages AS p
        JOIN versions AS v
            ON v.package = p.package
        LEFT JOIN builds AS b
            ON  v.package = b.package
            AND v.version = b.version
        CROSS JOIN (
            SELECT MIN(abi_tag) AS abi_tag
            FROM build_abis
        ) AS a
    WHERE b.version IS NULL
    AND   NOT v.skip
    AND   NOT p.skip

    UNION ALL

    SELECT DISTINCT
        b.package,
        b.version,
        a.abi_tag
    FROM
        builds AS b
        JOIN files AS f
            ON b.build_id = f.build_id
        CROSS JOIN build_abis AS a
    WHERE f.abi_tag <> 'none'
    AND   f.abi_tag <> a.abi_tag;

GRANT SELECT ON builds_pending TO {username};

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
    build_pkgs AS (
        SELECT COUNT(*) AS packages_built
        FROM (SELECT DISTINCT package FROM builds) AS t
    ),
    build_vers AS (
        SELECT COUNT(*) AS versions_built
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
        bv.versions_built,
        bs.builds_count,
        bs.builds_count_success,
        bl.builds_count_last_hour,
        bs.builds_time,
        f.builds_size
    FROM
        package_stats p,
        version_stats v,
        build_pkgs bp,
        build_vers bv,
        build_stats bs,
        build_latest bl,
        file_stats f;

GRANT SELECT ON statistics TO {username};

-- Data fix-ups

UPDATE files
    SET platform_tag = regexp_replace(platform_tag, '^(.*)\.whl$', E'\\1')
    WHERE platform_tag ~ '\.whl$';
UPDATE files
    SET abi_tag = 'none'
    WHERE abi_tag = 'noabi';
