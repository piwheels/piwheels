CREATE TABLE configuration (
    id INTEGER DEFAULT 1 NOT NULL,
    version VARCHAR(16) DEFAULT '0.6' NOT NULL,
    pypi_serial INTEGER DEFAULT 0 NOT NULL,

    CONSTRAINT config_pk PRIMARY KEY (id)
);
INSERT INTO configuration(id) VALUES (1);
GRANT UPDATE ON configuration TO piwheels;

COMMIT;
