DROP TABLE IF EXISTS
    packages, package_versions, versions, builds, files, metadata;

CREATE TABLE packages (
    package VARCHAR(200) NOT NULL,
    skip    BOOLEAN DEFAULT false NOT NULL,

    CONSTRAINT packages_pk PRIMARY KEY (package)
);
GRANT SELECT,INSERT,UPDATE,DELETE ON packages TO piwheels;

CREATE INDEX packages_skip ON packages(skip);

CREATE TABLE versions (
    package VARCHAR(200) NOT NULL,
    version VARCHAR(200) NOT NULL,
    skip    BOOLEAN DEFAULT false NOT NULL,

    CONSTRAINT versions_pk PRIMARY KEY (package, version),
    CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE RESTRICT
);
GRANT SELECT,INSERT,UPDATE,DELETE ON versions TO piwheels;

CREATE INDEX versions_skip ON versions(skip);

CREATE TABLE builds (
    build_id        SERIAL NOT NULL,
    package         VARCHAR(200) NOT NULL,
    version         VARCHAR(200) NOT NULL,
    built_by        INTEGER DEFAULT NULL,
    built_at        TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    duration        INTERVAL NOT NULL,
    status          BOOLEAN DEFAULT true NOT NULL,
    output          TEXT NOT NULL,

    CONSTRAINT builds_pk PRIMARY KEY (build_id),
    CONSTRAINT builds_unique UNIQUE (package, version, built_at, built_by),
    CONSTRAINT builds_versions_fk FOREIGN KEY (package, version)
        REFERENCES versions ON DELETE CASCADE,
    CONSTRAINT builds_built_by_ck CHECK (built_by >= 1)
);
GRANT SELECT,INSERT,UPDATE,DELETE ON builds TO piwheels;

CREATE INDEX builds_timestamp ON builds(built_at DESC NULLS LAST);
CREATE INDEX builds_pkgver ON builds(package, version);

CREATE TABLE files (
    filename            VARCHAR(255) NOT NULL,
    build_id            INTEGER NOT NULL,
    filesize            INTEGER NOT NULL,
    filehash            CHAR(32) NOT NULL,
    package_version_tag VARCHAR(100) NOT NULL,
    py_version_tag      VARCHAR(100) NOT NULL,
    abi_tag             VARCHAR(100) NOT NULL,
    platform_tag        VARCHAR(100) NOT NULL,

    CONSTRAINT files_pk PRIMARY KEY (filename),
    CONSTRAINT files_builds_fk FOREIGN KEY (build_id)
        REFERENCES builds (build_id) ON DELETE CASCADE
);
GRANT SELECT,INSERT,UPDATE,DELETE ON files TO piwheels;

CREATE UNIQUE INDEX files_pkgver ON files(build_id);
CREATE INDEX files_size ON files(filesize);

COMMIT;
