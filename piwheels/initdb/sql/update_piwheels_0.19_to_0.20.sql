UPDATE configuration SET version = '0.20';

DROP FUNCTION get_project_display_name(TEXT);
DROP FUNCTION get_package_description(TEXT);
DROP FUNCTION get_project_files(TEXT);
DROP FUNCTION get_project_versions(TEXT);
DROP FUNCTION get_file_apt_dependencies(VARCHAR);

CREATE FUNCTION get_project_data(pkg TEXT)
    RETURNS JSON
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH abi_scores AS (
        SELECT
            v.version,
            b.build_id,
            CASE
                WHEN ba.abi_tag = b.abi_tag THEN
                CASE
                    -- Best case: builder of requested ABI produced compiled
                    -- file of requested ABI
                    WHEN b.status AND f.abi_tag = ba.abi_tag THEN 5
                    -- Good case: builder of expected ABI produced 'none' ABI
                    -- build
                    WHEN b.status AND f.abi_tag = 'none' THEN 4
                    WHEN b.status AND f.abi_tag = 'abi3' THEN 4
                    -- Builder of requested ABI produced failure
                    WHEN NOT b.status THEN 2
                    -- Builder of requested ABI succeeded but produced no
                    -- files (or files were overwritten by duplicate attempt)
                    WHEN b.status AND f.abi_tag is NULL THEN 1
                    -- Pending build for the requested ABI
                    WHEN b.status IS NULL THEN 0
                    -- Unexpected case
                    ELSE -2
                END
                ELSE
                CASE
                    -- Weird case: builder of different ABI produced compiled
                    -- file with requested ABI
                    WHEN b.status AND f.abi_tag = ba.abi_tag THEN 4
                    -- Good case: builder of unexpected ABI produced compatible
                    -- build
                    WHEN b.status AND f.abi_tag = 'none' THEN 3
                    WHEN b.status AND f.abi_tag = 'abi3' THEN 3
                    -- Skipped package/version with no build, or pending build
                    WHEN b.status IS NULL THEN 1
                    -- Irrelevant cases
                    WHEN b.status THEN -1
                    WHEN NOT b.status THEN -1
                    -- Unexpected case
                    ELSE -2
                END
            END AS score,
            CASE f.abi_tag
                WHEN 'none' THEN ba.abi_tag
                WHEN 'abi3' THEN ba.abi_tag
                ELSE COALESCE(f.abi_tag, b.abi_tag, ba.abi_tag)
            END AS calc_abi_tag,
            CASE
                WHEN p.skip <> '' THEN 'skip'
                WHEN v.skip <> '' THEN 'skip'
                WHEN b.status AND f.build_id IS NOT NULL THEN 'success'
                WHEN NOT b.status THEN 'fail'
                WHEN b.build_id IS NULL THEN 'pending'
                ELSE 'error'
            END AS calc_status
        FROM
            packages p
            JOIN versions v USING (package)
            CROSS JOIN build_abis ba
            LEFT JOIN builds b
                ON b.package = v.package
                AND b.version = v.version
                -- TODO The <= comparison is *way* too simplisitic
                AND b.abi_tag <= ba.abi_tag
            LEFT JOIN files f USING (build_id)
        WHERE ba.skip = ''
        AND v.package = pkg
    ),
    abi_parts AS (
        SELECT
            abi_scores.*,
            ROW_NUMBER() OVER (
                PARTITION BY version, calc_abi_tag
                ORDER BY score DESC
            ) AS num
        FROM abi_scores
    ),
    abi_objects AS (
        SELECT
            version,
            json_object_agg(
                calc_abi_tag,
                json_build_object(
                    'status', calc_status,
                    'build_id', build_id
                )
            ) AS obj
        FROM abi_parts
        WHERE score >= 0
        AND num = 1
        GROUP BY version
    ),
    file_objects AS (
        SELECT
            b.version,
            json_object_agg(
                f.filename,
                json_build_object(
                    'hash', f.filehash,
                    'size', f.filesize,
                    'abi_builder', b.abi_tag,
                    'abi_file', f.abi_tag,
                    'platform', f.platform_tag,
                    'requires_python', f.requires_python,
                    'apt_dependencies', (
                        SELECT
                            COALESCE(json_agg(dependency), '{{}}')
                        FROM (
                            SELECT dependency
                            FROM dependencies
                            WHERE filename = f.filename AND tool = 'apt'
                            EXCEPT ALL
                            SELECT apt_package
                            FROM preinstalled_apt_packages
                            WHERE abi_tag = f.abi_tag
                        ) AS d
                    )
                )
            ) AS obj
        FROM files f
        JOIN builds b USING (build_id)
        WHERE b.package = pkg
        GROUP BY b.version
    )
    VALUES (
        json_build_object(
            'name', (
                SELECT name
                FROM package_names
                WHERE package = pkg
                ORDER BY seen DESC
                LIMIT 1
            ),
            'description', (
                SELECT description
                FROM packages
                WHERE package = pkg
            ),
            'releases', (
                SELECT COALESCE(json_object_agg(
                    v.version,
                    json_build_object(
                        'yanked', v.yanked,
                        'released', v.released AT TIME ZONE 'UTC',
                        'skip', COALESCE(NULLIF(v.skip, ''), p.skip),
                        'files', COALESCE(f.obj, '{{}}'),
                        'abis', COALESCE(a.obj, '{{}}')
                    )
                ), '{{}}')
                FROM
                    packages p
                    JOIN versions v USING (package)
                    LEFT JOIN file_objects f USING (version)
                    LEFT JOIN abi_objects a USING (version)
                WHERE p.package = pkg
            )
        )
    );
$sql$;

REVOKE ALL ON FUNCTION get_project_data(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_data(TEXT) TO {username};

DROP FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT, files ARRAY,
    dependencies ARRAY);
DROP FUNCTION log_build_failure(TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT);

CREATE FUNCTION log_build_success(
    package TEXT,
    version TEXT,
    built_by INTEGER,
    duration INTERVAL,
    abi_tag TEXT,
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

CREATE FUNCTION log_build_failure(
    package TEXT,
    version TEXT,
    built_by INTEGER,
    duration INTERVAL,
    abi_tag TEXT
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
    RETURN new_build_id;
END;
$sql$;

REVOKE ALL ON FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, files ARRAY, dependencies ARRAY
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, files ARRAY, dependencies ARRAY
    ) TO {username};
REVOKE ALL ON FUNCTION log_build_failure(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_build_failure(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT
    ) TO {username};

DROP TABLE output;

ALTER TABLE files
    ALTER COLUMN requires_python SET DATA TYPE VARCHAR(200);
