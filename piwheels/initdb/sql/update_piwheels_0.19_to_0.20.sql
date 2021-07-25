UPDATE configuration SET version = '0.20';

ALTER TABLE build_abis
    ADD COLUMN python_name  VARCHAR(100) DEFAULT '' NOT NULL,
    ADD COLUMN python_major INTEGER NOT NULL,
    ADD COLUMN python_minor INTEGER NOT NULL,
    ADD COLUMN os_release   VARCHAR(100) DEFAULT '' NOT NULL;