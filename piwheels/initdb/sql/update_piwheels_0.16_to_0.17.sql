UPDATE configuration SET version = '0.17';

ALTER TABLE packages
    ADD COLUMN description VARCHAR(200) DEFAULT '' NOT NULL;

ALTER TABLE versions
    ADD COLUMN yanked BOOLEAN DEFAULT false NOT NULL,
    DROP CONSTRAINT versions_package_fk,
    ADD CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE CASCADE;

ALTER TABLE rewrites_pending
    DROP CONSTRAINT rewrites_pending_command_ck;

UPDATE rewrites_pending SET command = CASE command
    WHEN 'PKGPROJ' THEN 'PROJECT'
    WHEN 'PKGBOTH' THEN 'BOTH'
END;

ALTER TABLE rewrites_pending
    ADD CONSTRAINT rewrites_pending_command_ck CHECK (command IN ('PROJECT', 'BOTH'));

CREATE TABLE preinstalled_apt_packages (
    abi_tag        VARCHAR(100) NOT NULL,
    apt_package    VARCHAR(255) NOT NULL,

    CONSTRAINT preinstalled_apt_packages_pk PRIMARY KEY (abi_tag, apt_package),
    CONSTRAINT preinstalled_apt_packages_abi_tag_fk FOREIGN KEY (abi_tag)
        REFERENCES build_abis (abi_tag) ON DELETE CASCADE
);

CREATE INDEX preinstalled_apt_packages_abi_tag ON preinstalled_apt_packages(abi_tag);
GRANT SELECT ON preinstalled_apt_packages TO {username};

ALTER TABLE rewrites_pending
    DROP CONSTRAINT rewrites_pending_package_fk;

DROP FUNCTION add_new_package(TEXT, TEXT);
CREATE FUNCTION add_new_package(package TEXT, skip TEXT = '', description TEXT = '')
    RETURNS BOOLEAN
    LANGUAGE plpgsql
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
BEGIN
    INSERT INTO packages (package, skip, description)
        VALUES (package, skip, description);
    RETURN true;
EXCEPTION
    WHEN unique_violation THEN RETURN false;
END;
$sql$;

