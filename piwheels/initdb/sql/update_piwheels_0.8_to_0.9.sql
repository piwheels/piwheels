UPDATE configuration SET version = '0.9';

DROP INDEX packages_skip;

DROP INDEX versions_skip;
CREATE INDEX versions_skip ON versions(skip, package);

CREATE TABLE output (
    build_id        INTEGER NOT NULL,
    output          TEXT NOT NULL,

    CONSTRAINT output_pk PRIMARY KEY (build_id),
    CONSTRAINT output_builds_fk FOREIGN KEY (build_id)
        REFERENCES builds (build_id) ON DELETE CASCADE
);

INSERT INTO output SELECT build_id, output FROM builds;

GRANT SELECT,INSERT ON output TO {username};

ALTER TABLE builds
    DROP COLUMN output,
    ADD COLUMN abi_tag VARCHAR(100) NOT NULL DEFAULT '';

ALTER TABLE builds
    DROP CONSTRAINT builds_built_by_ck,
    ADD CONSTRAINT builds_built_by_ck CHECK (built_by >= 0);

-- Set all extant builds as having been performed for the "first" build_abi
WITH default_tag AS (
    SELECT abi_tag
    FROM build_abis
    ORDER BY abi_tag
    LIMIT 1
)
UPDATE builds SET abi_tag = d.abi_tag
FROM default_tag AS d;

ALTER TABLE builds
    ALTER COLUMN abi_tag DROP DEFAULT;

-- Try and refine the tags for successful builds with associated files which
-- have a matching abi_tag in the build_abis table (can't rely on matching
-- py_version_tag - it's *way* too variable in files)
WITH build_abi_tags AS (
    SELECT
        b.build_id,
        f.abi_tag
    FROM
        builds AS b
        JOIN files AS f ON b.build_id = f.build_id
        JOIN build_abis AS a ON f.abi_tag = a.abi_tag
    WHERE f.platform_tag <> 'linux_armv6l'
)
UPDATE builds AS b SET abi_tag = d.abi_tag
FROM build_abi_tags AS d
WHERE b.build_id = d.build_id;

CREATE INDEX builds_pkgverabi ON builds(build_id, package, version, abi_tag);

DROP INDEX files_abi;
CREATE INDEX files_abi ON files(build_id, abi_tag);

DROP VIEW builds_pending;
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
        NOT v.skip
        AND NOT p.skip

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
