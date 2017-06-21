DROP TABLE IF EXISTS
    packages, package_versions, builds, metadata;

CREATE TABLE packages (
    package TEXT PRIMARY KEY
);
GRANT ALL ON packages TO piwheels;

CREATE TABLE package_versions (
    package TEXT,
    version TEXT,
    PRIMARY KEY (package, version),
    FOREIGN KEY (package) REFERENCES packages
);
GRANT ALL ON package_versions TO piwheels;

CREATE TABLE builds (
    build_id SERIAL PRIMARY KEY,
    build_timestamp TIMESTAMP DEFAULT NOW(),
    package TEXT,
    version TEXT,
    status BOOLEAN,
    output TEXT,
    filename TEXT,
    filesize INT,
    build_time NUMERIC,
    package_version_tag TEXT,
    py_version_tag TEXT,
    abi_tag TEXT,
    platform_tag TEXT,
    FOREIGN KEY (package, version) REFERENCES package_versions
);
GRANT ALL ON builds TO piwheels;

CREATE TABLE metadata (
    key TEXT,
    value BOOLEAN
);
GRANT ALL ON metadata TO piwheels;

GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO piwheels;

INSERT INTO
    metadata
VALUES (
    'active',
    true
);
