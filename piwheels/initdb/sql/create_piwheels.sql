REVOKE ALL PRIVILEGES ON DATABASE {dbname} FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;
GRANT CONNECT, TEMP ON DATABASE {dbname} TO {username};
GRANT USAGE ON SCHEMA public TO {username};

-- configuration
-------------------------------------------------------------------------------
-- This table contains a single row persisting configuration information. The
-- id column is redundant other than providing a key. The version column
-- contains a string indicating which version of the software the structure of
-- the database is designed for. Finally, pypi_serial contains the last serial
-- number the master retrieved from PyPI.
-------------------------------------------------------------------------------

CREATE TABLE configuration (
    id INTEGER DEFAULT 1 NOT NULL,
    version VARCHAR(16) DEFAULT '0.6' NOT NULL,
    pypi_serial BIGINT DEFAULT 0 NOT NULL,
    native_distro TEXT DEFAULT 'Raspbian GNU/Linux' NOT NULL,

    CONSTRAINT config_pk PRIMARY KEY (id)
);

INSERT INTO configuration(id, version) VALUES (1, '0.17');
GRANT SELECT ON configuration TO {username};

-- packages
-------------------------------------------------------------------------------
-- The "packages" table defines all available packages on PyPI, derived from
-- the list_packages() API. The "skip" column defaults to NULL but can be set
-- to a non-empty string indicating why a package should not be built.
-------------------------------------------------------------------------------

CREATE TABLE packages (
    package VARCHAR(200) NOT NULL,
    skip    VARCHAR(100) DEFAULT '' NOT NULL,
    description VARCHAR(200) DEFAULT '' NOT NULL,

    CONSTRAINT packages_pk PRIMARY KEY (package)
);

GRANT SELECT ON packages TO {username};

-- versions
-------------------------------------------------------------------------------
-- The "versions" table defines all versions of packages *with files* on PyPI;
-- note that versions without released files (a common occurrence) are
-- excluded. Like the "packages" table, the "skip" column can be set to a
-- non-empty string indicating why a version should not be built.
-------------------------------------------------------------------------------

CREATE TABLE versions (
    package  VARCHAR(200) NOT NULL,
    version  VARCHAR(200) NOT NULL,
    released TIMESTAMP DEFAULT '1970-01-01 00:00:00' NOT NULL,
    skip     VARCHAR(100) DEFAULT '' NOT NULL,

    CONSTRAINT versions_pk PRIMARY KEY (package, version),
    CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE RESTRICT
);

CREATE INDEX versions_package ON versions(package);
GRANT SELECT ON versions TO {username};

-- build_abis
-------------------------------------------------------------------------------
-- The "build_abis" table defines the set of CPython ABIs that the master
-- should attempt to build. This table must be populated with rows for anything
-- to be built. In addition, there must be at least one slave for each defined
-- ABI. Typical values are "cp34m", "cp35m", etc. Special ABIs like "none" must
-- NOT be included in the table.
-------------------------------------------------------------------------------

CREATE TABLE build_abis (
    abi_tag         VARCHAR(100) NOT NULL,
    skip            VARCHAR(100) DEFAULT '' NOT NULL,

    CONSTRAINT build_abis_pk PRIMARY KEY (abi_tag),
    CONSTRAINT build_abis_none_ck CHECK (abi_tag <> 'none')
);

GRANT SELECT ON build_abis TO {username};

-- builds
-------------------------------------------------------------------------------
-- The "builds" table tracks all builds attempted by the system, successful or
-- otherwise. As builds of a given version can be attempted multiple times, the
-- table is keyed by a straight-forward auto-incrementing integer. The package
-- and version columns reference the "versions" table.
--
-- The "built_by" column is an integer indicating which build slave attempted
-- the build; note that slave IDs can be re-assigned by a master restart, and
-- slaves that are restarted are assigned new numbers so this is not a reliable
-- method of discovering exactly which slave built something. It is more useful
-- as a means of determining the distribution of builds over time.
--
-- The "built_at" and "duration" columns simply track when the build started
-- and how long it took, "status" specifies whether or not the build succeeded
-- (true for success, false otherwise).
-------------------------------------------------------------------------------

CREATE TABLE builds (
    build_id        SERIAL NOT NULL,
    package         VARCHAR(200) NOT NULL,
    version         VARCHAR(200) NOT NULL,
    built_by        INTEGER NOT NULL,
    built_at        TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    duration        INTERVAL NOT NULL,
    status          BOOLEAN DEFAULT true NOT NULL,
    abi_tag         VARCHAR(100) NOT NULL,

    CONSTRAINT builds_pk PRIMARY KEY (build_id),
    CONSTRAINT builds_unique UNIQUE (package, version, built_at, built_by),
    CONSTRAINT builds_versions_fk FOREIGN KEY (package, version)
        REFERENCES versions ON DELETE CASCADE,
    CONSTRAINT builds_built_by_ck CHECK (built_by >= 0)
);

CREATE INDEX builds_timestamp ON builds(built_at DESC NULLS LAST);
CREATE INDEX builds_pkgver ON builds(package, version);
CREATE INDEX builds_pkgverid ON builds(build_id, package, version);
CREATE INDEX builds_pkgverabi ON builds(build_id, package, version, abi_tag);
GRANT SELECT ON builds TO {username};

-- output
-------------------------------------------------------------------------------
-- The "output" table is an optimization designed to separate the (huge)
-- "output" column out of the "builds" table. The "output" column is rarely
-- accessed in normal operations but forms the bulk of the database size, hence
-- it makes sense to keep it isolated from most queries. This table has a
-- 1-to-1 mandatory relationship with "builds".
-------------------------------------------------------------------------------

CREATE TABLE output (
    build_id        INTEGER NOT NULL,
    output          TEXT NOT NULL,

    CONSTRAINT output_pk PRIMARY KEY (build_id),
    CONSTRAINT output_builds_fk FOREIGN KEY (build_id)
        REFERENCES builds (build_id) ON DELETE CASCADE
);

GRANT SELECT ON output TO {username};

