UPDATE configuration SET version = '0.27';

CREATE FUNCTION get_archive_candidates(source_location VARCHAR(100), max_downloads INTEGER)
    RETURNS TABLE(package TEXT, filename TEXT)
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH downloads_per_build AS (
        SELECT
            b.build_id,
            COUNT(d.accessed_at) AS download_count
        FROM builds b
        JOIN files f USING (build_id)
        LEFT JOIN downloads d
            ON d.filename = f.filename
            AND d.accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 month'
        WHERE f.location = source_location
        AND f.deleted_at IS NULL
        GROUP BY b.build_id
    )
    SELECT b.package, f.filename
    FROM files f
    JOIN builds b USING (build_id)
    JOIN downloads_per_build dpb USING (build_id)
    WHERE dpb.download_count < max_downloads
    AND f.location = source_location
    AND f.deleted_at IS NULL
    ORDER BY b.package, f.filename;
$sql$;

REVOKE ALL ON FUNCTION get_archive_candidates(VARCHAR, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_archive_candidates(VARCHAR, INTEGER) TO {username};

CREATE FUNCTION get_unarchive_candidates(source_location VARCHAR(100), min_downloads INTEGER)
    RETURNS TABLE(package TEXT, filename TEXT)
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH downloads_per_build AS (
        SELECT
            b.build_id,
            COUNT(d.accessed_at) AS download_count
        FROM builds b
        JOIN files f USING (build_id)
        LEFT JOIN downloads d
            ON d.filename = f.filename
            AND d.accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 month'
        WHERE f.location = source_location
        AND f.deleted_at IS NULL
        GROUP BY b.build_id
    )
    SELECT b.package, f.filename
    FROM files f
    JOIN builds b USING (build_id)
    JOIN downloads_per_build dpb USING (build_id)
    WHERE dpb.download_count > min_downloads
    AND f.location = source_location
    AND f.deleted_at IS NULL
    ORDER BY b.package, f.filename;
$sql$;

REVOKE ALL ON FUNCTION get_unarchive_candidates(VARCHAR, INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_unarchive_candidates(VARCHAR, INTEGER) TO {username};

CREATE FUNCTION set_files_location(filenames TEXT[], new_location VARCHAR(100))
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE files
    SET location = new_location
    WHERE filename = ANY(filenames)
    AND deleted_at IS NULL;
$sql$;

REVOKE ALL ON FUNCTION set_files_location(TEXT[], VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION set_files_location(TEXT[], VARCHAR) TO {username};
