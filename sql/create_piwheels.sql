DROP TABLE IF EXISTS
    packages, package_versions, builds, metadata;

CREATE TABLE packages (
    package VARCHAR(200) NOT NULL,

    CONSTRAINT packages_pk PRIMARY KEY (package)
);
GRANT SELECT,INSERT,UPDATE,DELETE ON packages TO piwheels;

CREATE TABLE package_versions (
    package VARCHAR(200) NOT NULL,
    version VARCHAR(200) NOT NULL,

    CONSTRAINT pkgver_pk PRIMARY KEY (package, version),
    CONSTRAINT pkgver_pkg_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE RESTRICT
);
GRANT SELECT,INSERT,UPDATE,DELETE ON package_versions TO piwheels;

CREATE TABLE builds (
    package         VARCHAR(200) NOT NULL,
    version         VARCHAR(200) NOT NULL,
    built_at        TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    built_by        VARCHAR(100) DEFAULT NULL,
    duration        INTERVAL HOUR TO SECOND NOT NULL,
    output          TEXT NOT NULL,

    CONSTRAINT builds_pk PRIMARY KEY (package, version, built_at, built_by),
    CONSTRAINT builds_pkgver_fk FOREIGN KEY (package, version)
        REFERENCES package_versions ON DELETE CASCADE
);
GRANT SELECT,INSERT,UPDATE,DELETE ON builds TO piwheels;

CREATE INDEX builds_timestamp ON builds(built_at DESC NULLS LAST);
CREATE INDEX builds_pkgver ON builds(package, version);

CREATE TABLE files (
    filename            VARCHAR(255) NOT NULL,
    package             VARCHAR(200) NOT NULL,
    version             VARCHAR(200) NOT NULL,
    built_at            TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    built_by            VARCHAR(100) NOT NULL,
    filesize            INTEGER NOT NULL,
    filehash            CHAR(20) NOT NULL,
    package_version_tag VARCHAR(100) NOT NULL,
    py_version_tag      VARCHAR(100) NOT NULL,
    abi_tag             VARCHAR(100) NOT NULL,
    platform_tag        VARCHAR(100) NOT NULL,

    CONSTRAINT files_pk PRIMARY KEY (filename),
    CONSTRAINT files_builds_fk FOREIGN KEY (package, version, built_at, built_by)
        REFERENCES builds (package, version, built_at, built_by) ON DELETE CASCADE
);
GRANT SELECT,INSERT,UPDATE,DELETE ON files TO piwheels;

CREATE UNIQUE INDEX files_pkgver ON files(package, version, built_at, built_by);
CREATE INDEX files_size ON files(filesize);

COMMIT;
