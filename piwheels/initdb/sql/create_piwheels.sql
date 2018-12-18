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

    CONSTRAINT config_pk PRIMARY KEY (id)
);

INSERT INTO configuration(id, version) VALUES (1, '0.13');
GRANT SELECT,UPDATE ON configuration TO {username};

-- packages
-------------------------------------------------------------------------------
-- The "packages" table defines all available packages on PyPI, derived from
-- the list_packages() API. The "skip" column defaults to NULL but can be set
-- to a non-NULL string indicating why a package should not be built.
-------------------------------------------------------------------------------

CREATE TABLE packages (
    package VARCHAR(200) NOT NULL,
    skip    VARCHAR(100) DEFAULT NULL,

    CONSTRAINT packages_pk PRIMARY KEY (package)
);

GRANT SELECT,INSERT,UPDATE ON packages TO {username};

-- versions
-------------------------------------------------------------------------------
-- The "versions" table defines all versions of packages *with files* on PyPI;
-- note that versions without released files (a common occurrence) are
-- excluded. Like the "packages" table, the "skip" column can be set to a
-- non-NULL string indicating why a version should not be built.
-------------------------------------------------------------------------------

CREATE TABLE versions (
    package  VARCHAR(200) NOT NULL,
    version  VARCHAR(200) NOT NULL,
    released TIMESTAMP DEFAULT '1970-01-01 00:00:00' NOT NULL,
    skip     VARCHAR(100) DEFAULT NULL,

    CONSTRAINT versions_pk PRIMARY KEY (package, version),
    CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE RESTRICT
);

CREATE INDEX versions_package ON versions(package);
CREATE INDEX versions_skip ON versions((skip IS NULL), package);
GRANT SELECT,INSERT,UPDATE ON versions TO {username};

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
GRANT SELECT,INSERT,DELETE ON builds TO {username};
GRANT USAGE ON builds_build_id_seq TO {username};

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

GRANT SELECT,INSERT ON output TO {username};

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
GRANT SELECT,INSERT,UPDATE ON files TO {username};

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

    CONSTRAINT downloads_filename_fk FOREIGN KEY (filename)
        REFERENCES files (filename) ON DELETE CASCADE
);

CREATE INDEX downloads_files ON downloads(filename);
CREATE INDEX downloads_accessed_at ON downloads(accessed_at DESC);
GRANT SELECT,INSERT ON downloads TO {username};

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

    CONSTRAINT searches_package_fk FOREIGN KEY (package)
        REFERENCES packages (package) ON DELETE CASCADE
);

CREATE INDEX searches_package ON searches(package);
CREATE INDEX searches_accessed_at ON searches(accessed_at DESC);
GRANT SELECT,INSERT ON searches TO {username};

-- builds_pending
-------------------------------------------------------------------------------
-- The "builds_pending" view is the basis of the build queue in the master. The
-- "packages", "versions" and "build_abis" tables form the basis of what needs
-- to be built. The "builds" and "files" tables define what's been attempted,
-- what's succeeded, and for which ABIs. This view combines all this
-- information and returns "package", "version", "abi" tuples defining what
-- requires building next.
--
-- There are some things to note about the behaviour of the queue. When no
-- builds of a package have been attempted, only the "lowest" ABI is attempted.
-- This is because most packages wind up with the "none" ABI which is
-- compatible with everything. The "lowest" is attempted just in case
-- dependencies in later Python versions are incompatible with earlier
-- versions. Once a package has a file with the "none" ABI, no further builds
-- are attempted (naturally). Only if the initial build generated something
-- with a specific ABI (something other than "none") are builds for the other
-- ABIs listed in "build_abis" attempted.
-------------------------------------------------------------------------------

CREATE VIEW builds_pending AS
SELECT
    package,
    version,
    MIN(abi_tag) AS abi_tag
FROM (
    SELECT
        v.package,
        v.version,
        b.abi_tag
    FROM
        packages AS p
        JOIN versions AS v ON v.package = p.package
        CROSS JOIN build_abis AS b
    WHERE
        v.skip IS NULL
        AND p.skip IS NULL

    EXCEPT ALL

    (
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
) AS t
GROUP BY
    package,
    version;

GRANT SELECT ON builds_pending TO {username};

-- statistics
-------------------------------------------------------------------------------
-- The "statistics" view generates various statistics from the tables in the
-- system. It is used by the big_brother task to report the status of the
-- system to the monitor.
--
-- The view is broken up into numerous CTEs for performance purposes. Normally
-- CTEs aren't much good for performance in PostgreSQL but as each one only
-- returns a single row here they work well.
-------------------------------------------------------------------------------

CREATE VIEW statistics AS
    WITH package_stats AS (
        SELECT COUNT(*) AS packages_count
        FROM packages
        WHERE skip IS NULL
    ),
    version_stats AS (
        SELECT COUNT(*) AS versions_count
        FROM packages p JOIN versions v ON p.package = v.package
        WHERE p.skip IS NULL AND v.skip IS NULL
    ),
    build_vers AS (
        SELECT COUNT(*) AS versions_tried
        FROM (SELECT DISTINCT package, version FROM builds) AS t
    ),
    build_stats AS (
        SELECT
            COUNT(*) AS builds_count,
            COUNT(*) FILTER (WHERE status) AS builds_count_success,
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
    build_latest AS (
        SELECT COUNT(*) AS builds_count_last_hour
        FROM builds
        WHERE built_at > CURRENT_TIMESTAMP - INTERVAL '1 hour'
    ),
    build_pkgs AS (
        SELECT COUNT(*) AS packages_built
        FROM (
            SELECT DISTINCT package
            FROM builds b JOIN files f ON b.build_id = f.build_id
            WHERE b.status
        ) AS t
    ),
    file_count AS (
        SELECT COUNT(*) AS files_count
        FROM files
    ),
    file_stats AS (
        -- Exclude armv6l packages as they're just hard-links to armv7l packages
        -- and thus don't really count towards space used
        SELECT COALESCE(SUM(filesize), 0) AS builds_size
        FROM files
        WHERE platform_tag <> 'linux_armv6l'
    ),
    download_stats AS (
        SELECT COUNT(*) AS downloads_last_month
        FROM downloads
        WHERE accessed_at > CURRENT_TIMESTAMP - INTERVAL '1 month'
    )
    SELECT
        p.packages_count,
        bp.packages_built,
        v.versions_count,
        bv.versions_tried,
        bs.builds_count,
        bs.builds_count_success,
        bl.builds_count_last_hour,
        bs.builds_time,
        fc.files_count,
        fs.builds_size,
        dl.downloads_last_month
    FROM
        package_stats p,
        version_stats v,
        build_pkgs bp,
        build_vers bv,
        build_stats bs,
        build_latest bl,
        file_count fc,
        file_stats fs,
        download_stats dl;

GRANT SELECT ON statistics TO {username};

-- downloads_recent
-------------------------------------------------------------------------------
-- The "downloads_recent" view lists all non-skipped packages, along with their
-- download count for the last month. This is used as the basis of the package
-- search index.
-------------------------------------------------------------------------------

CREATE VIEW downloads_recent AS
SELECT
    p.package,
    COUNT(*) AS downloads
FROM
    packages AS p
    LEFT JOIN (
        builds AS b
        JOIN files AS f ON b.build_id = f.build_id
        JOIN downloads AS d ON d.filename = f.filename
    ) ON p.package = b.package
WHERE
    d.accessed_at IS NULL
    OR d.accessed_at > CURRENT_TIMESTAMP - INTERVAL '1 month'
GROUP BY p.package;

GRANT SELECT ON downloads_recent TO {username};

COMMIT;
