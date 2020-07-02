UPDATE configuration SET version = '0.17';

ALTER TABLE packages
    ADD COLUMN description VARCHAR(200) DEFAULT '' NOT NULL;

CREATE TABLE preinstalled_apt_packages (
    abi_tag        VARCHAR(100) NOT NULL,
    apt_package    VARCHAR(255) NOT NULL,

    CONSTRAINT preinstalled_apt_packages_pk PRIMARY KEY (abi_tag, apt_package),
    CONSTRAINT preinstalled_apt_packages_abi_tag_fk FOREIGN KEY (abi_tag)
        REFERENCES build_abis (abi_tag) ON DELETE CASCADE
);

CREATE INDEX preinstalled_apt_packages_abi_tag ON preinstalled_apt_packages(abi_tag);
GRANT SELECT ON preinstalled_apt_packages TO {username};

DROP FUNCTION get_file_dependencies(TEXT);

CREATE FUNCTION get_file_apt_dependencies(fn TEXT)
    RETURNS TABLE(
        dependency dependencies.dependency%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT dependency
        FROM dependencies
        WHERE filename = fn
        AND tool = 'apt'
    EXCEPT ALL
    SELECT apt_package
        FROM preinstalled_apt_packages p
        JOIN files f
        ON p.abi_tag = f.abi_tag
        WHERE f.filename = fn;
$sql$;

REVOKE ALL ON FUNCTION get_file_apt_dependencies(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_file_apt_dependencies(TEXT) TO {username};

CREATE FUNCTION update_project_description(pkg TEXT, dsc TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE packages
    SET description = dsc
    WHERE package = pkg;
$sql$;

REVOKE ALL ON FUNCTION update_project_description(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION update_project_description(TEXT, TEXT) TO {username};

CREATE FUNCTION get_project_description(pkg TEXT)
    RETURNS TEXT
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT description
    FROM packages
    WHERE package = pkg;
$sql$;

REVOKE ALL ON FUNCTION get_project_description(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_description(TEXT) TO {username};
