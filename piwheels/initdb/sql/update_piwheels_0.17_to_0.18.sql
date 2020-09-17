UPDATE configuration SET version = '0.18';

DELETE FROM packages WHERE skip = 'deleted';
DELETE FROM versions WHERE skip = 'deleted';

CREATE TABLE package_names (
    package VARCHAR(200) NOT NULL,
    name    VARCHAR(200) NOT NULL,
    seen    TIMESTAMP DEFAULT '1970-01-01 00:00:00' NOT NULL,

    CONSTRAINT package_names_pk PRIMARY KEY (name)
);

CREATE INDEX package_names_package ON package_names(package, seen DESC);
GRANT SELECT ON package_names TO {username};

CREATE TEMPORARY TABLE source
AS
    SELECT
        regexp_replace(LOWER(p.package), '[_.-]+', '-', 'g') AS package,
        p.package AS name,
        COALESCE(MAX(v.released), '1970-01-01 00:00:00') AS seen
    FROM
        packages p
        LEFT JOIN versions v USING (package)
    GROUP BY package, name;

ALTER TABLE source ADD PRIMARY KEY (package, name);

CREATE TEMPORARY TABLE only_canon
AS
    SELECT package FROM source WHERE package = name
    EXCEPT
    SELECT package FROM source WHERE package <> name;

ALTER TABLE only_canon ADD PRIMARY KEY (package);

CREATE TEMPORARY TABLE only_non_canon
AS
    SELECT package FROM source WHERE package <> name
    EXCEPT
    SELECT package FROM source WHERE package = name;

ALTER TABLE only_non_canon ADD PRIMARY KEY (package);

CREATE TEMPORARY TABLE both_names
AS
    SELECT package FROM source
    EXCEPT (
        SELECT package FROM only_canon
        UNION ALL
        SELECT package FROM only_non_canon
    );

ALTER TABLE both_names ADD PRIMARY KEY (package);

INSERT INTO package_names
    SELECT s.package, s.name, s.seen
    FROM source s JOIN only_canon c USING (package)

    UNION

    SELECT s.package, s.name, s.seen
    FROM source s JOIN only_non_canon c USING (package)

    UNION

    SELECT s.package, s.package AS name, MIN(s.seen) AS seen
    FROM source s JOIN only_non_canon c USING (package)
    GROUP BY s.package

    UNION

    SELECT s.package, s.package AS name, MIN(s.seen) AS seen
    FROM source s JOIN both_names c USING (package)
    GROUP BY s.package

    UNION

    SELECT s.package, s.name, s.seen
    FROM source s JOIN both_names c USING (package)
    WHERE s.package <> s.name;

ALTER TABLE versions
    DROP CONSTRAINT versions_package_fk;

WITH dupes AS (
    SELECT s.package, v.version, MAX(released) AS last_release
    FROM versions v JOIN source s ON v.package = s.name
    GROUP BY s.package, v.version
    HAVING COUNT(*) > 1
)
DELETE FROM versions v
    USING source s, dupes d
    WHERE v.package = s.name
    AND s.package = d.package
    AND v.version = d.version
    AND v.released < d.last_release;

DELETE FROM versions v
    USING both_names c, source s
    WHERE v.package = s.name
    AND c.package = s.package
    AND s.package <> s.name;

ALTER TABLE builds
    DROP CONSTRAINT builds_versions_fk;

WITH dupes AS (
    SELECT s.package, MIN(p.package) AS min_package
    FROM packages p JOIN source s ON p.package = s.name
    GROUP BY s.package
    HAVING COUNT(*) > 1
)
DELETE FROM packages p
    USING source s, dupes d
    WHERE p.package = s.name
    AND s.package = d.package
    AND p.package > min_package
    AND p.package <> s.package;

DELETE FROM packages p
    USING both_names c, source s
    WHERE p.package = s.name
    AND c.package = s.package
    AND s.package <> s.name;

UPDATE packages
    SET package = regexp_replace(LOWER(package), '[_.-]+', '-', 'g')
    WHERE package <> regexp_replace(LOWER(package), '[_.-]+', '-', 'g');

UPDATE versions
    SET package = regexp_replace(LOWER(package), '[_.-]+', '-', 'g')
    WHERE package <> regexp_replace(LOWER(package), '[_.-]+', '-', 'g');

ALTER TABLE versions
    ADD CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE CASCADE;

UPDATE builds
    SET package = regexp_replace(LOWER(package), '[_.-]+', '-', 'g')
    WHERE package <> regexp_replace(LOWER(package), '[_.-]+', '-', 'g');

ALTER TABLE builds
    ADD CONSTRAINT builds_versions_fk FOREIGN KEY (package, version)
        REFERENCES versions ON DELETE CASCADE;

ALTER TABLE package_names
    ADD CONSTRAINT package_names_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE CASCADE;

CREATE FUNCTION add_package_name(
    canon_name TEXT,
    alt_name TEXT,
    last_seen TIMESTAMP
)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    INSERT INTO package_names (package, name, seen)
    VALUES (canon_name, alt_name, last_seen)
    ON CONFLICT (name) DO
        UPDATE SET seen = last_seen
$sql$;

REVOKE ALL ON FUNCTION add_package_name(TEXT, TEXT, TIMESTAMP) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION add_package_name(TEXT, TEXT, TIMESTAMP) TO {username};

CREATE FUNCTION get_project_display_name(pkg TEXT)
    RETURNS TEXT
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT name
    FROM package_names
    WHERE package = pkg
    ORDER BY seen DESC
    LIMIT 1
$sql$;

REVOKE ALL ON FUNCTION get_project_display_name(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_display_name(TEXT) TO {username};

CREATE FUNCTION get_package_aliases(pkg TEXT)
    RETURNS TABLE(
        name package_names.name%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT name
    FROM package_names
    WHERE package = pkg
    AND name != pkg
$sql$;

REVOKE ALL ON FUNCTION get_package_aliases(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_package_aliases(TEXT) TO {username};

UPDATE project_page_hits
SET package = regexp_replace(LOWER(package), '[_.-]+', '-', 'g');
