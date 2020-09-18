UPDATE configuration SET version = '0.19';

ALTER TABLE files
    ADD COLUMN requires_python VARCHAR(100) NULL;

DROP FUNCTION get_project_versions(TEXT);
CREATE FUNCTION get_project_versions(pkg TEXT)
    RETURNS TABLE(
        version versions.version%TYPE,
        yanked BOOLEAN,
        released TIMESTAMP WITH TIME ZONE,
        skip versions.skip%TYPE,
        builds_succeeded TEXT,
        builds_failed TEXT
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        v.version,
        v.yanked,
        v.released AT TIME ZONE 'UTC',
        COALESCE(NULLIF(v.skip, ''), p.skip) AS skip_msg,
        COALESCE(STRING_AGG(DISTINCT b.abi_tag, ',') FILTER (WHERE b.status), '') AS builds_succeeded,
        COALESCE(STRING_AGG(DISTINCT b.abi_tag, ',') FILTER (WHERE NOT b.status), '') AS builds_failed
    FROM
        packages p
        JOIN versions v USING (package)
        LEFT JOIN builds b USING (package, version)
    WHERE v.package = pkg
    GROUP BY version, skip_msg, released, yanked;
$sql$;

REVOKE ALL ON FUNCTION get_project_versions(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_versions(TEXT) TO {username};

DROP FUNCTION get_file_apt_dependencies(fn TEXT);
CREATE FUNCTION get_file_apt_dependencies(fn VARCHAR)
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

REVOKE ALL ON FUNCTION get_file_apt_dependencies(VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_file_apt_dependencies(VARCHAR) TO {username};

DROP FUNCTION get_project_files(TEXT);
CREATE FUNCTION get_project_files(pkg TEXT)
    RETURNS TABLE(
        version builds.version%TYPE,
        platform_tag files.platform_tag%TYPE,
        builder_abi builds.abi_tag%TYPE,
        file_abi_tag files.abi_tag%TYPE,
        filename files.filename%TYPE,
        filesize files.filesize%TYPE,
        filehash files.filehash%TYPE,
        yanked versions.yanked%TYPE,
        requires_python files.requires_python%TYPE,
        dependencies VARCHAR ARRAY
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        b.version,
        f.platform_tag,
        b.abi_tag AS builder_abi,
        f.abi_tag AS file_abi_tag,
        f.filename,
        f.filesize,
        f.filehash,
        v.yanked,
        f.requires_python,
        ARRAY_AGG(d.dependency)
            FILTER (WHERE d.dependency IS NOT NULL) AS dependencies
    FROM
        builds b
        JOIN files f USING (build_id)
        JOIN versions v USING (package, version)
        LEFT JOIN LATERAL (
            SELECT f.filename, d.dependency
            FROM get_file_apt_dependencies(f.filename) AS d
        ) d USING (filename)
    WHERE b.status
    AND b.package = pkg
    GROUP BY (
        version, platform_tag, builder_abi, file_abi_tag, filename, filesize,
        filehash, yanked, requires_python
    );
$sql$;

REVOKE ALL ON FUNCTION get_project_files(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_files(TEXT) TO {username};

DROP FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT, files ARRAY, dependencies ARRAY
);

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
    INSERT INTO output (build_id, output) VALUES (new_build_id, output);
    -- We delete the existing entries from files rather than using INSERT..ON
    -- CONFLICT UPDATE because we need to delete dependencies associated with
    -- those files too. This is considerably simpler than a multi-layered
    -- upsert across tables.
    DELETE FROM files f
        USING UNNEST(build_files) AS b
        WHERE f.filename = b.filename;
    INSERT INTO files (
        filename,
        build_id,
        filesize,
        filehash,
        package_tag,
        package_version_tag,
        py_version_tag,
        abi_tag,
        platform_tag,
        requires_python
    )
        SELECT
            b.filename,
            new_build_id,
            b.filesize,
            b.filehash,
            b.package_tag,
            b.package_version_tag,
            b.py_version_tag,
            b.abi_tag,
            b.platform_tag,
            b.requires_python
        FROM
            UNNEST(build_files) AS b;
    INSERT INTO dependencies (
        filename,
        tool,
        dependency
    )
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
