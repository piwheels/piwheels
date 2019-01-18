==========
piw-initdb
==========

The piw-initdb script is used to initialize or upgrade the piwheels master
database. The target `PostgreSQL`_ database must already exist, and the DSN
should connect as a cluster superuser (e.g. the postgres user), in contrast to
the piw-master script which should *not* use the cluster superuser. The script
will prompt before making any permanent alterations, and all actions will be
executed within a single transaction so that in the event of failure the
database will be left unchanged. Nonetheless, it is strongly recommended you
take a backup of your database before using this script for upgrades.

Synopsis
========

::

    piw-initdb [-h] [--version] [-c FILE] [-q] [-v] [-l FILE] [-d DSN]
               [-u NAME] [-y]


Description
===========

.. program:: piw-initdb

.. option:: -h, --help

    show this help message and exit

.. option:: --version

    show program's version number and exit

.. option:: -c FILE, --configuration FILE

    Specify a configuration file to load

.. option:: -q, --quiet

    produce less console output

.. option:: -v, --verbose

    produce more console output

.. option:: -l FILE, --log-file FILE

    log messages to the specified file

.. option:: -d DSN, --dsn DSN

    The database to create or upgrade; this DSN must connect as the cluster
    superuser (default: postgres:///piwheels)

.. option:: -u NAME, --user NAME

    The name of the ordinary piwheels database user (default: piwheels); this
    must *not* be a cluster superuser

.. option:: -y, --yes

    Proceed without prompting before init/upgrades


Usage
=====

This script is intended to be used after installation to initialize the
piwheels master database. Note that it does *not* create the database or the
users for the database. It merely creates the tables, views, and other
structures within an already existing database. See the :doc:`overview` chapter
for typical usage.

The script can also be used to upgrade an existing piwheels database to the
latest version. The update scripts used attempt to preserve all data, and all
upgrades are performed in a single transaction so that, theoretically, if
anything goes wrong the database should be rolled back to its original state.
However, it is still strongly recommended that you back up your master database
before proceeding with any upgrade.

.. _PostgreSQL: https://postgresql.org/
