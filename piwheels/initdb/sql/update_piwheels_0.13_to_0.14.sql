UPDATE configuration SET version = '0.14';

CREATE TABLE dependencies (
    filename            VARCHAR(255) NOT NULL,
    tool                VARCHAR(10) DEFAULT 'apt' NOT NULL,
    dependency          VARCHAR(255) NOT NULL,

    CONSTRAINT dependencies_pk PRIMARY KEY (filename, tool, dependency),
    CONSTRAINT dependencies_files_fk FOREIGN KEY (filename)
        REFERENCES files(filename) ON DELETE CASCADE,
    CONSTRAINT dependencies_tool_ck CHECK (tool IN ('apt', 'pip', ''))
);

GRANT SELECT,INSERT ON dependencies TO {username};

COMMIT;
