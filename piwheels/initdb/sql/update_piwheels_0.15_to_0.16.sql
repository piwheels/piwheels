UPDATE configuration SET version = '0.16';

ALTER TABLE downloads
    ADD COLUMN installer_name      VARCHAR(20) DEFAULT NULL,
    ADD COLUMN installer_version   VARCHAR(100) DEFAULT NULL,
    ADD COLUMN setuptools_version  VARCHAR(100) DEFAULT NULL;

ALTER TABLE searches
    ADD COLUMN installer_name      VARCHAR(20) DEFAULT NULL,
    ADD COLUMN installer_version   VARCHAR(100) DEFAULT NULL,
    ADD COLUMN setuptools_version  VARCHAR(100) DEFAULT NULL,
    DROP CONSTRAINT searches_package_fk;

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

CREATE TABLE project_json_downloads (
    package             VARCHAR(200) NOT NULL,
    accessed_by         INET NOT NULL,
    accessed_at         TIMESTAMP NOT NULL,
    user_agent          VARCHAR(2000)
);

CREATE INDEX project_json_downloads_package ON project_json_downloads(package);
CREATE INDEX project_json_downloads_accessed_at ON project_json_downloads(accessed_at DESC);
GRANT SELECT ON project_json_downloads TO {username};

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

DROP FUNCTION log_download(
  TEXT, INET, TIMESTAMP,
  TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
);

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
