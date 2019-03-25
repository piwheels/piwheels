#!/usr/bin/env python

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

"""
Contains the functions that make up the :program:`piw-initdb` script.

.. autofunction:: main

.. autofunction:: detect_users

.. autofunction:: detect_version

.. autofunction:: get_connection

.. autofunction:: get_script

.. autofunction:: parse_statements
"""

import re
import io
import sys
import logging

from pkg_resources import resource_listdir, resource_string
from sqlalchemy import create_engine, text, exc
from sqlalchemy.engine.url import make_url

from .. import __version__, terminal, const


def main(args=None):
    """
    This is the main function for the :program:`piw-initdb` script. It creates
    the piwheels database required by the master or, if it already exists,
    upgrades it to the current version of the application.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[RuntimeError] = (
        terminal.error_handler.exc_message, 1)
    terminal.error_handler[exc.SQLAlchemyError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'initdb'
    parser = terminal.configure_parser("""\
The piw-initdb script is used to initialize or upgrade the piwheels master
database. The target PostgreSQL database must already exist, and the DSN should
connect as a cluster superuser (e.g. the postgres user), in contrast to the
piw-master script which should *not* use the cluster superuser. The script will
prompt before making any permanent alterations, and all actions will be
executed within a single transaction so that in the event of failure the
database will be left unchanged. Nonetheless, it is strongly recommended you
take a backup of your database before using this script for upgrades.
""")
    parser.add_argument(
        '--debug', action='store_true', help="Set logging to debug level")
    parser.add_argument(
        '-d', '--dsn', default=const.DSN,
        help="The database to create or upgrade; this DSN must connect as "
        "the cluster superuser (default: %(default)s)")
    parser.add_argument(
        '-u', '--user', metavar='NAME', default=const.USER,
        help="The name of the ordinary piwheels database user (default: "
        "%(default)s); this must *not* be a cluster superuser")
    parser.add_argument(
        '-y', '--yes', action='store_true',
        help="Proceed without prompting before init/upgrades")
    config = parser.parse_args(args)
    if config.debug:
        config.log_level = logging.DEBUG
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Initialize Database version %s", __version__)
    conn = get_connection(config.dsn)
    logging.info("Checking username and superuser status")
    detect_users(conn, config.user)
    logging.info("Adminstration and master users verified")
    logging.info("Detecting database version")
    db_version = detect_version(conn)
    if db_version is None:
        logging.warning("Database appears to be uninitialized")
        prompt = "Do you wish to initialize the database?"
    elif db_version == __version__:
        logging.warning("Database is the current version")
        return 0
    else:
        logging.warning("Detected database version %s", db_version)
        prompt = "Do you wish to proceed with the upgrade to %s?" % __version__
    script = get_script(db_version)
    if config.yes or terminal.yes_no_prompt(prompt):
        if db_version is None:
            logging.warning("Initializing database at version %s", __version__)
        else:
            logging.warning("Upgrading database to version %s", __version__)
            logging.warning("Have patience: this can be a long operation!")
        with conn.begin():
            dbname = conn.scalar("VALUES (current_database())")
            for statement in parse_statements(script):
                statement = statement.format(username=config.user, dbname=dbname)
                logging.debug(statement)
                conn.execute(text(statement))
                if not config.debug:
                    print('.', end='', flush=True)
            print("")
        logging.info("Complete")
    return 0


def get_connection(dsn):
    """
    Return an SQLAlchemy connection to the specified *dsn* or raise
    :exc:`RuntimeError` if the database doesn't exist (the administrator is
    expected to create the database before running this script).
    """
    try:
        db_url = make_url(dsn)
        engine = create_engine(db_url)
        return engine.connect()
    except exc.OperationalError:
        raise RuntimeError("Database %s does not exist" % db_url.database)


def detect_users(conn, test_user):
    """
    Test that the user for *conn* is a cluster superuser (so we can drop and
    create anything we want in the database), and that *test_user* (which will
    be granted limited rights to various objects for the purposes of the
    :program:`piw-master` script) exists and is *not* a cluster superuser.
    """
    # Check the user we're connected as is a cluster superuser
    username = conn.scalar(text("VALUES (CURRENT_USER)"))
    super_user = conn.scalar(text(
        "SELECT usesuper FROM pg_user WHERE usename = CURRENT_USER"))
    if not super_user:
        raise RuntimeError("User %s is not a cluster superuser" % username)
    # Check the "normal" user exists and warn if it's a cluster superuser
    super_user = conn.scalar(text(
        "SELECT usesuper FROM pg_user WHERE usename = :user"), user=test_user)
    if super_user is None:
        raise RuntimeError("User %s doesn't exist as a cluster user" % test_user)
    if super_user:
        raise RuntimeError("User %s is a cluster superuser; this is not "
                           "recommended" % test_user)


def detect_version(conn):
    """
    Detect the version of the database. This is typically done by reading the
    contents of the ``configuration`` table, but before that was added we can
    guess a couple of versions based on what tables exist (or don't). Returns
    ``None`` if the database appears uninitialized, and raises
    :exc:`RuntimeError` is the version is so ancient we can't do anything with
    it.
    """
    try:
        with conn.begin():
            db_version = conn.scalar(text(
                "SELECT version FROM configuration"))
    except exc.ProgrammingError:
        with conn.begin():
            packages_exists = bool(conn.scalar(text(
                "SELECT 1 FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' AND tablename = 'packages'")))
        with conn.begin():
            statistics_exists = bool(conn.scalar(text(
                "SELECT 1 FROM pg_catalog.pg_views "
                "WHERE schemaname = 'public' AND viewname = 'statistics'")))
        with conn.begin():
            files_exists = bool(conn.scalar(text(
                "SELECT 1 FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' AND tablename = 'files'")))
        if not packages_exists:
            # Database is uninitialized
            return None
        elif not files_exists:
            # Database is too ancient to upgrade
            raise RuntimeError("Database version older than 0.4; cannot upgrade")
        elif not statistics_exists:
            return "0.4"
        else:
            return "0.5"
    else:
        return db_version


def get_script(version=None):
    """
    Generate the script to get the database from *version* (the result of
    :func:`detect_version`) to the current version of the software. If
    *version* is ``None``, this is simply the contents of the
    :file:`sql/create_piwheels.sql` script. Otherwise, it is a concatenation of
    various update scripts.
    """
    if version is None:
        return resource_string(__name__, 'sql/create_piwheels.sql').decode('utf-8')
    # Build the list of upgradable versions from the scripts in the sql/
    # directory
    upgrades = {}
    ver_regex = re.compile(r'update_piwheels_(?P<from>.*)_to_(?P<to>.*)\.sql$')
    for filename in resource_listdir(__name__, 'sql'):
        match = ver_regex.match(filename)
        if match is not None:
            upgrades[match.group('from')] = (match.group('to'), filename)
    # Attempt to find a list of scripts which'll get us from the existing
    # version to the desired one. NOTE: This is a stupid algorithm which won't
    # attempt different branches or back-tracking so if you wind up with custom
    # versions or downgrade scripts in the sql directory, things will probably
    # break
    this_version = version
    output = []
    try:
        while this_version != __version__:
            this_version, filename = upgrades[this_version]
            output.append(resource_string(__name__, 'sql/' + filename))
    except KeyError:
        raise RuntimeError("Unable to find upgrade path from %s to %s" % (
            version, __version__))
    return ''.join(script.decode('utf-8') for script in output)


def parse_statements(script):
    """
    This is an extremely crude statement splitter for PostgreSQL's dialect of
    SQL. It understands ``--comments``, ``"quoted identifiers"``, ``'string
    literals'`` and ``$delim$ extended strings $delim$``, but not ``E'\\escaped
    strings'`` or ``/* C-style comments */``. If you start using such things in
    the update scripts, you'll need to extend this function to accommodate
    them.

    It returns a generator which yields individiual statements from *script*,
    delimited by semi-colon terminators.
    """
    # pylint: disable=too-many-branches
    stmt = ''
    quote = None
    for char in script:
        if quote != '--':
            stmt += char
        if quote is None:
            if char == ';':
                yield stmt.strip()
                stmt = ''
            elif char == "'":
                quote = "'"
            elif char == '"':
                quote = '"'
            elif char == '$':
                quote = '$'
            elif char == '-':
                quote = '-'
        elif quote in ('"', "'"):
            if quote == char:
                quote = None
        elif quote == '-':
            if char == '-':
                quote = '--'
                stmt = stmt[:-2]
            else:
                quote = None
        elif quote == '--':
            if char == '\n':
                quote = None
        else:
            assert quote.startswith('$')
            if len(quote) > 1 and quote.endswith('$'):
                if stmt.endswith(quote):
                    quote = None
            else:
                quote += char
    stmt = stmt.strip()
    if stmt:
        yield stmt


if __name__ == '__main__':
    main()
