UPDATE configuration SET version = '0.18';

CREATE TABLE package_names (
    package VARCHAR(200) NOT NULL,
    name    VARCHAR(200) NOT NULL,
    seen    TIMESTAMP DEFAULT '1970-01-01 00:00:00' NOT NULL,

    CONSTRAINT package_names_pk PRIMARY KEY (name),
    CONSTRAINT package_names_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE CASCADE
);

CREATE INDEX package_names_package ON package_names(package, seen DESC);
GRANT SELECT ON package_names TO {username};

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
