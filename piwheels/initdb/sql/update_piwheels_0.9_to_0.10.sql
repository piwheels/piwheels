UPDATE configuration SET version = '0.10';

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
