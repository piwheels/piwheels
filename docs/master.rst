==========
piw-master
==========

The piw-master script is intended to be run on the database and file-server
machine. It is recommended you *do not* run :doc:`piw-slave <slaves>` on the
same machine as the piw-master script. The database specified in the
configuration must exist and have been configured with the :doc:`piw-initdb
<initdb>` script. It is *strongly recommended* you run piw-master as an
ordinary unprivileged user, although obviously it will need write access to the
output directory.


Synopsis
========

.. code-block:: text

    piw-master [-h] [--version] [-c FILE] [-q] [-v] [-l FILE] [-d DSN]
                    [-o PATH] [--dev-mode] [--debug TASK] [--pypi-xmlrpc URL]
                    [--pypi-simple URL] [--pypi-json URL] [--status-queue ADDR]
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

    Specify a configuration file to load instead of the defaults at:

    * :file:`/etc/piwheels.conf`
    * :file:`/usr/local/etc/piwheels.conf`
    * :file:`~/.config/piwheels/piwheels.conf`

.. option:: -q, --quiet

    Produce less console output

.. option:: -v, --verbose

    Produce more console output

.. option:: -l FILE, --log-file FILE

    Log messages to the specified file

.. option:: -d DSN, --dsn DSN

    The connection string for the database to use; this database must be
    initialized with :doc:`initdb` and the user must *not* be a `PostgreSQL`_
    superuser (default: ``postgres:///piwheels``)

.. option:: -o PATH, --output-path PATH

    The path under which the website should be written; must be writable by the
    current user

.. option:: --dev-mode

    Run the master in development mode; this reduces some timeouts and tweaks
    some defaults

.. option:: --debug TASK

    Set logging to debug level for the named task; can be specified multiple
    times to debug many tasks

.. option:: --pypi-xmlrpc URL

    The URL of the PyPI XML-RPC service (default: ``https://pypi.org/pypi``)

.. option:: --pypi-simple URL

    The URL of the PyPI simple API (default: ``https://pypi.org/simple``)

.. option:: --pypi-json URL

    The URL of the PyPI JSON API (default: ``https://pypi.org/pypi``)

.. option:: --status-queue ADDR

    The address of the queue used to report status to monitors (default:
    ``ipc:///tmp/piw-status``); this is usually an ipc address

.. option:: --control-queue ADDR

    The address of the queue a monitor can use to control the master (default:
    ``ipc:///tmp/piw-control``); this is usually an ipc address

.. option:: --import-queue ADDR

    The address of the queue used by :doc:`piw-import <importer>`,
    :doc:`piw-add <add>`, :doc:`piw-remove <remove>`, and :doc:`piw-rebuild
    <rebuild>` (default: ``ipc:///tmp/piw-import``); this should always be an
    ipc address

.. option:: --log-queue ADDR

    The address of the queue used by :doc:`piw-logger <logger>` (default:
    ``ipc:///tmp/piw-logger``); this should always be an ipc address

.. option:: --slave-queue ADDR

    The address of the queue used to talk to :doc:`piw-slave <slaves>`
    (default: ``tcp://*:5555``); this is usually a tcp address

.. option:: --file-queue ADDR

    The address of the queue used to transfer files to :doc:`piw-slave
    <slaves>` (default: ``tcp://*:5556``); this is usually a tcp address

.. option:: --web-queue ADDR

    The address of the queue used to request web page updates (default:
    ``inproc://web``)

.. option:: --builds-queue ADDR

    The address of the queue used to store pending builds (default:
    ``inproc://builds``)

.. option:: --db-queue ADDR

    The address of the queue used to talk to the database server (default:
    ``inproc://db``)

.. option:: --fs-queue ADDR

    The address of the queue used to talk to the file-system server (default:
    ``inproc://fs``)

.. option:: --stats-queue ADDR

    The address of the queue used to send statistics to the collator task
    (default: ``inproc://stats``)


Deployment
==========

A typical deployment of the master service on a Raspbian server goes something
like this (each step assumes you start as root):

#. Install the pre-requisite software:

   .. code-block:: console

       # apt install postgresql apache2 python3-configargparse python3-zmq \
                     python3-voluptuous python3-cbor2 python3-requests \
                     python3-sqlalchemy python3-psycopg2 python3-chameleon \
                     python3-simplejson python3-urwid python3-geoip python3-pip
       # pip3 install "piwheels[monitor,master,logger]"

   If you wish to install directly from the git repository:

   .. code-block:: console

       # apt install git
       # pip3 install git+https://github.com/piwheels/piwheels#egg=piwheels[monitor,master,logger]

#. Set up the (unprivileged) piwheels user and the output directory:

   .. code-block:: console

       # groupadd piwheels
       # useradd -g piwheels -m piwheels
       # mkdir /var/www/piwheels
       # chown piwheels:piwheels /var/www/piwheels

#. Set up the configuration file:

   .. code-block:: ini
       :caption: /etc/piwheels.conf

       [master]
       dsn=postgresql:///piwheels
       output-path=/var/www/piwheels

#. Set up the database:

   .. code-block:: console

       # su - postgres
       $ createuser piwheels
       $ createdb -O postgres piwheels
       $ piw-initdb

#. Set up the web server:

   * Point the document root to the output path (:file:`/var/www/piwheels`
     above, but it can be anywhere your piwheels user has write access to;
     naturally you want to make sure your web-server's user only has *read*
     access to the location).

   * Set up SSL for the web server (e.g. with `Let's Encrypt`_; the
     `dehydrated`_ utility is handy for getting and maintaining the SSL
     certificates). This part isn't optional; you won't get ``pip`` installing
     things from an unencrypted source without a lot of pain.

   * See below for an example Apache configuration

#. Start the master running (it'll take quite a while to populate the list of
   packages and versions from PyPI on the initial run so get this going before
   you start bringing up build slaves):

   .. code-block:: console

       # su - piwheels
       $ piw-master -v

#. Deploy some build slaves; see :doc:`slaves` for deployment instructions.


Example httpd configuration
===========================

The following is an example Apache configuration similar to that used on the
production piwheels master. The port 80 (http) server configuration should look
something like this:

.. code-block:: apache
    :caption: /etc/apache2/sites-available/000-default.conf

    <VirtualHost *:80>
        ServerName www.example.org
        ServerAlias example.org
        RedirectMatch 302 ^(.*) https://www.example.org$1
    </VirtualHost>

.. note::

    Obviously, you will want to replace all instances of "example.org" with
    your own server's domain.

On the port 443 (https) side of things, you want the "full" configuration which
should look something like this, assuming your output path is
:file:`/var/www/piwheels`:

.. code-block:: apache
    :caption: /etc/apache2/sites-available/default-ssl.conf

    <IfModule mod_ssl.c>
        <VirtualHost _default_:443>
            ServerName www.example.org
            ServerAlias example.org
            ServerAdmin webmaster@example.org
            DocumentRoot /var/www/piwheels

            ErrorLog ${APACHE_LOG_DIR}/ssl_error.log
            CustomLog ${APACHE_LOG_DIR}/ssl_access.log combined
            # Send Apache log records to piw-logger for transfer to piw-master
            CustomLog "|/usr/local/bin/piw-logger --drop" combined

            SSLEngine On
            SSLCertificateFile /var/lib/dehydrated/certs/example.org/fullchain.pem
            SSLCertificateKeyFile /var/lib/dehydrated/certs/example.org/privkey.pem

            <Directory /var/www/piwheels>
                Options -Indexes +FollowSymlinks
                AllowOverride None
                Require all granted
                <IfModule mod_rewrite.c>
                    RewriteEngine On
                    RewriteRule ^project/?$ /packages.html [L,R=301]
                    RewriteRule ^p/(.*)/?$ /project/$1 [L,R=301]
                </IfModule>
                <IfModule mod_headers.c>
                    Header set Access-Control-Allow-Origin "*"
                </IfModule>
                ErrorDocument 404 /404.html
                DirectoryIndex index.html
            </Directory>

            <Directory /var/www/piwheels/logs/>
                Options +MultiViews
                MultiviewsMatch Any
                RemoveType .gz
                AddEncoding gzip .gz
                <IfModule mod_filter.c>
                    FilterDeclare gzip CONTENT_SET
                    FilterProvider gzip INFLATE "! req('Accept-Encoding') =~ /gzip/"
                    FilterChain gzip
                </IfModule>
            </Directory>
        </VirtualHost>
    </IfModule>

Several important things to note:

* A `CustomLog`_ line pipes log entries to the :doc:`logger` script which
  buffers entries and passes them to piw-master for insertion into the database
  (which in turn is used to generate statistics for the homepage and the
  project pages)

* Only ``index.html`` is allowed as a directory index, no directory listings
  are generated (they can be enormous, and remember the master is expected to
  be deployable on a Raspberry Pi)

* There's a couple of `mod_rewrite`_ redirections to deal with legacy path
  redirections, and providing a more friendly root for the :file:`/project/`
  path

* The build logs are stored in pre-compressed gzip archives, and the server is
  configured to serve them verbatim to clients which provide an
  `Accept-Encoding: gzip`_ header. For clients which do not (e.g.
  :manpage:`curl(1)`), the server unpacks the log transparently

* An example configuration for the SSL certificate locations is given which
  assumes `dehydrated`_ is being used to maintain them


Example database configuration
==============================

The following sections detail various setups for the database server. The
simplest is the first, the combined configuration in which the machine hosting
the master service also hosts the database.

The later sections detail separating the master and database hosts, and assume
your master server is accessible at the IPv6 address ``1234:abcd::1`` and
your database server is at the IPv6 address ``1234:abcd::2``. Replace
addresses accordingly.


Combined configuration
----------------------

This is effectively covered in the prior deployment section. The default DSN of
``dsn=postgresql:///piwheels`` can either be implied by default, or explicitly
specified in :file:`/etc/piwheels.conf`.

The only thing to be aware of, particularly if you are deploying on a Pi, is
that the calculation of the build queue is quite a big query. Assuming you are
targeting all packages on PyPI (as the production piwheels instance does), you
should never consider running the combined database+master on a machine (or VM)
with less than 4 cores and 4GB of RAM, preferably more. If deploying a combined
master+database on a Pi, use a Pi 4 with 8GB of RAM.


Separate configuration
----------------------

If you wish to deploy your PostgreSQL database on a separate server, you will
first need to ensure that server can accept remote connections from the master
server. A simple (but less secure) means of configuring this is to simply
"trust" that connections from the master's IP address to the piwheels
database by the piwheels user. This can be accomplished by adding the last line
below to :file:`pg_hba.conf`:

.. code-block:: text
    :caption: /etc/postgresql/**ver**/main/pg_hba.conf
    :emphasize-lines: 17

    # Database administrative login by Unix domain socket
    local   all             postgres                                peer

    # TYPE  DATABASE        USER            ADDRESS                 METHOD

    # "local" is for Unix domain socket connections only
    local   all             all                                     peer
    # IPv4 local connections:
    host    all             all             127.0.0.1/32            md5
    # IPv6 local connections:
    host    all             all             ::1/128                 md5
    # Allow replication connections from localhost, by a user with the
    # replication privilege.
    local   replication     all                                     peer
    host    replication     all             127.0.0.1/32            md5
    host    replication     all             ::1/128                 md5
    host    piwheels        piwheels        1234:abcd::1/128        trust

Then restarting the PostgreSQL server:

.. code-block:: console

    # systemctl restart postgresql

Then, on the master, use the following DSN in :file:`/etc/piwheels.conf`:

.. code-block:: ini
    :caption: /etc/piwheels.conf

    [master]
    dsn=postgresql://piwheels@[1234:abcd::2]/piwheels

.. warning::

    *Never* provide remote access to the PostgreSQL superuser, ``postgres``.
    Install the piwheels package directly on the database server and run the
    :doc:`initdb` script locally. This will also require creating a
    :file:`/etc/piwheels.conf` on the database server, that uses a typical
    "local" DSN like ``dsn=postgresql:///piwheels``.


SSH tunnelling
--------------

A more secure (but rather more complex) option is to create a persistent SSH
tunnel from the master to the database server which forwards the UNIX socket
for the database back to the master as the unprivileged ``piwheels`` user.

Firstly, on the master, generate an SSH key-pair for the ``piwheels`` user and
copy the public key to the database server.

.. code-block:: console

    # su - piwheels
    $ ssh-keygen
    Generating public/private rsa key pair.
    Enter file in which to save the key (/home/piwheels/.ssh/id_rsa):
    Created directory '/home/piwheels/.ssh'.
    Enter passphrase (empty for no passphrase):
    Enter same passphrase again:
    Your identification has been saved in /home/piwheels/.ssh/id_rsa
    Your public key has been saved in /home/piwheels/.ssh/id_rsa.pub
    ...
    $ ssh-copy-id piwheels@1234:abcd::2

.. note::

    This assumes that you *temporarily* permit password-based login for the
    piwheels user on the database server.

Secondly, set up a :manpage:`systemd(1)` service to maintain the tunnel:

.. literalinclude:: ../piwheelsdb-tunnel.service
    :language: ini
    :caption: /etc/systemd/system/piwheelsdb-tunnel.service

.. code-block:: console

    # systemctl daemon-reload
    # systemctl enable piwheelsdb-tunnel.service
    # systemctl start piwheelsdb-tunnel.service

At this point, you should be able to switch back to the piwheels user and
connect to the piwheels database (however, note that as the tunnel is owned by
the unprivileged piwheels user, only it can access the database remotely):

.. code-block:: console

    # su - piwheels
    $ psql piwheels
    psql (13.5 (Debian 13.5-0+deb11u1))
    Type "help" for help.

    piwheels=>

.. note::

    This method requires *no* alteration of :file:`pg_hba.conf` on the database
    server; the default should be sufficient. As far as the database server is
    concerned the local piwheels user is simply accessing the database via the
    local UNIX socket.


Automatic start
===============

If you wish to ensure that the master starts on every boot-up, you may wish to
define a systemd unit for it:

.. literalinclude:: ../piwheels-master.service
    :language: ini
    :caption: /etc/systemd/system/piwheels-master.service

.. code-block:: console

    # systemctl daemon-reload
    # systemctl enable piwheels-master
    # systemctl start piwheels-master


Upgrades
========

The master will check that build slaves have the same version number and will
reject them if they do not. Furthermore, it will check the version number in
the database's *configuration* table matches its own and fail if it does not.
Re-run the :doc:`piw-initdb <initdb>` script as the PostgreSQL super-user to
upgrade the database between versions (downgrades are not supported, so take a
backup first!).

.. _PostgreSQL: https://postgresql.org/
.. _Let's Encrypt: https://letsencrypt.org/
.. _dehydrated: https://github.com/lukas2511/dehydrated
.. _CustomLog: https://httpd.apache.org/docs/2.4/mod/mod_log_config.html#customlog
.. _mod_rewrite: https://httpd.apache.org/docs/2.4/mod/mod_rewrite.html
.. _Accept-Encoding\: gzip: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Accept-Encoding
