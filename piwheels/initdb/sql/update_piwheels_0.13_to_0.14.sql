UPDATE configuration SET version = '0.14';

REVOKE UPDATE ON configuration FROM {username};

UPDATE packages SET skip = '' WHERE skip IS NULL;
ALTER packages ALTER COLUMN skip NOT NULL, ALTER COLUMN skip SET DEFAULT '';
REVOKE INSERT,UPDATE ON packages FROM {username};

UPDATE versions SET skip = '' WHERE skip IS NULL;
ALTER versions ALTER COLUMN skip NOT NULL, ALTER COLUMN skip SET DEFAULT '';
DROP INDEX versions_skip;
REVOKE INSERT,UPDATE ON versions FROM {username};

REVOKE INSERT,DELETE ON builds FROM {username};
REVOKE USAGE ON builds_build_id_seq FROM {username};

REVOKE INSERT ON output FROM {username};

CREATE INDEX files_packages ON files(package_tag);
REVOKE INSERT,UPDATE ON files FROM {username};

CREATE TABLE dependencies (
    filename            VARCHAR(255) NOT NULL,
    tool                VARCHAR(10) DEFAULT 'apt' NOT NULL,
    dependency          VARCHAR(255) NOT NULL,

    CONSTRAINT dependencies_pk PRIMARY KEY (filename, tool, dependency),
    CONSTRAINT dependencies_files_fk FOREIGN KEY (filename)
        REFERENCES files(filename) ON DELETE CASCADE,
    CONSTRAINT dependencies_tool_ck CHECK (tool IN ('apt', 'pip', ''))
);
GRANT SELECT,INSERT ON dependencies TO {username};

ALTER TABLE downloads DROP CONSTRAINT downloads_filename_fk;
REVOKE INSERT ON downloads FROM {username};

REVOKE INSERT ON searches FROM {username};

CREATE VIEW versions_detail AS
SELECT
    v.package,
    v.version,
    (p.skip <> '') or (v.skip <> '') AS skipped,
    COUNT(*) FILTER (WHERE b.status) AS builds_succeeded,
    COUNT(*) FILTER (WHERE NOT b.status) AS builds_failed
FROM
    packages p
    JOIN versions v ON p.package = v.package
    JOIN builds b ON v.package = b.package AND v.version = b.version
GROUP BY
    v.package,
    v.version,
    skipped;
GRANT SELECT ON versions_detail TO {username};

CREATE FUNCTION set_pypi_serial(new_serial INTEGER)
    RETURNS VOID
    LANGUAGE plpgsql
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
BEGIN
    IF (SELECT pypi_serial FROM configuration) > new_serial THEN
        RAISE EXCEPTION integrity_constraint_violation
            USING MESSAGE = 'pypi_serial number cannot go backwards';
    END IF;
    UPDATE configuration SET pypi_serial = new_serial WHERE id = 1;
