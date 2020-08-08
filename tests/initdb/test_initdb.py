# The piwheels project
#   Copyright (c) 2017 Ben Nuttall <https://github.com/bennuttall>
#   Copyright (c) 2017 Dave Jones <dave@waveform.org.uk>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


import os
from unittest import mock

import pytest

from conftest import find_message, PIWHEELS_USER, PIWHEELS_SUPERUSER
from piwheels import __version__
from piwheels.initdb import main, detect_version, parse_statements


@pytest.fixture()
def create_script_04(request):
    # The database creation script for v0.4. This is used in the database
    # upgrade tests below.
    return """
CREATE TABLE packages (
    package VARCHAR(200) NOT NULL,
    skip    BOOLEAN DEFAULT false NOT NULL,
    CONSTRAINT packages_pk PRIMARY KEY (package)
);
GRANT SELECT,INSERT,UPDATE,DELETE ON packages TO piwheels;
CREATE INDEX packages_skip ON packages(skip);
CREATE TABLE versions (
    package VARCHAR(200) NOT NULL,
    version VARCHAR(200) NOT NULL,
    skip    BOOLEAN DEFAULT false NOT NULL,
    CONSTRAINT versions_pk PRIMARY KEY (package, version),
    CONSTRAINT versions_package_fk FOREIGN KEY (package)
        REFERENCES packages ON DELETE RESTRICT
);
GRANT SELECT,INSERT,UPDATE,DELETE ON versions TO piwheels;
CREATE INDEX versions_skip ON versions(skip);
CREATE TABLE builds (
    build_id        SERIAL NOT NULL,
    package         VARCHAR(200) NOT NULL,
    version         VARCHAR(200) NOT NULL,
    built_by        INTEGER NOT NULL,
    built_at        TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    duration        INTERVAL NOT NULL,
    status          BOOLEAN DEFAULT true NOT NULL,
    output          TEXT NOT NULL,
    CONSTRAINT builds_pk PRIMARY KEY (build_id),
    CONSTRAINT builds_unique UNIQUE (package, version, built_at, built_by),
    CONSTRAINT builds_versions_fk FOREIGN KEY (package, version)
        REFERENCES versions ON DELETE CASCADE,
    CONSTRAINT builds_built_by_ck CHECK (built_by >= 1)
);
GRANT SELECT,INSERT,UPDATE,DELETE ON builds TO piwheels;
CREATE INDEX builds_timestamp ON builds(built_at DESC NULLS LAST);
CREATE INDEX builds_pkgver ON builds(package, version);
CREATE TABLE files (
    filename            VARCHAR(255) NOT NULL,
    build_id            INTEGER NOT NULL,
    filesize            INTEGER NOT NULL,
    filehash            CHAR(64) NOT NULL,
    package_version_tag VARCHAR(100) NOT NULL,
    py_version_tag      VARCHAR(100) NOT NULL,
    abi_tag             VARCHAR(100) NOT NULL,
    platform_tag        VARCHAR(100) NOT NULL,

    CONSTRAINT files_pk PRIMARY KEY (filename),
    CONSTRAINT files_builds_fk FOREIGN KEY (build_id)
        REFERENCES builds (build_id) ON DELETE CASCADE
);
GRANT SELECT,INSERT,UPDATE,DELETE ON files TO piwheels;
CREATE UNIQUE INDEX files_pkgver ON files(build_id);
CREATE INDEX files_size ON files(filesize);
"""


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--dsn' in out
    assert '--user' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_bad_db():
    with pytest.raises(RuntimeError) as exc:
        # hopefully you don't have a database named this...
        main(['--dsn', 'postgresql:///djskalfjsqklfjdsklfjklsd'])
        assert 'does not exist' in str(exc)


def test_not_a_superuser(db, with_clean_db, db_url):
    with pytest.raises(RuntimeError) as exc:
        main(['--dsn', db_url])
        assert 'not a cluster superuser' in str(exc)


def test_bad_user(db, with_clean_db, db_super_url):
    with pytest.raises(RuntimeError) as exc:
        # hopefully you don't have a user named this...
        main(['--dsn', db_super_url, '--user', 'fdjskalfjdsklfdsjk'])
        assert "doesn't exist as a cluster user" in str(exc)


def test_user_is_superuser(db, with_clean_db, db_super_url):
    with pytest.raises(RuntimeError) as exc:
        # hopefully you don't have a user named this...
        main(['--dsn', db_super_url, '--user', PIWHEELS_SUPERUSER])
        assert "is a cluster superuser; this is not recommended" in str(exc)


