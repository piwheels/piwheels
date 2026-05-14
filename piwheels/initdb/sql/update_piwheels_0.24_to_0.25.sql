UPDATE configuration SET version = '0.25';

CREATE TABLE metadata_downloads (
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

CREATE INDEX metadata_downloads_files ON metadata_downloads(filename);
CREATE INDEX metadata_downloads_accessed_at ON metadata_downloads(accessed_at DESC);
GRANT SELECT ON metadata_downloads TO {username};

CREATE FUNCTION log_metadata_download(
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
    INSERT INTO metadata_downloads (
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

REVOKE ALL ON FUNCTION log_metadata_download(
    TEXT, INET, TIMESTAMP,
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION log_metadata_download(
    TEXT, INET, TIMESTAMP,
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
    ) TO {username};
