DROP TABLE IF EXISTS
    packages, package_versions, versions, builds, files, metadata;
DROP VIEW IF EXISTS
    statistics, builds_pending;

CREATE TABLE configuration (
    id INTEGER DEFAULT 1 NOT NULL,
    version VARCHAR(16) DEFAULT '0.6' NOT NULL,
    pypi_serial INTEGER DEFAULT 0 NOT NULL,

    CONSTRAINT config_pk PRIMARY KEY (id)
);
INSERT INTO configuration(id) VALUES (1);
GRANT UPDATE ON configuration TO piwheels;

CREATE TABLE packages (
    package VARCHAR(200) NOT NULL,
    skip    BOOLEAN DEFAULT false NOT NULL,

    CONSTRAINT packages_pk PRIMARY KEY (package)
);
GRANT SELECT,INSERT ON packages TO piwheels;

CREATE INDEX packages_skip ON packages(skip);

CREATE TABLE versions (
    package VARCHAR(200) NOT NULL,
    version VARCHAR(200) NOT NULL,
    skip    BOOLEAN DEFAULT false NOT NULL,

    CONSTRAINT versions_pk PRIMARY KEY (package, version),
    CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE RESTRICT
);
GRANT SELECT,INSERT ON versions TO piwheels;

CREATE INDEX versions_skip ON versions(skip);

CREATE TABLE builds (
    build_id        SERIAL NOT NULL,
    package         VARCHAR(200) NOT NULL,
    version         VARCHAR(200) NOT NULL,
    built_by        INTEGER NOT NULL,
    built_at        TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    duration        INTERVAL NOT NULL,
    status          BOOLEAN DEFAULT true NOT NULL,
    output          TEXT NOT NULL,

    CONSTRAINT builds_pk PRIMARY KEY (build_id),
    CONSTRAINT builds_unique UNIQUE (package, version, built_at, built_by),
    CONSTRAINT builds_versions_fk FOREIGN KEY (package, version)
        REFERENCES versions ON DELETE CASCADE,
    CONSTRAINT builds_built_by_ck CHECK (built_by >= 1)
);
GRANT SELECT,INSERT ON builds TO piwheels;

CREATE INDEX builds_timestamp ON builds(built_at DESC NULLS LAST);
CREATE INDEX builds_pkgver ON builds(package, version);

CREATE TABLE files (
    filename            VARCHAR(255) NOT NULL,
    build_id            INTEGER NOT NULL,
    filesize            INTEGER NOT NULL,
    filehash            CHAR(64) NOT NULL,
    package_version_tag VARCHAR(100) NOT NULL,
    py_version_tag      VARCHAR(100) NOT NULL,
    abi_tag             VARCHAR(100) NOT NULL,
    platform_tag        VARCHAR(100) NOT NULL,

    CONSTRAINT files_pk PRIMARY KEY (filename),
    CONSTRAINT files_builds_fk FOREIGN KEY (build_id)
        REFERENCES builds (build_id) ON DELETE CASCADE
);
GRANT SELECT,INSERT,UPDATE ON files TO piwheels;

CREATE INDEX files_builds ON files(build_id);
CREATE INDEX files_size ON files(filesize);

CREATE VIEW builds_pending AS
SELECT
    v.package,
    v.version
FROM
    packages p
    JOIN versions v ON v.package = p.package
    LEFT JOIN builds b ON v.package = b.package AND v.version = b.version
WHERE b.package IS NULL
    AND NOT v.skip
    AND NOT p.skip;

GRANT SELECT ON builds_pending TO piwheels;

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
build_stats AS (
    SELECT
        COUNT(DISTINCT b.package) AS packages_built,
        COUNT(DISTINCT (b.package, b.version)) AS versions_built,
        COUNT(*) AS builds_count,
        SUM(CASE b.status WHEN true THEN 1 ELSE 0 END) AS builds_count_success,
        SUM(CASE WHEN b.built_at > CURRENT_TIMESTAMP - INTERVAL '1 hour' THEN 1 ELSE 0 END) AS builds_count_last_hour,
        COALESCE(SUM(b.duration), INTERVAL '0') AS builds_time
    FROM
        packages p
        JOIN versions v ON v.package = p.package
        LEFT JOIN builds b ON v.package = b.package AND v.version = b.version
),
file_stats AS (
    SELECT
        COALESCE(SUM(filesize), 0) AS builds_size
    FROM
        files
    WHERE
        -- Exclude armv6l packages as they're just hard-links to armv7l packages
        -- and thus don't really count towards space used
        platform_tag <> 'linux_armv6l'
)
SELECT
    p.packages_count,
    b.packages_built,
    v.versions_count,
    b.versions_built,
    b.builds_count,
    b.builds_count_success,
    b.builds_count_last_hour,
    b.builds_time,
    f.builds_size
FROM
    package_stats p,
    version_stats v,
    build_stats b,
    file_stats f;

GRANT SELECT ON statistics TO piwheels;

COMMIT;
