REVOKE UPDATE,DELETE ON packages FROM {username};
REVOKE UPDATE,DELETE ON versions FROM {username};
REVOKE UPDATE,DELETE ON builds FROM {username};
REVOKE DELETE ON files FROM {username};

DROP INDEX files_pkgver;
CREATE INDEX files_builds ON files(build_id);

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

GRANT SELECT ON statistics TO {username};

INSERT INTO files (
    filename,
    build_id,
    filesize,
    filehash,
    package_version_tag,
    py_version_tag,
    abi_tag,
    platform_tag
)
SELECT
    regexp_replace(filename, 'linux_armv7l\.whl$', 'linux_armv6l.whl'),
    build_id,
    filesize,
    filehash,
    package_version_tag,
    py_version_tag,
    abi_tag,
    'linux_armv6l'
FROM files
WHERE platform_tag = 'linux_armv7l';