-- files
-------------------------------------------------------------------------------
-- The "files" table tracks each file generated by a build. The "filename"
-- column is the primary key, and "build_id" is a foreign key referencing the
-- "builds" table above. The "filesize" and "filehash" columns contain the size
-- in bytes and SHA256 hash of the contents respectively.
--
-- The various "*_tag" columns are derived from the "filename" column;
-- effectively these are redundant but are split out as the information is
-- required for things like the build-queue, and indexing of (some of) them is
-- needed for performance.
-------------------------------------------------------------------------------

CREATE TABLE files (
    filename            VARCHAR(255) NOT NULL,
    build_id            INTEGER NOT NULL,
    filesize            INTEGER NOT NULL,
    filehash            CHAR(64) NOT NULL,
    package_tag         VARCHAR(200) NOT NULL,
    package_version_tag VARCHAR(200) NOT NULL,
    py_version_tag      VARCHAR(100) NOT NULL,
    abi_tag             VARCHAR(100) NOT NULL,
    platform_tag        VARCHAR(100) NOT NULL,

    CONSTRAINT files_pk PRIMARY KEY (filename),
    CONSTRAINT files_builds_fk FOREIGN KEY (build_id)
        REFERENCES builds (build_id) ON DELETE CASCADE
);

CREATE INDEX files_builds ON files(build_id);
CREATE INDEX files_size ON files(platform_tag, filesize) WHERE platform_tag <> 'linux_armv6l';
CREATE INDEX files_abi ON files(build_id, abi_tag);
CREATE INDEX files_packages ON files(package_tag);
GRANT SELECT ON files TO {username};

