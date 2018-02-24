UPDATE configuration SET version = '0.12';

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

    CONSTRAINT packages_package_fk FOREIGN KEY (package)
        REFERENCES packages (package) ON DELETE CASCADE
);

CREATE INDEX searches_package ON searches(package);
CREATE INDEX searches_accessed_at ON searches(accessed_at DESC);
GRANT SELECT,INSERT ON searches TO {username};

COMMIT;