def test_new_abort(db, with_clean_db, db_super_url, caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        assert main(['--dsn', db_super_url, '--user', PIWHEELS_USER]) == 0
    assert find_message(caplog.records,
                        message='Database appears to be uninitialized')


def test_current_version(db, with_schema, db_super_url, caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        assert main(['--dsn', db_super_url, '--user', PIWHEELS_USER]) == 0
    assert find_message(caplog.records,
                        message='Database is the current version')


def test_no_path(db, with_schema, db_super_url, caplog):
    with mock.patch('piwheels.initdb.__version__', 'foo'):
        with pytest.raises(RuntimeError) as exc:
            main(['--dsn', db_super_url, '--user', PIWHEELS_USER, '--yes'])
            assert 'Unable to find upgrade path' in str(exc)


def test_too_ancient(db, with_schema):
    with db.begin():
        db.execute("DROP TABLE configuration")
        db.execute("DROP TABLE files CASCADE")
    with pytest.raises(RuntimeError) as exc:
        detect_version(db)
        assert 'Database version older than 0.4' in str(exc)


def test_detect_04(db, with_schema):
    with db.begin():
        db.execute("DROP TABLE configuration")
    assert detect_version(db) == '0.4'


def test_detect_05(db, with_schema):
    with db.begin():
        db.execute("DROP TABLE configuration")
        db.execute("CREATE VIEW statistics(i) AS VALUES (1)")
    assert detect_version(db) == '0.5'


def test_parse_statements():
    assert list(parse_statements('-- This is a comment\nDROP TABLE foo;')) == ['DROP TABLE foo;']
    assert list(parse_statements("VALUES (-1, '- not a comment -')")) == ["VALUES (-1, '- not a comment -')"]
    assert list(parse_statements('DROP TABLE bar;\nDROP TABLE foo\n')) == ['DROP TABLE bar;', 'DROP TABLE foo']
    assert list(parse_statements("VALUES (';');")) == ["VALUES (';');"]
    assert list(parse_statements('DROP TABLE "little;bobby;tables";')) == ['DROP TABLE "little;bobby;tables";']
    fn = """
CREATE FUNCTION foo(i integer) RETURNS text
LANGUAGE SQL
AS $sql$
   VALUES ('foo');
$sql$;"""
    assert list(parse_statements(fn)) == [fn.strip()]


def test_init(db, with_clean_db, db_super_url, caplog):
    assert main(['--dsn', db_super_url, '--user', PIWHEELS_USER, '--yes']) == 0
    with db.begin():
        for row in db.execute("SELECT version FROM configuration"):
            assert row[0] == __version__
            break
        else:
            assert False, "Didn't find version row in configuration"
    assert find_message(caplog.records,
                        message='Initializing database at '
                        'version %s' % __version__)


def test_init_debug(db, with_clean_db, db_super_url, caplog):
    assert main(['--dsn', db_super_url, '--user', PIWHEELS_USER, '--yes', '--debug']) == 0
    with db.begin():
        for row in db.execute("SELECT version FROM configuration"):
            assert row[0] == __version__
            break
        else:
            assert False, "Didn't find version row in configuration"
    assert find_message(
        caplog.records,
        message='Initializing database at version %s' % __version__)
    assert find_message(
        caplog.records,
        message='REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;')
    assert find_message(
        caplog.records,
        message='REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;')
    assert find_message(
        caplog.records,
        message='CREATE INDEX builds_timestamp ON builds(built_at DESC NULLS LAST);')
    assert find_message(
        caplog.records,
        message='CREATE INDEX files_builds ON files(build_id);')


def test_full_upgrade(db, with_clean_db, db_super_url, caplog, create_script_04):
    # The following is the creation script from the ancient 0.4 version; this
    # is deliberately picked so we run through all subsequent update scripts
    # testing they all apply cleanly ... albeit with an empty database which
    # won't test the harder bits
    with db.begin():
        for statement in parse_statements(create_script_04):
            db.execute(statement)
    assert main(['--dsn', db_super_url, '--user', PIWHEELS_USER, '--yes']) == 0
    with db.begin():
        for row in db.execute("SELECT version FROM configuration"):
            assert row[0] == __version__
            break
        else:
            assert False, "Didn't find version row in configuration"
    assert find_message(caplog.records,
                        message='Upgrading database to '
                        'version %s' % __version__)


def test_upgraded_structure(db, with_schema, db_super_url, create_script_04):
    # The following checks that the resulting database structure from a full
    # upgrade (see above) matches that of a clean creation
    def db_structure():
        with db.begin():
            return {
                'relations': list(db.execute("""\
                    SELECT
                        cls.relname,
                        cls.relkind,
                        CASE WHEN cls.relkind IN ('v', 'm')
                            THEN pg_get_viewdef(cls.oid)
                            ELSE ''
                        END AS reldef,
                        obj_description(cls.oid, 'pg_class') AS relcomment
                    FROM
                        pg_catalog.pg_class cls
                        JOIN pg_catalog.pg_namespace nsp
                            ON cls.relnamespace = nsp.oid
                    WHERE
                        nsp.nspname = 'public'
                    ORDER BY
                        relname;
                    """)),
                'columns': list(db.execute("""\
                    SELECT
                        attrelid::regclass::name AS attrelname,
                        ROW_NUMBER() OVER (PARTITION BY attrelid ORDER BY attnum) AS attnum,
                        attname,
                        atttypid::regtype::name AS atttype,
                        atttypmod,
                        attnotnull,
                        pg_get_expr(ad.adbin, cls.oid) AS attdefault,
                        col_description(cls.oid, att.attnum) AS attcomment
                    FROM
                        pg_catalog.pg_attribute att
                        JOIN pg_catalog.pg_class cls
                            ON att.attrelid = cls.oid
                        JOIN pg_catalog.pg_namespace nsp
                            ON cls.relnamespace = nsp.oid
                        LEFT JOIN pg_catalog.pg_attrdef ad
                            ON att.attrelid = ad.adrelid AND att.attnum = ad.adnum
                    WHERE
                        nsp.nspname = 'public'
                        AND att.attnum > 0
                        AND NOT att.attisdropped
                    ORDER BY
                        attrelname, attnum
                    """)),
                'constraints': list(db.execute("""\
                    SELECT
                        con.conname,
                        pg_get_constraintdef(con.oid) AS condef,
                        obj_description(con.oid, 'pg_constraint') AS concomment
                    FROM
                        pg_catalog.pg_constraint con
                        JOIN pg_catalog.pg_namespace nsp
                            ON con.connamespace = nsp.oid
                    WHERE
                        nsp.nspname = 'public'
                    ORDER BY
                        conname;
                    """)),
                'functions': list(db.execute("""\
                    SELECT
                        pro.proname,
                        pg_get_function_arguments(pro.oid) AS proargs,
                        pg_get_functiondef(pro.oid) AS prodef,
                        obj_description(pro.oid, 'pg_proc') AS procomment
                    FROM
                        pg_catalog.pg_proc pro
                        JOIN pg_catalog.pg_namespace nsp
                            ON pro.pronamespace = nsp.oid
                    WHERE
                        nsp.nspname = 'public'
                    ORDER BY
                        proname, proargs;
                    """)),
                'triggers': list(db.execute("""\
                    SELECT
                        tg.tgname,
                        tg.tgrelid::regclass::name AS tgrelname,
                        tg.tgtype,
                        tg.tgfoid::regproc::name AS tgprocname,
                        obj_description(tg.oid, 'pg_trigger') AS tgcomment
                    FROM
                        pg_catalog.pg_trigger tg
                        JOIN pg_catalog.pg_class cls
                            ON tg.tgrelid = cls.oid
                        JOIN pg_catalog.pg_namespace nsp
                            ON cls.relnamespace = nsp.oid
                    WHERE
                        nsp.nspname = 'public'
                        AND NOT tg.tgisinternal
                    ORDER BY
                        tgrelname, tgname;
                    """)),
                'privileges': list(db.execute("""\
                    WITH users(name) AS (
                        VALUES ('{user}'), ('{superuser}'), ('public')
                    ),
                    schemas(name) AS (
                        VALUES ('public')
                    ),
                    tables AS (
                        SELECT t.table_schema || '.' || t.table_name AS name
                        FROM information_schema.tables t
                        JOIN schemas s ON s.name = t.table_schema
                        WHERE table_type IN ('BASE TABLE', 'VIEW')
                    ),
                    db_privs(name) AS (
                        VALUES ('CREATE'), ('CONNECT'), ('TEMPORARY')
                    ),
                    schema_privs(name) AS (
                        VALUES ('CREATE'), ('USAGE')
                    ),
                    table_privs(name) AS (
                        VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'),
                               ('TRUNCATE'), ('REFERENCES'), ('TRIGGER')
                    )
                    SELECT
                        'database'         AS obj_type,
                        current_database() AS obj_id,
                        dp.name            AS privilege,
                        u.name             AS username
                    FROM users u, db_privs dp
                    WHERE has_database_privilege(u.name, current_database(), dp.name)

                    UNION ALL

                    SELECT
                        'schema'           AS obj_type,
                        sc.name            AS obj_id,
                        sp.name            AS privilege,
                        u.name             AS username
                    FROM users u, schemas sc, schema_privs sp
                    WHERE has_schema_privilege(u.name, sc.name, sp.name)

                    UNION ALL

                    SELECT
                        'table'            AS obj_type,
                        tb.name            AS obj_id,
                        tp.name            AS privilege,
                        u.name             AS username
                    FROM users u, tables tb, table_privs tp
                    WHERE has_table_privilege(u.name, tb.name, tp.name)

                    ORDER BY obj_type, obj_id, privilege, username
                    """.format(
                        user=PIWHEELS_USER,
                        superuser=PIWHEELS_SUPERUSER
                    ))),
            }
            permissions = []
            return relation_defs, column_defs, constraint_defs, function_defs, trigger_defs
    create_structure = db_structure()
    with db.begin():
        # Wipe the public schema and re-create it with standard defaults
        db.execute("DROP SCHEMA public CASCADE")
        db.execute("CREATE SCHEMA public AUTHORIZATION postgres")
        db.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
        db.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
    with db.begin():
        for statement in parse_statements(create_script_04):
            db.execute(statement)
    assert main(['--dsn', db_super_url, '--user', PIWHEELS_USER, '--yes']) == 0
    upgrade_structure = db_structure()
    assert create_structure == upgrade_structure