-- dependencies
-------------------------------------------------------------------------------
-- The "dependencies" table tracks the libraries that need to be installed for
-- a given wheel to operate correctly. The primary key is a combination of the
-- "filename" that the dependency applies to, and the name of the "dependency"
-- that needs installing. One additional column records the "tool" that the
-- dependency needs installing with (at the moment this will always be apt but
-- it's possible in future that pip will be included here).
-------------------------------------------------------------------------------

CREATE TABLE dependencies (
    filename            VARCHAR(255) NOT NULL,
    tool                VARCHAR(10) DEFAULT 'apt' NOT NULL,
    dependency          VARCHAR(255) NOT NULL,

    CONSTRAINT dependencies_pk PRIMARY KEY (filename, tool, dependency),
    CONSTRAINT dependencies_files_fk FOREIGN KEY (filename)
        REFERENCES files(filename) ON DELETE CASCADE,
    CONSTRAINT dependencies_tool_ck CHECK (tool IN ('apt', 'pip', ''))
);

GRANT SELECT ON dependencies TO {username};

-- downloads
-------------------------------------------------------------------------------
-- The "downloads" table tracks the files that are downloaded by piwheels
-- users.
-------------------------------------------------------------------------------

CREATE TABLE downloads (
    filename            VARCHAR(255) NOT NULL,
    accessed_by         INET NOT NULL,
    accessed_at         TIMESTAMP NOT NULL,
    arch                VARCHAR(100) DEFAULT NULL,
    distro_name         VARCHAR(100) DEFAULT NULL,
    distro_version      VARCHAR(100) DEFAULT NULL,
    os_name             VARCHAR(100) DEFAULT NULL,
    os_version          VARCHAR(100) DEFAULT NULL,
    py_name             VARCHAR(100) DEFAULT NULL,
    py_version          VARCHAR(100) DEFAULT NULL,
    installer_name      VARCHAR(20) DEFAULT NULL,
    installer_version   VARCHAR(100) DEFAULT NULL,
    setuptools_version  VARCHAR(100) DEFAULT NULL
);

CREATE INDEX downloads_files ON downloads(filename);
CREATE INDEX downloads_accessed_at ON downloads(accessed_at DESC);
GRANT SELECT ON downloads TO {username};

-- searches
-------------------------------------------------------------------------------
-- The "searches" table tracks the searches made against piwheels by users.
-------------------------------------------------------------------------------

CREATE TABLE searches (
    package             VARCHAR(200) NOT NULL,
    accessed_by         INET NOT NULL,
    accessed_at         TIMESTAMP NOT NULL,
    arch                VARCHAR(100) DEFAULT NULL,
    distro_name         VARCHAR(100) DEFAULT NULL,
    distro_version      VARCHAR(100) DEFAULT NULL,
    os_name             VARCHAR(100) DEFAULT NULL,
    os_version          VARCHAR(100) DEFAULT NULL,
    py_name             VARCHAR(100) DEFAULT NULL,
    py_version          VARCHAR(100) DEFAULT NULL,
    installer_name      VARCHAR(20) DEFAULT NULL,
    installer_version   VARCHAR(100) DEFAULT NULL,
    setuptools_version  VARCHAR(100) DEFAULT NULL
);

CREATE INDEX searches_package ON searches(package);
CREATE INDEX searches_accessed_at ON searches(accessed_at DESC);
GRANT SELECT ON searches TO {username};

-- project_page_hits
-------------------------------------------------------------------------------
-- The "project_page_hits" table tracks the views of project pages by users.
-------------------------------------------------------------------------------

CREATE TABLE project_page_hits (
    package             VARCHAR(200) NOT NULL,
    accessed_by         INET NOT NULL,
    accessed_at         TIMESTAMP NOT NULL,
    user_agent          VARCHAR(2000),
    bot                 BOOLEAN DEFAULT false NOT NULL
);

CREATE INDEX project_page_hits_package ON project_page_hits(package);
CREATE INDEX project_page_hits_accessed_at ON project_page_hits(accessed_at DESC);
GRANT SELECT ON project_page_hits TO {username};

-- project_json_downloads
-------------------------------------------------------------------------------
-- The "project_json_downloads" table tracks the downloads of project JSON by
-- users.
-------------------------------------------------------------------------------

CREATE TABLE project_json_downloads (
    package             VARCHAR(200) NOT NULL,
    accessed_by         INET NOT NULL,
    accessed_at         TIMESTAMP NOT NULL,
    user_agent          VARCHAR(2000)
);

CREATE INDEX project_json_downloads_package ON project_json_downloads(package);
CREATE INDEX project_json_downloads_accessed_at ON project_json_downloads(accessed_at DESC);
GRANT SELECT ON project_json_downloads TO {username};

-- web_page_hits
-------------------------------------------------------------------------------
-- The "web_page_hits" table tracks the views of static web pages by users.
-------------------------------------------------------------------------------

CREATE TABLE web_page_hits (
    page                VARCHAR(30) NOT NULL,
    accessed_by         INET NOT NULL,
    accessed_at         TIMESTAMP NOT NULL,
    user_agent          VARCHAR(2000),
    bot                 BOOLEAN DEFAULT false NOT NULL
);

CREATE INDEX web_page_hits_package ON web_page_hits(page);
CREATE INDEX web_page_hits_accessed_at ON web_page_hits(accessed_at DESC);
GRANT SELECT ON web_page_hits TO {username};

-- rewrites_pending
-------------------------------------------------------------------------------
-- The "rewrites_pending" table stores the state of the_secretary's queue
-- between runs of the master. Under ordinary circumstances the table is empty,
-- but when the master terminates, the task stores the state of its internal
-- buffer in this table, restoring it (and emptying the table) on restart.
-------------------------------------------------------------------------------

CREATE TABLE rewrites_pending (
    package        VARCHAR(200) NOT NULL,
    added_at       TIMESTAMP NOT NULL,
    command        VARCHAR(8) NOT NULL,

    CONSTRAINT rewrites_pending_pk PRIMARY KEY (package),
    CONSTRAINT rewrites_pending_package_fk FOREIGN KEY (package)
        REFERENCES packages (package) ON DELETE CASCADE,
    CONSTRAINT rewrites_pending_command_ck CHECK
        (command IN ('PKGPROJ', 'PKGBOTH'))
);

CREATE INDEX rewrites_pending_added ON rewrites_pending(added_at);
GRANT SELECT ON rewrites_pending TO {username};

-- preinstalled_apt_packages
-------------------------------------------------------------------------------
-- The "preinstalled_apt_packages" table stores the apt packages which are
-- preinstalled in each distro version (where a distro version maps directly to
-- an ABI) so that the relevant apt packages can be excluded from the
-- dependencies shown for a particular piwheels package. The table should be
-- populated with all the apt packages preinstalled in the "Lite" version of the
-- OS release.
-------------------------------------------------------------------------------

CREATE TABLE preinstalled_apt_packages (
    abi_tag        VARCHAR(100) NOT NULL,
    apt_package    VARCHAR(255) NOT NULL,

    CONSTRAINT preinstalled_apt_packages_pk PRIMARY KEY (abi_tag, apt_package),
    CONSTRAINT preinstalled_apt_packages_abi_tag_fk FOREIGN KEY (abi_tag)
        REFERENCES build_abis (abi_tag) ON DELETE CASCADE
);

CREATE INDEX preinstalled_apt_packages_abi_tag ON preinstalled_apt_packages(abi_tag);
GRANT SELECT ON preinstalled_apt_packages TO {username};

-- builds_pending
-------------------------------------------------------------------------------
-- The "builds_pending" view is the basis of the build queue in the master. The
-- "packages", "versions" and "build_abis" tables form the basis of what needs
-- to be built. The "builds" and "files" tables define what's been attempted,
-- what's succeeded, and for which ABIs. This view combines all this
-- information and returns "package", "version", "abi" tuples defining what
-- requires building next and on which ABI.
--
-- There are some things to note about the behaviour of the queue. When no
-- builds of a package have been attempted, only the "lowest" ABI is attempted.
-- This is because most packages wind up with the "none" ABI which is
-- compatible with everything. The "lowest" is attempted just in case
-- dependencies in later Python versions are incompatible with earlier
-- versions. Once a package has a file with the "none" ABI, no further builds
-- are attempted (naturally). Only if the initial build generated something
-- with a specific ABI (something other than "none"), or if the initial build
-- fails are builds for the other ABIs listed in "build_abis" attempted. Each
-- ABI is attempted in order until a build succeeds in producing an ABI "none"
-- package, or we run out of active ABIs.
-------------------------------------------------------------------------------

CREATE VIEW builds_pending AS
-- Finally, because I can't write this in order due to postgres' annoying
-- materialization of CTEs, the same set as below but augmented with a per-ABI
-- build queue position, based on version release date, primarily for the
-- purposes of filtering
SELECT
    abi_tag,
    ROW_NUMBER() OVER (PARTITION BY abi_tag ORDER BY released) AS position,
    package,
    version
FROM
    (
        -- The set of package versions against each ABI for which they haven't
        -- been attempted and for which no covering "none" ABI wheel exists
        SELECT
            q.package,
            q.version,
            v.released,
            MIN(q.abi_tag) AS abi_tag
        FROM
            (
                -- The set of package versions X build ABIs that we want to
                -- exist once the queue is complete
                SELECT
                    v.package,
                    v.version,
                    b.abi_tag
                FROM
                    packages AS p
                    JOIN versions AS v ON v.package = p.package
                    CROSS JOIN build_abis AS b
                WHERE
                    v.skip = ''
                    AND p.skip = ''
                    AND b.skip = ''

                EXCEPT ALL

                (
                    -- The set of package versions that successfully produced
                    -- wheels with ABI "none", and which therefore count as
                    -- all build ABIs
                    SELECT
                        b.package,
                        b.version,
                        v.abi_tag
                    FROM
                        builds AS b
                        JOIN files AS f ON b.build_id = f.build_id
                        CROSS JOIN build_abis AS v
                    WHERE f.abi_tag = 'none'

                    UNION ALL

                    -- The set of package versions that successfully produced a
                    -- wheel with a single ABI (abi_tag <> 'none') or which
                    -- were attempted but failed (build_id IS NULL)
                    SELECT
                        b.package,
                        b.version,
                        COALESCE(f.abi_tag, b.abi_tag) AS abi_tag
                    FROM
                        builds AS b
                        LEFT JOIN files AS f ON b.build_id = f.build_id
                    WHERE
                        f.build_id IS NULL
                        OR f.abi_tag <> 'none'
                )
            ) AS q
            JOIN versions v ON q.package = v.package AND q.version = v.version
        GROUP BY
            q.package,
            q.version,
            v.released
    ) AS t;

GRANT SELECT ON builds_pending TO {username};

-- get_pypi_serial()
-------------------------------------------------------------------------------
-- Retrieves the current PyPI serial number from the "configuration" table.
-------------------------------------------------------------------------------

CREATE FUNCTION get_pypi_serial()
    RETURNS BIGINT
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT pypi_serial FROM configuration WHERE id = 1;
$sql$;

REVOKE ALL ON FUNCTION get_pypi_serial() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_pypi_serial() TO {username};

-- set_pypi_serial(new_serial)
-------------------------------------------------------------------------------
-- Called to update the last PyPI serial number seen in the "configuration"
-- table.
-------------------------------------------------------------------------------

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

-- add_new_package(package, skip=NULL)
-------------------------------------------------------------------------------
-- Called to insert a new row in the "packages" table.
-------------------------------------------------------------------------------

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

-- add_new_package_version(package, version, released=NULL, skip=NULL)
-------------------------------------------------------------------------------
-- Called to insert a new row in the "versions" table.
-------------------------------------------------------------------------------

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

-- update_project_description(package, description)
-------------------------------------------------------------------------------
-- Called to update the project description for *package* in the packages
-- table.
-------------------------------------------------------------------------------

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

-- get_project_description(package)
-------------------------------------------------------------------------------
-- Called to retrieve the project description for *package* in the packages
-- table.
-------------------------------------------------------------------------------

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

-- skip_package(package, reason)
-------------------------------------------------------------------------------
-- Sets the "skip" field on the specified row in "packages" to the given value.
-------------------------------------------------------------------------------

CREATE FUNCTION skip_package(pkg TEXT, reason TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE packages SET skip = reason WHERE package = pkg;
$sql$;

REVOKE ALL ON FUNCTION skip_package(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION skip_package(TEXT, TEXT) TO {username};

-- skip_package_version(package, version, reason)
-------------------------------------------------------------------------------
-- Sets the "skip" field on the specified row in "versions" to the given value.
-------------------------------------------------------------------------------

CREATE FUNCTION skip_package_version(pkg TEXT, ver TEXT, reason TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    UPDATE versions SET skip = reason
    WHERE package = pkg AND version = ver;
$sql$;

REVOKE ALL ON FUNCTION skip_package_version(TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION skip_package_version(TEXT, TEXT, TEXT) TO {username};

-- log_download(filename, accessed_by, accessed_at, arch, distro_name,
--              distro_version, os_name, os_version, py_name, py_version,
--              installer_name, installer_version, setuptools_version)
-------------------------------------------------------------------------------
-- Adds a new entry to the downloads table.
-------------------------------------------------------------------------------

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
    py_version TEXT = NULL,
    installer_name TEXT = NULL,
    installer_version TEXT = NULL,
    setuptools_version TEXT = NULL
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
        py_version,
        installer_name,
        installer_version,
        setuptools_version
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
        py_version,
        installer_name,
        installer_version,
        setuptools_version
    );
$sql$;

REVOKE ALL ON FUNCTION log_download(
    TEXT, INET, TIMESTAMP,
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_download(
    TEXT, INET, TIMESTAMP,
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
    ) TO {username};

-- log_search(package, accessed_by, accessed_at, arch, distro_name,
--              distro_version, os_name, os_version, py_name, py_version,
--              installer_name, installer_version, setuptools_version)
-------------------------------------------------------------------------------
-- Adds a new entry to the searches table.
-------------------------------------------------------------------------------

CREATE FUNCTION log_search(
    package TEXT,
    accessed_by INET,
    accessed_at TIMESTAMP,
    arch TEXT = NULL,
    distro_name TEXT = NULL,
    distro_version TEXT = NULL,
    os_name TEXT = NULL,
    os_version TEXT = NULL,
    py_name TEXT = NULL,
    py_version TEXT = NULL,
    installer_name TEXT = NULL,
    installer_version TEXT = NULL,
    setuptools_version TEXT = NULL
)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    INSERT INTO searches (
        package,
        accessed_by,
        accessed_at,
        arch,
        distro_name,
        distro_version,
        os_name,
        os_version,
        py_name,
        py_version,
        installer_name,
        installer_version,
        setuptools_version
    )
    VALUES (
        package,
        accessed_by,
        accessed_at,
        arch,
        distro_name,
        distro_version,
        os_name,
        os_version,
        py_name,
        py_version,
        installer_name,
        installer_version,
        setuptools_version
    );
$sql$;

REVOKE ALL ON FUNCTION log_search(
    TEXT, INET, TIMESTAMP,
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_search(
    TEXT, INET, TIMESTAMP,
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
    ) TO {username};

-- log_project(package, accessed_by, accessed_at)
-------------------------------------------------------------------------------
-- Adds a new entry to the project_page_hits table.
-------------------------------------------------------------------------------

CREATE FUNCTION log_project(
    package TEXT,
    accessed_by INET,
    accessed_at TIMESTAMP,
    user_agent TEXT
)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    INSERT INTO project_page_hits (
        package,
        accessed_by,
        accessed_at,
        user_agent
    )
    VALUES (
        package,
        accessed_by,
        accessed_at,
        user_agent
    );
$sql$;

REVOKE ALL ON FUNCTION log_project(
    TEXT, INET, TIMESTAMP, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_project(
    TEXT, INET, TIMESTAMP, TEXT
    ) TO {username};

-- log_json(package, accessed_by, accessed_at, user_agent)
-------------------------------------------------------------------------------
-- Adds a new entry to the project_json_downloads table.
-------------------------------------------------------------------------------

CREATE FUNCTION log_json(
    package TEXT,
    accessed_by INET,
    accessed_at TIMESTAMP,
    user_agent TEXT
)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    INSERT INTO project_json_downloads (
        package,
        accessed_by,
        accessed_at,
        user_agent
    )
    VALUES (
        package,
        accessed_by,
        accessed_at,
        user_agent
    );
$sql$;

REVOKE ALL ON FUNCTION log_json(
    TEXT, INET, TIMESTAMP, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_json(
    TEXT, INET, TIMESTAMP, TEXT
    ) TO {username};

-- log_page(page, accessed_by, accessed_at)
-------------------------------------------------------------------------------
-- Adds a new entry to the web_page_hits table.
-------------------------------------------------------------------------------

CREATE FUNCTION log_page(
    page TEXT,
    accessed_by INET,
    accessed_at TIMESTAMP,
    user_agent TEXT
)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    INSERT INTO web_page_hits (
        page,
        accessed_by,
        accessed_at,
        user_agent
    )
    VALUES (
        page,
        accessed_by,
        accessed_at,
        user_agent
    );
$sql$;

REVOKE ALL ON FUNCTION log_page(
    TEXT, INET, TIMESTAMP, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_page(
    TEXT, INET, TIMESTAMP, TEXT
    ) TO {username};

-- log_build_success(package, version, build_by, ...)
-- log_build_failure(package, version, build_by, ...)
-------------------------------------------------------------------------------
-- Adds a new entry to the builds table, and any associated files
-------------------------------------------------------------------------------

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
        platform_tag
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
            b.platform_tag
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
    INSERT INTO output (build_id, output) VALUES (new_build_id, output);
    RETURN new_build_id;
END;
$sql$;

REVOKE ALL ON FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT, files ARRAY, dependencies ARRAY
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_build_success(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT, files ARRAY, dependencies ARRAY
    ) TO {username};
REVOKE ALL ON FUNCTION log_build_failure(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_build_failure(
    TEXT, TEXT, INTEGER, INTERVAL, TEXT, TEXT
    ) TO {username};

-- delete_build(package, version)
-------------------------------------------------------------------------------
-- Deletes build, output, and files information for the specified *version*
-- of *package*.
-------------------------------------------------------------------------------

CREATE FUNCTION delete_build(pkg TEXT, ver TEXT)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    -- Foreign keys take care of the rest
    DELETE FROM builds b WHERE b.package = pkg AND b.version = ver;
$sql$;

REVOKE ALL ON FUNCTION delete_build(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_build(TEXT, TEXT) TO {username};

-- test_package(package)
-------------------------------------------------------------------------------
-- Tests *package* exists as a row in the *packages* table, regardless of
-- whether it is skipped or not.
-------------------------------------------------------------------------------

CREATE FUNCTION test_package(pkg TEXT)
    RETURNS BOOLEAN
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT COUNT(*) = 1 FROM packages p WHERE p.package = pkg;
$sql$;

REVOKE ALL ON FUNCTION test_package(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION test_package(TEXT) TO {username};

-- test_package_version(package, version)
-------------------------------------------------------------------------------
-- Tests *version* of *package* exists as a row in the *versions* table,
-- regardless of whether it is skipped or not.
-------------------------------------------------------------------------------

CREATE FUNCTION test_package_version(pkg TEXT, ver TEXT)
    RETURNS BOOLEAN
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT COUNT(*) = 1 FROM versions v
    WHERE v.package = pkg AND v.version = ver;
$sql$;

REVOKE ALL ON FUNCTION test_package_version(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION test_package_version(TEXT, TEXT) TO {username};

-- get_build_queue()
-------------------------------------------------------------------------------
-- Returns the build-queue, with the specified *lim* of versions per ABI,
-- ordered by ABI, then position in the queue.
-------------------------------------------------------------------------------

CREATE FUNCTION get_build_queue(lim INTEGER)
    RETURNS TABLE(
        abi_tag builds_pending.abi_tag%TYPE,
        package builds_pending.package%TYPE,
        version builds_pending.version%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT abi_tag, package, version
    FROM builds_pending
    WHERE position <= lim
    ORDER BY abi_tag, position;
$sql$;

REVOKE ALL ON FUNCTION get_build_queue(INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_build_queue(INTEGER) TO {username};

-- get_basic_statistics()
-------------------------------------------------------------------------------
-- Returns a single row with the basic statistics about the system.
-------------------------------------------------------------------------------

CREATE FUNCTION get_basic_statistics()
    RETURNS TABLE(
        builds_time            INTERVAL,
        builds_size            BIGINT,
        packages_built         INTEGER,
        files_count            INTEGER,
        new_last_hour          INTEGER,
        downloads_last_hour    INTEGER,
        downloads_bandwidth    BIGINT
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
            CAST(COUNT(*) AS INTEGER) AS files_count,
            CAST(COUNT(DISTINCT package_tag) AS INTEGER) AS packages_built
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
        SELECT CAST(COUNT(*) AS INTEGER) AS downloads_last_hour
        FROM downloads
        WHERE accessed_at >
            CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    ),
    bandwidth_stats AS (
        SELECT
            SUM(f.filesize) AS downloads_bandwidth
        FROM downloads d JOIN files f USING (filename)
        WHERE accessed_at >
            CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    ),
    version_stats AS (
        SELECT CAST(COUNT(*) AS INTEGER) AS new_last_hour
        FROM versions
        WHERE released > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    )
    SELECT
        bs.builds_time,
        fs.builds_size,
        fc.packages_built,
        fc.files_count,
        ds.downloads_last_hour,
        vs.new_last_hour AS new_last_hour,
        bw.downloads_bandwidth
    FROM
        build_stats bs,
        file_count fc,
        file_stats fs,
        version_stats vs,
        download_stats ds,
        bandwidth_stats bw
$sql$;

-- get_download_statistics()
-------------------------------------------------------------------------------
-- Returns a single row containing the download counts for a variety of
-- time spans.
-------------------------------------------------------------------------------

CREATE FUNCTION get_statistics()
    RETURNS TABLE(
        downloads_all          INTEGER,
        downloads_last_year    INTEGER,
        downloads_last_month   INTEGER,
        downloads_last_week    INTEGER,
        downloads_last_day     INTEGER,
        downloads_last_hour    INTEGER
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    WITH downloads_agg AS (
        SELECT
            CAST(DATE_TRUNC('day', accessed_at) AS DATE) AS day,
            COUNT(*) AS downloads
        FROM downloads
        WHERE accessed_at >
            CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '365 days'
        GROUP BY day
    ),
    download_stats_year AS (
        SELECT
            SUM(downloads) AS downloads_last_year,
            SUM(downloads) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
            ) AS downloads_last_month,
            SUM(downloads) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '7 days'
            ) AS downloads_last_week,
            SUM(downloads) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 day'
            ) AS downloads_last_day
        FROM downloads_agg
    )
    SELECT
        dl.downloads_last_year   AS downloads_last_year,
        dl.downloads_last_month  AS downloads_last_month,
        dl.downloads_last_week   AS downloads_last_week,
        dl.downloads_last_day    AS downloads_last_day
    FROM
        download_stats_year dl
$sql$;

-- get_statistics()
-------------------------------------------------------------------------------
-- Returns a single row containing a variety of statistics about the system.
-------------------------------------------------------------------------------

CREATE FUNCTION get_statistics()
    RETURNS TABLE(
        builds_time            INTERVAL,
        builds_size            BIGINT,
        packages_built         INTEGER,
        files_count            INTEGER,
        new_last_hour          INTEGER,
        downloads_all          INTEGER,
        downloads_last_year    INTEGER,
        downloads_last_month   INTEGER,
        downloads_last_week    INTEGER,
        downloads_last_day     INTEGER,
        downloads_last_hour    INTEGER
        downloads_bandwith     BIGINT,
        time_saved_all         INTERVAL,
        time_saved_year        INTERVAL,
        time_saved_month       INTERVAL,
        time_saved_week        INTERVAL,
        time_saved_day         INTERVAL,
        power_saved_kwh        DOUBLE PRECISION,

        po.top_last_month,
        po.top_all,
        dm.downloads_by_month,
        dd.downloads_by_day,
        tm.time_saved_by_month,
        pm.python_versions_by_month,
        am.arch_by_month,
        om.os_by_month,
        rm.release_by_month
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
            CAST(COUNT(*) AS INTEGER) AS files_count,
            CAST(COUNT(DISTINCT package_tag) AS INTEGER) AS packages_built
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
    days_last_year AS (
        SELECT
            CAST(t.d AS DATE) AS day
        FROM
            generate_series(
                DATE_TRUNC(
                    'day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '365 days'),
                DATE_TRUNC(
                    'day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                INTERVAL '1 day'
            ) AS t(d)
    ),
    months_last_year AS (
        SELECT
            CAST(t.d AS DATE) AS month
        FROM
            generate_series(
                DATE_TRUNC(
                    'month', CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '11 months'),
                DATE_TRUNC(
                    'month', CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
                INTERVAL '1 month'
            ) AS t(d)
    ),
    download_stats_hour AS (
        SELECT COUNT(*) AS downloads_last_hour
        FROM downloads
        WHERE accessed_at >
            CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    ),
    downloads_agg AS (
        SELECT
            CAST(DATE_TRUNC('day', accessed_at) AS DATE) AS day,
            COUNT(*) AS downloads
        FROM downloads
        GROUP BY day
    ),
    download_stats_year AS (
        SELECT
            SUM(downloads) AS downloads_all,
            SUM(downloads) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '365 days'
            ) AS downloads_last_year,
            SUM(downloads) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
            ) AS downloads_last_month,
            SUM(downloads) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '7 days'
            ) AS downloads_last_week,
            SUM(downloads) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 day'
            ) AS downloads_last_day
        FROM downloads_agg
    ),
    downloads_by_day AS (
        SELECT
            ARRAY_AGG(
                (day, downloads)
                ORDER BY day
            ) AS downloads_by_day
        FROM (
            SELECT
                days.day,
                COALESCE(agg.downloads, 0) AS downloads
            FROM
                days_last_year days LEFT JOIN downloads_agg agg USING (day)
            WHERE agg.day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '365 days'
        ) AS t
    ),
    downloads_by_month AS (
        SELECT
            ARRAY_AGG(
                (month, downloads)
                ORDER BY month
            ) AS downloads_by_month
        FROM (
            SELECT
                months.month,
                COALESCE(SUM(agg.downloads), 0) AS downloads
            FROM
                months_last_year months
                LEFT JOIN downloads_agg agg
                    ON months.month = DATE_TRUNC('month', agg.day)
            GROUP BY month
        ) AS t
    ),
    popularity_stats AS (
        SELECT
            ARRAY_AGG(
                (package, downloads_last_month)
                ORDER BY position_last_month
            ) FILTER (
                WHERE position_last_month <= 10
            ) AS top_last_month,
            ARRAY_AGG(
                (package, downloads_all)
                ORDER BY position_all
            ) FILTER (
                WHERE position_all <= 30
            ) AS top_all
        FROM (
            SELECT
                package_tag AS package,
                RANK() OVER (ORDER BY COUNT(*) FILTER (
                    WHERE accessed_at >
                    CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
                ) DESC) AS position_last_month,
                RANK() OVER (ORDER BY COUNT(*) DESC) AS position_all,
                COUNT(*) FILTER (
                    WHERE accessed_at >
                    CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
                ) AS downloads_last_month,
                COUNT(*) AS downloads_all
            FROM
                downloads d
                JOIN files f USING (filename)
            GROUP BY package_tag
        ) AS t
    ),
    bandwidth_stats AS (
        SELECT
            SUM(f.filesize) AS downloads_bandwidth
        FROM downloads d JOIN files f USING (filename)
    ),
    time_saved_agg AS (
        SELECT
            CAST(DATE_TRUNC('day', accessed_at) AS DATE) AS day,
            SUM(CASE f.platform_tag
                -- Pi0s are about 6x slower than Pi3s on average
                WHEN 'linux_armv7l' THEN 1
                WHEN 'linux_armv6l' THEN 6
                ELSE 0
            END *
            CASE
                WHEN b.duration > INTERVAL '1 week' THEN INTERVAL '0'
                WHEN b.duration > INTERVAL '6.7 seconds' THEN
                    b.duration - INTERVAL '6.7 seconds'
                ELSE INTERVAL '0'
            END) AS time_saved
        FROM
            downloads d
            JOIN files f USING (filename)
            JOIN builds b USING (build_id)
        WHERE f.abi_tag <> 'none'
        GROUP BY day
    ),
    time_saved_stats AS (
        SELECT
            SUM(time_saved) AS time_saved_all,
            SUM(time_saved) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '365 days'
            ) AS time_saved_year,
            SUM(time_saved) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
            ) AS time_saved_month,
            SUM(time_saved) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '7 days'
            ) AS time_saved_week,
            SUM(time_saved) FILTER (
                WHERE day >
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 day'
            ) AS time_saved_day
        FROM time_saved_agg
    ),
    time_saved_by_month AS (
        SELECT
            ARRAY_AGG(
                (month, time_saved)
                ORDER BY month
            ) AS time_saved_by_month
        FROM (
            SELECT
                CAST(DATE_TRUNC('month', day) AS DATE) AS month,
                SUM(time_saved) AS time_saved
            FROM time_saved_agg
            WHERE day >= DATE_TRUNC(
                'month',
                CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '11 months')
            GROUP BY month
        ) AS t
    ),
    energy_saved_stats AS (
        SELECT
            SUM(
                5 * -- volts
                CASE f.platform_tag
                    -- https://www.pidramble.com/wiki/benchmarks/power-consumption
                    WHEN 'linux_armv7l' THEN 0.220 -- amps
                    WHEN 'linux_armv6l' THEN 0.080
                    ELSE 0.0
                END *
                CASE f.platform_tag
                    WHEN 'linux_armv7l' THEN 1
                    WHEN 'linux_armv6l' THEN 6
                    ELSE 0
                END *
                EXTRACT(EPOCH FROM CASE
                    WHEN b.duration > INTERVAL '1 week' THEN INTERVAL '0'
                    WHEN b.duration > INTERVAL '6.7 seconds' THEN
                        b.duration - INTERVAL '6.7 seconds'
                    ELSE INTERVAL '0'
                END) -- seconds
            ) / 3600000 AS power_saved_kwh
        FROM
            downloads d
            JOIN files f USING (filename)
            JOIN builds b USING (build_id)
        WHERE f.abi_tag <> 'none'
    ),
    popular_distros AS (
        SELECT
            RANK() OVER (ORDER BY COUNT(*) DESC) AS num,
            distro_name
        FROM downloads
        WHERE distro_name IS NOT NULL
        AND accessed_at >
            CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
        GROUP BY distro_name
    ),
    detail_agg AS (
        SELECT
            CASE py_name
                WHEN 'CPython' THEN
                    CASE WHEN py_version ~ '^(\d+\.\d+)'
                        THEN REGEXP_REPLACE(py_version, '^(\d+\.\d+).*$', '\1')
                        ELSE 'Other'
                    END
                ELSE 'Other'
            END AS python_version,
            COALESCE(CASE arch
                WHEN 'x86' THEN 'i686'
                WHEN 'armv8l' THEN 'aarch64'
                WHEN 'AMD64' THEN 'x86_64'
                ELSE arch
            END, 'Other') AS architecture,
            COALESCE(p.distro_name, 'Other') AS distribution,
            CASE
                WHEN p.distro_name IS NULL THEN 'Other'
                ELSE d.distro_version
            END AS release,
            CAST(DATE_TRUNC('month', accessed_at) AS DATE) AS month,
            COUNT(*) AS downloads
        FROM
            downloads d
            LEFT JOIN popular_distros p
                ON d.distro_name = p.distro_name
                AND p.num <= 5
        WHERE accessed_at >= DATE_TRUNC(
            'month',
            CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '11 months')
        GROUP BY
            python_version,
            architecture,
            distribution,
            release,
            month
    ),
    python_versions_by_month AS (
        SELECT
            ARRAY_AGG(
                (python_version, month, downloads)
                ORDER BY python_version, month
            ) AS python_versions_by_month
        FROM (
            SELECT python_version, month, SUM(downloads) AS downloads
            FROM detail_agg
            GROUP BY python_version, month
        ) AS t
    ),
    arch_by_month AS (
        SELECT
            ARRAY_AGG(
                (architecture, month, downloads)
                ORDER BY architecture, month
            ) AS arch_by_month
        FROM (
            SELECT architecture, month, SUM(downloads) AS downloads
            FROM detail_agg
            GROUP BY architecture, month
        ) AS t
    ),
    os_by_month AS (
        SELECT
            ARRAY_AGG(
                (distribution, month, downloads)
                ORDER BY distribution, month
            ) AS os_by_month
        FROM (
            SELECT distribution, month, SUM(downloads) AS downloads
            FROM detail_agg
            GROUP BY distribution, month
        ) AS t
    ),
    release_by_month AS (
        SELECT
            ARRAY_AGG(
                (release, month, downloads)
                ORDER BY release, month
            ) AS release_by_month
        FROM (
            SELECT release, month, SUM(downloads) AS downloads
            FROM detail_agg
            -- XXX Limit to configuration.native_distro
            GROUP BY release, month
        ) AS t
    ),
    version_stats AS (
        SELECT COUNT(*) AS new_last_hour
        FROM versions
        WHERE released > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '1 hour'
    )
    SELECT
        bs.builds_time,
        fs.builds_size,
        fc.packages_built,
        fc.files_count,
        CAST(vs.new_last_hour AS INTEGER)         AS new_last_hour,
        CAST(dl.downloads_all AS INTEGER)         AS downloads_all,
        CAST(dl.downloads_last_year AS INTEGER)   AS downloads_last_year,
        CAST(dl.downloads_last_month AS INTEGER)  AS downloads_last_month,
        CAST(dl.downloads_last_week AS INTEGER)   AS downloads_last_week,
        CAST(dl.downloads_last_day AS INTEGER)    AS downloads_last_day,
        CAST(dh.downloads_last_hour AS INTEGER)   AS downloads_last_hour,
        bw.downloads_bandwidth,
        ts.time_saved_all,
        ts.time_saved_year,
        ts.time_saved_month,
        ts.time_saved_week,
        ts.time_saved_day,
        CAST(es.power_saved_kwh AS DOUBLE PRECISION) AS power_saved_kwh,
        po.top_last_month,
        po.top_all,
        dm.downloads_by_month,
        dd.downloads_by_day,
        tm.time_saved_by_month,
        pm.python_versions_by_month,
        am.arch_by_month,
        om.os_by_month,
        rm.release_by_month
    FROM
        build_stats bs,
        file_count fc,
        file_stats fs,
        version_stats vs,
        popularity_stats po,
        bandwidth_stats bw,
        time_saved_stats ts,
        energy_saved_stats es,
        download_stats_year dl,
        download_stats_hour dh,
        downloads_by_month dm,
        downloads_by_day dd,
        time_saved_by_month tm,
        python_versions_by_month pm,
        arch_by_month am,
        os_by_month om,
        release_by_month rm
$sql$;

REVOKE ALL ON FUNCTION get_statistics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_statistics() TO {username};

-- get_builds_last_hour()
-------------------------------------------------------------------------------
-- Returns an ABI separated count of the builds in the last hour
-------------------------------------------------------------------------------

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

-- get_search_index()
-------------------------------------------------------------------------------
-- Returns a mapping of package name to download counts for all time, and the
-- last 30 days. This is used by the master to construct the search index.
-------------------------------------------------------------------------------

CREATE FUNCTION get_search_index()
    RETURNS TABLE(
        package packages.package%TYPE,
        downloads_recent INTEGER,
        downloads_all INTEGER
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT
        p.package,
        CAST(COALESCE(COUNT(d.filename) FILTER (
            WHERE d.accessed_at > CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '30 days'
        ), 0) AS INTEGER) AS downloads_recent,
        CAST(COALESCE(COUNT(d.filename), 0) AS INTEGER) AS downloads_all
    FROM
        packages AS p
        LEFT JOIN (
            builds AS b
            JOIN files AS f ON b.build_id = f.build_id
            JOIN downloads AS d ON d.filename = f.filename
        ) ON p.package = b.package
    GROUP BY p.package;
$sql$;

REVOKE ALL ON FUNCTION get_search_index() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_search_index() TO {username};

-- get_package_files(package)
-------------------------------------------------------------------------------
-- Returns the filenames and hashes of all files built for *package*.
-------------------------------------------------------------------------------

CREATE FUNCTION get_package_files(pkg TEXT)
    RETURNS TABLE(
        filename files.filename%TYPE,
        filehash files.filehash%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT f.filename, f.filehash
    FROM builds b JOIN files f USING (build_id)
    WHERE b.status AND b.package = pkg;
$sql$;

REVOKE ALL ON FUNCTION get_package_files(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_package_files(TEXT) TO {username};

-- get_version_files(package, version)
-------------------------------------------------------------------------------
-- Returns the filenames of all files for *version* of *package*.
-------------------------------------------------------------------------------

CREATE FUNCTION get_version_files(pkg TEXT, ver TEXT)
    RETURNS TABLE(
        filename files.filename%TYPE
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT f.filename
    FROM builds b JOIN files f USING (build_id)
    WHERE b.status AND b.package = pkg AND b.version = ver;
$sql$;

REVOKE ALL ON FUNCTION get_version_files(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_version_files(TEXT, TEXT) TO {username};

-- get_project_versions(package)
-------------------------------------------------------------------------------
-- Returns all information about versions and files for *package*, including
-- all successful builds and failed build attempts
-------------------------------------------------------------------------------

CREATE FUNCTION get_project_versions(pkg TEXT)
    RETURNS TABLE(
        version versions.version%TYPE,
        released TIMESTAMP WITH TIME ZONE,
        build_id builds.build_id%TYPE,
        skip versions.skip%TYPE,
        duration builds.duration%TYPE,
        status builds.status%TYPE,
        filename files.filename%TYPE,
        filesize files.filesize%TYPE,
        filehash files.filehash%TYPE,
        builder_abi builds.abi_tag%TYPE,
        file_abi_tag files.abi_tag%TYPE,
        platform_tag files.platform_tag%TYPE,
        apt_dependencies TEXT
    )
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT version, released AT TIME ZONE 'UTC', build_id, skip, duration,
    status, f.filename, filesize, filehash, b.abi_tag builder_abi,
    f.abi_tag file_abi_tag, platform_tag,
    string_agg(dependency, ' ') apt_dependencies
    FROM versions v
    LEFT JOIN builds b USING (package, version)
    LEFT JOIN files f USING (build_id)
    LEFT JOIN dependencies d ON f.filename = d.filename AND d.tool = 'apt'
    WHERE v.package = pkg
    GROUP BY version, released, build_id, skip, duration, status, f.filename,
    filesize, filehash, builder_abi, file_abi_tag, platform_tag
    ORDER BY released DESC, built_at DESC;
$sql$;

REVOKE ALL ON FUNCTION get_project_versions(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_versions(TEXT) TO {username};

-- get_project_files(package)
-------------------------------------------------------------------------------
-- Return details about all files built for the given *package*.
-------------------------------------------------------------------------------

CREATE FUNCTION get_project_files(pkg TEXT)
    RETURNS TABLE(
        version builds.version%TYPE,
        abi_tag files.abi_tag%TYPE,
        filename files.filename%TYPE,
        filesize files.filesize%TYPE,
        filehash files.filehash%TYPE
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
        f.filehash
    FROM
        builds b
        JOIN files f USING (build_id)
    WHERE b.status
    AND b.package = pkg;
$sql$;

REVOKE ALL ON FUNCTION get_project_files(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_project_files(TEXT) TO {username};

-- get_file_apt_dependencies(filename)
-------------------------------------------------------------------------------
-- Returns apt dependencies registered against the specified *filename*,
-- excluding those listed in preinstalled_apt_packages with a matching ABI tag.
-------------------------------------------------------------------------------

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

-- save_rewrites_pending(...)
-------------------------------------------------------------------------------
-- Saves the state of the_secretary task's internal buffer in the
-- rewrites_pending table.
-------------------------------------------------------------------------------

CREATE FUNCTION save_rewrites_pending(data rewrites_pending ARRAY)
    RETURNS VOID
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    DELETE FROM rewrites_pending;
    INSERT INTO rewrites_pending (
        package,
        added_at,
        command
    )
        SELECT
            d.package,
            d.added_at,
            d.command
        FROM
            UNNEST(data) AS d;
$sql$;

REVOKE ALL ON FUNCTION save_rewrites_pending(rewrites_pending ARRAY) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION save_rewrites_pending(rewrites_pending ARRAY) TO {username};

-- load_rewrites_pending()
-------------------------------------------------------------------------------
-- Loads the state of the_secretary's internal buffer from the rewrites_pending
-- table.
-------------------------------------------------------------------------------

CREATE FUNCTION load_rewrites_pending()
    RETURNS TABLE(
        package rewrites_pending.package%TYPE,
        added_at rewrites_pending.added_at%TYPE,
        command rewrites_pending.command%TYPE
    )
    LANGUAGE SQL
    CALLED ON NULL INPUT
    SECURITY DEFINER
    SET search_path = public, pg_temp
AS $sql$
    SELECT package, added_at, command
    FROM rewrites_pending
    ORDER BY added_at;
$sql$;

REVOKE ALL ON FUNCTION load_rewrites_pending() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION load_rewrites_pending() TO {username};

COMMIT;
