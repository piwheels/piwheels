UPDATE configuration SET version = '0.9';

CREATE TABLE output (
    build_id        INTEGER NOT NULL,
    output          TEXT NOT NULL,

    CONSTRAINT output_pk PRIMARY KEY (build_id),
    CONSTRAINT output_builds_fk FOREIGN KEY (build_id)
        REFERENCES builds (build_id) ON DELETE CASCADE
);

INSERT INTO output SELECT build_id, output FROM builds;

GRANT INSERT ON output TO piwheels;

ALTER TABLE builds
    DROP COLUMN output,
    ADD COLUMN abi_tag VARCHAR(100) NOT NULL DEFAULT '';

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
