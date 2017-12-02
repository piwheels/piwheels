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

::

    piw-master [-h] [--version] [-c FILE] [-q] [-v] [-l FILE] [-d DSN]
               [--pypi-xmlrpc URL] [--pypi-simple URL] [-o PATH]
               [--index-queue ADDR] [--status-queue ADDR]
               [--control-queue ADDR] [--builds-queue ADDR]
               [--db-queue ADDR] [--fs-queue ADDR] [--slave-queue ADDR]
               [--file-queue ADDR]


Description
===========

.. program:: piw-master

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

    The database to use; this database must be configured with piw-initdb and
    the user should *not* be a PostgreSQL superuser (default:
    postgres:///piwheels)

.. option:: --pypi-xmlrpc URL

    The URL of the PyPI XML-RPC service (default: https://pypi.python.org/pypi)

.. option:: --pypi-simple URL

    The URL of the PyPI simple API (default: https://pypi.python.org/simple)

.. option:: -o PATH, --output-path PATH

    The path under which the website should be written; must be writable by the
    current user

.. option:: --index-queue ADDR

    The address of the IndexScribe queue (default: inproc://indexes)

.. option:: --status-queue ADDR

    The address of the queue used to report status to monitors (default:
    ipc:///tmp/piw-status)

.. option:: --control-queue ADDR

    The address of the queue a monitor can use to control the master (default:
    ipc:///tmp/piw-control)

.. option:: --builds-queue ADDR

    The address of the queue used to store pending builds (default:
    inproc://builds)

.. option:: --db-queue ADDR

    The address of the queue used to talk to the database server (default:
    inproc://db)

.. option:: --fs-queue ADDR

    The address of the queue used to talk to the file- system server (default:
    inproc://fs)

.. option:: --slave-queue ADDR

    The address of the queue used to talk to the build slaves (default:
    tcp://\*:5555)

.. option:: --file-queue ADDR

    The address of the queue used to transfer files from slaves (default:
    tcp://\*:5556)


Development
===========

Although the piwheels master appears to be a monolithic script, it's actually
composed of numerous (often extremely simple) tasks. Each task runs its own
thread and all communication between tasks takes place over `ZeroMQ`_ sockets.
This is also how communication occurs between the master and the :doc:`slaves`,
and the :doc:`monitor`.

The following diagram roughly illustrates all the tasks in the system
(including those of the build slaves and the monitor), along with details of
the type of ZeroMQ socket used to communicate between them:

.. image:: master_arch.*
    :align: center

It may be confusing that the file server and database server appear to be
separate to the master in the diagram. This is deliberate as the system's
architecture is such that certain tasks can be easily broken off into entirely
separate processes (potentially on separate machines), if required in future
(either for performance or security reasons).


Tasks
=====

The following sections document the tasks shown above (listed from the "front"
at PyPI to the "back" at Users):


.. _cloud-gazer:

Cloud Gazer
-----------

Implemented in: :class:`piwheels.master.cloud_gazer.CloudGazer`.

This task is the "front" of the system. It follows PyPI's event log for new
package and version registrations, and writes those entries to the database.
It does this via :ref:`the-oracle`.


.. _the-oracle:

The Oracle
----------

Implemented in: :class:`piwheels.master.the_oracle.TheOracle`.

This task is the main interface to the database. It accepts requests from other
tasks ("register this new package", "log this build", "what files were built
with this package", etc.) and executes them against the database. Because
database requests are extremely variable in their execution time, there are
actually several instances of the oracle which sit behind :ref:`seraph`.


.. _seraph:

Seraph
------

Implemented in: :class:`piwheels.master.seraph.Seraph`.

Seraph is a simple load-balancer for the various instances of
:ref:`the-oracle`. This is the task that *actually* accepts database requests.
It finds a free oracle and passes the request along, passing back the reply
when it's finished.


.. _the-architect:

The Architect
-------------

Implemented in: :class:`piwheels.master.the_architect.TheArchitect`.

This task is the final database related task in the master script. Unlike
:ref:`the-oracle` it simply queries the database for the packages that need
building.  Whenever :ref:`slave-driver` needs a task to hand to a build slave,
it asks the Architect for one matching the build slave's ABI.


.. _slave-driver:

Slave Driver
------------

Implemented in: :class:`piwheels.master.slave_driver.SlaveDriver`.

This task is the main coordinator of the build slave's activities. When a build
slave first comes online it introduces itself to this task (with information
including the ABI it can build for), and asks for a package to build. As
described above, this task asks :ref:`the-architect` for the next package
matching the build slave's ABI and passes this back.

Eventually the build slave will communicate whether or not the build succeeded,
along with information about the build (log output, files generated, etc.).
This task writes this information to the database via :ref:`the-oracle`. If the
build was successful, it informs the :ref:`file-juggler` that it should expect
a file transfer from the relevant build slave.

Finally, when all files from the build have been transferred, the Slave Driver
informs the :ref:`index-scribe` that the package's index will need (re)writing.


.. _mr-chase:

Mr. Chase
---------

Implemented in: :class:`piwheels.master.mr_chase.MrChase`.

This task talks to :program:`piw-import` and handles importing builds manually
into the system. It is essentially a cut-down version of the
:ref:`slave-driver` with a correspondingly simpler protocol.

This task writes information to the database via :ref:`the-oracle`. If the
imported build was successful, it informs the :ref:`file-juggler` that it
should expect a file transfer from the importer.

Finally, when all files from the build have been transferred, it informs the
:ref:`index-scribe` that the package's index will need (re)writing.


.. _file-juggler:

File Juggler
------------

Implemented in: :class:`piwheels.master.file_juggler.FileJuggler`.

This task handles file transfers from the build slaves to the master. Files are
transferred in multiple (relatively small) chunks and are verified with the
hash reported by the build slave (retrieved from the database via
:ref:`the-oracle`).


.. _big-brother:

Big Brother
-----------

Implemented in: :class:`piwheels.master.big_brother.BigBrother`.

This task is a bit of a miscellaneous one. It sits around periodically
generating statistics about the system as a whole (number of files, number of
packages, number of successful builds, number of builds in the last hour, free
disk space, etc.) and sends these off to the :ref:`index-scribe`.


.. _index-scribe:

Index Scribe
------------

Implemented in: :class:`piwheels.master.index_scribe.IndexScribe`.

This task generates the web output for piwheels. It generates the home-page
with statistics from :ref:`big-brother`, the overall package index, and
individual package file lists with messages from :ref:`slave-driver`.


Queues
======

It should be noted that the diagram omits several queues for the sake of
brevity. For instance, there is a simple PUSH/PULL control queue between the
master's "main" task and each sub-task which is used to relay control messages
like ``PAUSE``, ``RESUME``, and ``QUIT``.

Most of the protocols used by the queues are (currently) undocumented with the
exception of those between the build slaves and the :ref:`slave-driver` and
:ref:`file-juggler` tasks (documented in the :doc:`slaves` chapter).

However, all protocols share a common basis: messages are lists of Python
objects. The first element is always string containing the action. Further
elements are parameters specific to the action. Messages are encoded with
:mod:`pickle`. This is an untrusted format but was the quickest to get started
with (and the inter-process queues aren't exposed to the internet). A future
version may switch to something slightly safer like `JSON`_ or better still
`CBOR`_.


.. _ZeroMQ: https://zeromq.org/
.. _JSON: https://www.json.org/
.. _CBOR: https://cbor.io/