END;
$sql$;
REVOKE ALL ON FUNCTION set_pypi_serial(INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION set_pypi_serial(INTEGER) TO {username};

CREATE FUNCTION add_new_package(package TEXT, skip TEXT = '')
    RETURNS BOOLEAN
    LANGUAGE plpgsql
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
BEGIN
    INSERT INTO packages (package, skip) VALUES (package, skip);
    RETURN true;
EXCEPTION
    WHEN unique_violation THEN RETURN false;
END;
$sql$;
REVOKE ALL ON FUNCTION add_new_package(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION add_new_package(TEXT, TEXT) TO {username};

CREATE FUNCTION add_new_package_version(
    package TEXT,
    version TEXT,
    released TIMESTAMP = NULL,
    skip TEXT = ''
)
    RETURNS BOOLEAN
    LANGUAGE plpgsql
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
BEGIN
    INSERT INTO versions (package, version, released, skip)
        VALUES (package, version, COALESCE(released, '1970-01-01 00:00:00'), skip);
    RETURN true;
EXCEPTION
    WHEN unique_violation THEN RETURN false;
END;
$sql$;
REVOKE ALL ON FUNCTION add_new_package_version(
    TEXT, TEXT, TIMESTAMP, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION add_new_package_version(
    TEXT, TEXT, TIMESTAMP, TEXT
    ) TO {username};

CREATE FUNCTION skip_package(package TEXT, reason TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE packages SET skip = reason WHERE package = package;
$sql$;
REVOKE ALL ON FUNCTION skip_package(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION skip_package(TEXT, TEXT) TO {username};

CREATE FUNCTION skip_package_version(package TEXT, version TEXT, reason TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE versions SET skip = reason
    WHERE package = package AND version = version;
$sql$;
REVOKE ALL ON FUNCTION skip_package_version(TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION skip_package_version(TEXT, TEXT, TEXT) TO {username};

CREATE FUNCTION log_download(
    filename TEXT,
    accessed_by INET,
    accessed_at TIMESTAMP,
    arch TEXT = NULL,
    distro_name TEXT = NULL,
    distro_version TEXT = NULL,
    os_name TEXT = NULL,
    os_version TEXT = NULL,
    py_name TEXT = NULL,
    py_version TEXT = NULL
)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    INSERT INTO downloads (
        filename,
        accessed_by,
        accessed_at,
        arch,
        distro_name,
        distro_version,
        os_name,
        os_version,
        py_name,
        py_version
    )
    VALUES (
        filename,
        accessed_by,
        accessed_at,
        arch,
        distro_name,
        distro_version,
        os_name,
        os_version,
        py_name,
        py_version
    );
$sql$;
REVOKE ALL ON FUNCTION log_download(
    TEXT, INET, TIMESTAMP,
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_download(
    TEXT, INET, TIMESTAMP,
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
    ) TO {username};

CREATE FUNCTION log_build_success(
    package TEXT,
    version TEXT,
    built_by INTEGER,
    duration INTERVAL,
    abi_tag TEXT,
    output TEXT,
    build_files files ARRAY,
    build_deps dependencies ARRAY
)
    RETURNS INTEGER
    LANGUAGE plpgsql
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
DECLARE
    new_build_id INTEGER;
BEGIN
    IF ARRAY_LENGTH(build_files, 1) = 0 THEN
        RAISE EXCEPTION integrity_constraint_violation
            USING MESSAGE = 'Successful build must include at least one file';
    END IF;
    INSERT INTO builds (
            package,
            version,
            built_by,
            duration,
            status,
            abi_tag
        )
        VALUES (
            package,
            version,
            built_by,
            duration,
            TRUE,
            abi_tag
        )
        RETURNING build_id
        INTO new_build_id;
    INSERT INTO output VALUES (new_build_id, output);
    -- We delete the existing entries from files rather than using INSERT..ON
    -- CONFLICT UPDATE because we need to delete dependencies associated with
    -- those files too. This is considerably simpler than a multi-layered
    -- upsert across tables.
    DELETE FROM files f
        USING UNNEST(build_files) AS b
        WHERE f.filename = b.filename;
    INSERT INTO files
        SELECT
            b.filename,
            new_build_id,
            b.filesize,
            b.filehash,
            b.package_tag,
            b.package_version_tag,
            b.py_version_tag,
            b.abi_tag,
            b.platform_tag
        FROM
            UNNEST(build_files) AS b;
    INSERT INTO dependencies
        SELECT
            d.filename,
            d.tool,
            d.dependency
        FROM
            UNNEST(build_deps) AS d;
    RETURN new_build_id;
END;
$sql$;
REVOKE ALL ON FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT, files ARRAY, dependencies ARRAY
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT, files ARRAY, dependencies ARRAY
    ) TO {username};

CREATE FUNCTION log_build_failure(
    package TEXT,
    version TEXT,
    built_by INTEGER,
    duration INTERVAL,
    abi_tag TEXT,
    output TEXT
)
    RETURNS INTEGER
    LANGUAGE plpgsql
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
DECLARE
    new_build_id INTEGER;
BEGIN
    INSERT INTO builds (
            package,
            version,
            built_by,
            duration,
            status,
            abi_tag
        )
        VALUES (
            package,
            version,
            built_by,
            duration,
            FALSE,
            abi_tag
        )
        RETURNING build_id
        INTO new_build_id;
    INSERT INTO output VALUES (new_build_id, output);
    RETURN new_build_id;
END;
$sql$;
REVOKE ALL ON FUNCTION log_build_failure(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_build_failure(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT
    ) TO {username};

CREATE FUNCTION delete_build(package TEXT, version TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    -- Foreign keys take care of the rest
    DELETE FROM builds WHERE package = package AND version = version;
$sql$;
REVOKE ALL ON FUNCTION delete_build(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_build(TEXT, TEXT) TO {username};

COMMIT;
