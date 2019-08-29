==========
piw-master
==========

The piw-master script is intended to be run on the database and file-server
machine. It is recommended you do not run piw-slave on the same machine as the
piw-master script. The database specified in the configuration must exist and
have been configured with the piw-initdb script. It is recommended you run
piw-master as an ordinary unprivileged user, although obviously it will need
write access to the output directory.


Synopsis
========

.. code-block:: text

    piw-master [-h] [--version] [-c FILE] [-q] [-v] [-l FILE] [-d DSN]
                    [-o PATH] [--dev-mode] [--pypi-xmlrpc URL]
                    [--pypi-simple URL] [--status-queue ADDR]
                    [--control-queue ADDR] [--import-queue ADDR]
                    [--log-queue ADDR] [--slave-queue ADDR] [--file-queue ADDR]
                    [--web-queue ADDR] [--builds-queue ADDR] [--db-queue ADDR]
                    [--fs-queue ADDR] [--stats-queue ADDR]


Description
===========

.. program:: piw-master

.. option:: -h, --help

    Show this help message and exit

.. option:: --version

    Show program's version number and exit

.. option:: -c FILE, --configuration FILE

    Specify a configuration file to load

.. option:: -q, --quiet

    Produce less console output

.. option:: -v, --verbose

    Produce more console output

.. option:: -l FILE, --log-file FILE

    Log messages to the specified file

.. option:: -d DSN, --dsn DSN

    The database to use; this database must be configured with piw-initdb and
    the user must *not* be a `PostgreSQL`_ superuser (default:
    postgres:///piwheels)

.. option:: -o PATH, --output-path PATH

    The path under which the website should be written; must be writable by the
    current user

.. option:: --dev-mode

    Run the master in development mode, which reduces some timeouts and tweaks
    some defaults

.. option:: --pypi-xmlrpc URL

    The URL of the PyPI XML-RPC service (default: https://pypi.python.org/pypi)

.. option:: --pypi-simple URL

    The URL of the PyPI simple API (default: https://pypi.python.org/simple)

.. option:: --status-queue ADDR

    The address of the queue used to report status to monitors (default:
    ipc:///tmp/piw-status); this is usually an ipc address

.. option:: --control-queue ADDR

    The address of the queue a monitor can use to control the master (default:
    ipc:///tmp/piw-control); this is usually an ipc address

.. option:: --import-queue ADDR

    The address of the queue used by :doc:`importer` (default:
    ipc:///tmp/piw-import); this should always be an ipc address

.. option:: --log-queue ADDR

    The address of the queue used by :doc:`logger` (default:
    ipc:///tmp/piw-logger); this should always be an ipc address

.. option:: --slave-queue ADDR

    The address of the queue used to talk to the build slaves (default:
    tcp://\*:5555); this is usually a tcp address

.. option:: --file-queue ADDR

    The address of the queue used to transfer files from slaves (default:
    tcp://\*:5556); this is usually a tcp address

.. option:: --builds-queue ADDR

    The address of the queue used to store pending builds (default:
    inproc://builds)

.. option:: --db-queue ADDR

    The address of the queue used to talk to the database server (default:
    inproc://db)

.. option:: --fs-queue ADDR

    The address of the queue used to talk to the file- system server (default:
    inproc://fs)

.. option:: --stats-queue ADDR

    The address of the queue used to send statistics to the collator task
    (default: inproc://stats)


Deployment
==========

A typical deployment of the master service on a Raspbian server goes something
like this (each step assumes you start as root):

1. Install the pre-requisite software:

   .. code-block:: console

       # apt install postgresql-9.6 apache2 python3-psycopg2 python3-geoip
       # apt install python3-sqlalchemy python3-urwid python3-zmq python3-voluptuous python3-chameleon
       # pip install piwheels[monitor,master,logger]

2. Set up the (unprivileged) piwheels user and the output directory:

   .. code-block:: console

       # groupadd piwheels
       # useradd -g piwheels -m piwheels
       # mkdir /var/www/piwheels
       # chown piwheels:piwheels /var/www/piwheels

3. Set up the database:

   .. code-block:: console

       # su - postgres
       $ createuser piwheels
       $ createdb -O postgres piwheels
       $ piw-initdb

4. Set up the web server:

   * Point the document root to the output path (:file:`/var/www/piwheels`
     above, but it can be anywhere your piwheels user has write access to;
     naturally you want to make sure your web-server's user only has *read*
     access to the location).
   * Set up SSL for the web server (e.g. with `Let's Encrypt`_; the
     `dehydrated`_ utility is handy for getting and maintaining the SSL
     certificates).

5. Start the master running (it'll take quite a while to populate the list of
   packages and versions from PyPI on the initial run so get this going before
   you start bringing up build slaves):

   .. code-block:: console

       # su - piwheels
       $ piw-master -v

6. Deploy some build slaves; see :doc:`slaves` for deployment instructions.


Automatic start
===============

If you wish to ensure that the master starts on every boot-up, you may wish to
define a systemd unit for it. Example units can be also be found in the root of
the piwheels repository:

.. code-block:: console

    # wget https://raw.githubusercontent.com/piwheels/piwheels/master/piwheels-master.service
    # cp piwheels-master.service /etc/systemd/system/
    # systemctl daemon-reload
    # systemctl enable piwheels-master
    # systemctl start piwheels-master


Upgrades
========

The master will check that build slaves have the same version number and will
reject them if they do not. Furthermore, it will check the version number in
the database's *configuration* table matches its own and fail if it does not.
Re-run the :doc:`initdb` script as the PostgreSQL super-user to upgrade the
database between versions (downgrades are not supported, so take a backup
first!).

.. _PostgreSQL: https://postgresql.org/
.. _Let's Encrypt: https://letsencrypt.org/
.. _dehydrated: https://github.com/lukas2511/dehydrated