REVOKE ALL ON FUNCTION add_new_package(TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION add_new_package(TEXT, TEXT, TEXT) TO {username};

CREATE FUNCTION delete_package(pkg TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    DELETE FROM packages
    WHERE package = pkg;
$sql$;

REVOKE ALL ON FUNCTION delete_package(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_package(TEXT) TO {username};

CREATE FUNCTION delete_version(pkg TEXT, ver TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    DELETE FROM versions
    WHERE package = pkg
    AND version = ver;
$sql$;

REVOKE ALL ON FUNCTION delete_version(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_version(TEXT, TEXT) TO {username};

CREATE FUNCTION yank_version(pkg TEXT, ver TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE versions
    SET yanked = true
    WHERE package = pkg
    AND version = ver;
$sql$;

REVOKE ALL ON FUNCTION yank_version(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION yank_version(TEXT, TEXT) TO {username};

CREATE FUNCTION unyank_version(pkg TEXT, ver TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE versions
    SET yanked = false
    WHERE package = pkg
    AND version = ver;
$sql$;

REVOKE ALL ON FUNCTION unyank_version(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION unyank_version(TEXT, TEXT) TO {username};

CREATE FUNCTION package_marked_deleted(pkg TEXT)
    RETURNS BOOLEAN
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT COUNT(*) = 1
    FROM packages
    WHERE package = pkg
    AND skip = 'deleted';
$sql$;

REVOKE ALL ON FUNCTION package_marked_deleted(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION package_marked_deleted(TEXT) TO {username};

CREATE FUNCTION get_versions_deleted(pkg TEXT)
    RETURNS TABLE(
        version versions.version%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT version
    FROM versions
    WHERE package = pkg
    AND skip = 'deleted';
$sql$;

REVOKE ALL ON FUNCTION get_versions_deleted(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_versions_deleted(TEXT) TO {username};

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

CREATE FUNCTION set_package_description(pkg TEXT, dsc TEXT)
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

REVOKE ALL ON FUNCTION set_package_description(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION set_package_description(TEXT, TEXT) TO {username};

CREATE FUNCTION get_package_description(pkg TEXT)
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

REVOKE ALL ON FUNCTION get_package_description(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_package_description(TEXT) TO {username};

DROP FUNCTION get_project_versions(TEXT);

CREATE FUNCTION get_project_versions(pkg TEXT)
    RETURNS TABLE(
        version versions.version%TYPE,
        skipped versions.skip%TYPE,
        builds_succeeded TEXT,
        builds_failed TEXT,
        yanked BOOLEAN
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        v.version,
        COALESCE(NULLIF(v.skip, ''), p.skip) AS skipped,
        COALESCE(STRING_AGG(DISTINCT b.abi_tag, ', ') FILTER (WHERE b.status), '') AS builds_succeeded,
        COALESCE(STRING_AGG(DISTINCT b.abi_tag, ', ') FILTER (WHERE NOT b.status), '') AS builds_failed,
        v.yanked
    FROM
        packages p
        JOIN versions v USING (package)
        LEFT JOIN builds b USING (package, version)
    WHERE v.package = pkg
    GROUP BY version, skipped, yanked;
$sql$;

DROP FUNCTION get_project_files(TEXT);

CREATE FUNCTION get_project_files(pkg TEXT)
    RETURNS TABLE(
        version builds.version%TYPE,
        abi_tag files.abi_tag%TYPE,
        filename files.filename%TYPE,
        filesize files.filesize%TYPE,
        filehash files.filehash%TYPE,
        yanked versions.yanked%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        b.version,
        f.abi_tag,
        f.filename,
        f.filesize,
        f.filehash,
        v.yanked
    FROM
        builds b
        JOIN files f USING (build_id)
        JOIN versions v USING (package, version)
    WHERE b.status
    AND b.package = pkg;
$sql$;

REVOKE ALL ON FUNCTION get_project_files(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_files(TEXT) TO {username};

DROP FUNCTION get_statistics();
CREATE FUNCTION get_statistics()
    RETURNS TABLE(
        builds_time            INTERVAL,
        builds_size            BIGINT,
        packages_built         INTEGER,
        files_count            INTEGER,
        new_last_hour          INTEGER,
        downloads_all          INTEGER,
        downloads_last_month   INTEGER,
        downloads_last_hour    INTEGER
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH build_stats AS (
        SELECT
            COALESCE(SUM(CASE
                -- This guards against including insanely huge durations as
                -- happens when a builder starts without NTP time sync and
                -- records a start time of 1970-01-01 and a completion time
                -- sometime this millenium...
                WHEN duration < INTERVAL '1 week' THEN duration
                ELSE INTERVAL '0'
            END), INTERVAL '0') AS builds_time
        FROM
            builds
    ),
    file_count AS (
        SELECT
            COUNT(*) AS files_count,
            COUNT(DISTINCT package_tag) AS packages_built
        FROM files
    ),
    file_stats AS (
        -- Exclude armv6l packages as they're just hard-links to armv7l
        -- packages and thus don't really count towards space used ... in most
        -- cases anyway
        SELECT COALESCE(SUM(filesize), 0) AS builds_size
        FROM files
        WHERE platform_tag <> 'linux_armv6l'
    ),
    download_stats AS (
        SELECT
            COUNT(*) AS downloads_all,
            COUNT(*) FILTER (
                WHERE accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
            ) AS downloads_last_month,
            COUNT(*) FILTER (
                WHERE accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
            ) AS downloads_last_hour
        FROM downloads
    ),
    version_stats AS (
        SELECT COUNT(*) AS new_last_hour
        FROM versions
        WHERE released > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    )
    SELECT
        bs.builds_time,
        fs.builds_size,
        CAST(fc.packages_built AS INTEGER),
        CAST(fc.files_count AS INTEGER),
        CAST(vs.new_last_hour AS INTEGER),
        CAST(dl.downloads_all AS INTEGER),
        CAST(dl.downloads_last_month AS INTEGER),
        CAST(dl.downloads_last_hour AS INTEGER)
    FROM
        build_stats bs,
        file_count fc,
        file_stats fs,
        version_stats vs,
        download_stats dl;
$sql$;

REVOKE ALL ON FUNCTION get_statistics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_statistics() TO {username};

CREATE FUNCTION get_builds_last_hour()
    RETURNS TABLE(
        abi_tag build_abis.abi_tag%TYPE,
        builds  INTEGER
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH t AS (
        SELECT abi_tag
        FROM builds
        WHERE built_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    )
    SELECT b.abi_tag, CAST(COUNT(t.abi_tag) AS INTEGER) AS builds
    FROM build_abis b LEFT JOIN t USING (abi_tag)
    WHERE b.skip = ''
    GROUP BY b.abi_tag;
$sql$;

REVOKE ALL ON FUNCTION get_builds_last_hour() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_builds_last_hour() TO {username};
