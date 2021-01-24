UPDATE configuration SET version = '0.20';

CREATE FUNCTION get_file_pip_dependencies(fn VARCHAR)
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
        AND tool = 'pip';
$sql$;

REVOKE ALL ON FUNCTION get_file_pip_dependencies(VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_file_pip_dependencies(VARCHAR) TO {username};

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
        apt_dependencies VARCHAR ARRAY,
        pip_dependencies VARCHAR ARRAY
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
        ARRAY_AGG(ad.dependency)
            FILTER (WHERE ad.dependency IS NOT NULL) AS apt_dependencies,
        ARRAY_AGG(pd.dependency)
            FILTER (WHERE pd.dependency IS NOT NULL) AS pip_dependencies
    FROM
        builds b
        JOIN files f USING (build_id)
        JOIN versions v USING (package, version)
        LEFT JOIN LATERAL (
            SELECT f.filename, d.dependency
            FROM get_file_apt_dependencies(f.filename) AS d
        ) ad USING (filename)
        LEFT JOIN LATERAL (
            SELECT f.filename, d.dependency
            FROM get_file_pip_dependencies(f.filename) AS d
        ) pd USING (filename)
    WHERE b.status
    AND b.package = pkg
    GROUP BY (
        version, platform_tag, builder_abi, file_abi_tag, filename, filesize,
        filehash, yanked, requires_python
    );
$sql$;

REVOKE ALL ON FUNCTION get_project_files(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_files(TEXT) TO {username};
