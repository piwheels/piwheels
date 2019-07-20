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
