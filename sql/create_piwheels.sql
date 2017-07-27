DROP TABLE IF EXISTS
    files, builds, versions, packages, package_versions, metadata;

CREATE TABLE packages (
    package VARCHAR(200) NOT NULL,

    CONSTRAINT packages_pk PRIMARY KEY (package)
);
GRANT SELECT,INSERT,UPDATE,DELETE ON packages TO piwheels;

CREATE TABLE versions (
    package VARCHAR(200) NOT NULL,
    version VARCHAR(200) NOT NULL,

    CONSTRAINT versions_pk PRIMARY KEY (package, version),
    CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages(package) ON DELETE RESTRICT
);
GRANT SELECT,INSERT,UPDATE,DELETE ON versions TO piwheels;

CREATE TABLE files (
    filename            VARCHAR(255) NOT NULL,
    filesize            INTEGER NOT NULL,
    filehash            CHAR(20) NOT NULL,
    package_version_tag VARCHAR(100) NOT NULL,
    py_version_tag      VARCHAR(100) NOT NULL,
    abi_tag             VARCHAR(100) NOT NULL,
    platform_tag        VARCHAR(100) NOT NULL,

    CONSTRAINT files_pk PRIMARY KEY (filename)
);
GRANT SELECT,INSERT,UPDATE,DELETE ON files TO piwheels;

CREATE INDEX files_size ON files(filesize);

CREATE TABLE builds (
    package         VARCHAR(200) NOT NULL,
    version         VARCHAR(200) NOT NULL,
    built_at        TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    built_by        VARCHAR(100) DEFAULT NULL,
    duration        INTERVAL NOT NULL,
    output          TEXT NOT NULL,
    filename        VARCHAR(255) DEFAULT NULL,

    CONSTRAINT builds_pk UNIQUE (package, version, built_at, built_by),
    CONSTRAINT builds_versions_fk FOREIGN KEY (package, version)
        REFERENCES versions(package, version) ON DELETE CASCADE,
    CONSTRAINT builds_filename_fk FOREIGN KEY (filename)
        REFERENCES files(filename) ON DELETE SET NULL
);
GRANT SELECT,INSERT,UPDATE,DELETE ON builds TO piwheels;

CREATE INDEX builds_timestamp ON builds(built_at DESC NULLS LAST);
CREATE INDEX builds_pkgver ON builds(package, version);
CREATE INDEX builds_filename ON builds(filename);

COMMIT;
