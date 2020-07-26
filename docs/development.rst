===========
Development
===========

The main GitHub repository for the project can be found at:

    https://github.com/piwheels/piwheels

After cloning, we recommend you set up a virtualenv for development and then
execute ``make develop`` within that virtualenv. This should install all
requirements for executing all tools, building the documentation and executing
the test suite.


Testing
=======

Executing the test suite requires that you have a local `PostgreSQL`_
installation configured with an unprivileged user, a privileged super user,
and a test database.

The test suite uses environment variables to discover the name of the test
database, and the aforementioned users. See the top of
:file:`tests/conftest.py` for more details. A typical execution of the test
suite might look as follows:

.. code-block:: console

    $ export PIWHEELS_TESTDB=piwtest
    $ export PIWHEELS_USER=piwheels
    $ export PIWHEELS_PASS=piwheels
    $ export PIWHEELS_SUPERUSER=piwsuper
    $ export PIWHEELS_SUPERPASS=foobar
    $ cd piwheels
    $ make test

You may wish to construct a script for exporting the environment variables, or
add these values to your :file:`~/.bashrc`.

.. note::

    If you are not using your local PostgreSQL installation for anything else
    you may wish to set ``fsync=off`` and ``synchronous_commit=off`` in your
    local :file:`postgresql.conf` to speed up execution of the test suite. Do
    *NOT* do this on any production PostgreSQL server!


Design
======

Although the piwheels master appears to be a monolithic script, it's actually
composed of numerous (often extremely simple) tasks. Each task runs its own
thread and all communication between tasks takes place over `ZeroMQ`_ sockets.
This is also how communication occurs between the master and the :doc:`slaves`,
and the :doc:`monitor`.

The following diagram roughly illustrates all the tasks in the system
(including those of the build slaves and the monitor), along with details of
the type of ZeroMQ socket used to communicate between them:

.. image:: images/master_arch.*
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
:ref:`the-oracle` it periodically queries the database for the packages that
need building and passes this information along to the :ref:`slave-driver`.


.. _slave-driver:

Slave Driver
------------

Implemented in: :class:`piwheels.master.slave_driver.SlaveDriver`.

This task is the main coordinator of the build slaves' activities. When a build
slave first comes online it introduces itself to this task (with information
including the ABI it can build for), and asks for a package to build. If there
is a pending package matching the build slave's ABI, it will be told to build
that package.

Periodically, :ref:`the-architect` refreshes this task's list of packages that
require building.

Eventually the build slave will communicate whether or not the build succeeded,
along with information about the build (log output, files generated, etc.).
This task writes this information to the database via :ref:`the-oracle`. If the
build was successful, it informs the :ref:`file-juggler` that it should expect
a file transfer from the relevant build slave.

Finally, when all files from the build have been transferred, the Slave Driver
informs the :ref:`the-scribe` that the package's index and project page will
need (re)writing. It also periodically informs :ref:`big-brother` of the size
of the build queue.


.. _mr-chase:

Mr. Chase
---------

Implemented in: :class:`piwheels.master.mr_chase.MrChase`.

This task talks to :program:`piw-import` and handles importing builds manually
into the system. It is essentially a cut-down version of the
:ref:`slave-driver` with a correspondingly simpler protocol. It is also the
end-point for :program:`piw-rebuild` and :program:`piw-remove`.

This task writes information to the database via :ref:`the-oracle`. If the
imported build was successful, it informs the :ref:`file-juggler` that it
should expect a file transfer from the importer.

Finally, when all files from the build have been transferred, it informs the
:ref:`the-scribe` that the package's index and project pages will need
(re)writing.


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
disk space, etc.) and sends these off to the :ref:`the-scribe`.


.. _the-scribe:

The Scribe
----------

Implemented in: :class:`piwheels.master.the_scribe.TheScribe`.

This task generates the web output for piwheels. It generates the home-page
with statistics from :ref:`big-brother`, the overall package index, individual
package file lists, and project pages with messages from :ref:`slave-driver`.


.. _the-secretary:

The Secretary
-------------

Implemented in :class:`piwheels.master.the_secretary.TheSecretary`.

This task sits in front of :ref:`the-scribe` and attempts to mitigate many of
the repeated requests that typically get sent to it. For example, project pages
(which are relatively expensive to generate, in database terms), may need
regenerating every time a file is registered against a package version.

This often happens in a burst when a new package version is released, resulting
in several (redundant) requests to re-write the same page with minimally
changed information. The secretary buffers up such requests, eliminating
duplicates before finally passing them to :ref:`the-scribe` for processing.


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
`CBOR`_.


Protocols
=========

The following sections document the protocols used between the build slaves and
the three sub-tasks that they talk to in the :doc:`master`. Each protocol
operates over a separate queue. All messages in the piwheels system follow a
similar structure of being a tuple containing:

* A short unicode string indicating what sort of message it is.

* Data. The structure of the data is linked to the type of the message, and
  validated on both transmission and reception (see :mod:`piwheels.protocols`
  for more information).

For example the message telling a build slave what package and version to build
looks like this in Python syntax::

    ['BUILD', 'numpy', '1.14.0']

If a message is not associated with any data whatsoever, it is transmitted as a
simple unicode string (without the list encapsulation). The serialization
format for all messages in the system is currently `CBOR`_.


Slave Driver
------------

The queue that talks to :ref:`slave-driver` is a ZeroMQ REQ socket, hence the
protocol follows a strict request-reply sequence which is illustrated below:

.. image:: images/slave_protocol.*
    :align: center

1. The new build slave sends "HELLO" with data ``[build_timeout,
   master_timeout, py_version_tag, abi_tag, platform_tag, label, os_name,
   os_version, board_revision, board_serial]`` where:

   * *build_timeout* is the slave's configured timeout (the length of time
     after which it will assume a build has failed and attempt to terminate it)
     as a :class:`~datetime.timedelta`.

   * *master_timeout* is the maximum length of time the slave will wait for
     communication from the master. After this timeout it will assume the
     connection has failed, terminate and clean-up any on-going build, then
     attempt to restart the connection to the master.

   * *py_version_tag* is the python version the slave will build for (e.g.
     "27", "35", etc.)

   * *abi_tag* is the ABI the slave will build for (e.g. "cp35m")

   * *platform_tag* is the platform of the slave (e.g. "linux_armv7l")

   * *label* is an identifying label for the slave (e.g. "slave2"); note that
     this label doesn't have to be anything specific, it's purely a convenience
     for administrators displayed in the monitor. In the current implementation
     this is the unqualified hostname of the slave

   * *os_name* is a string identifying the operating system, e.g. "Raspbian
     GNU/Linux".

   * *os_version* is a string identifying the release of the operating system,
     e.g. "10 (buster)".

   * *board_revision* is a code indicating the revision of the board that the
     slave is running upon, e.g. "c03111" for a Raspberry Pi 4B.

   * *board_serial* is the serial number of the board that the slave is running
     upon.

2. The master replies sends "ACK" with data ``[slave_id, pypi_url]`` where
   *slave_id* is an integer identifier for the slave. Strictly speaking, the
   build slave doesn't need this identifier but it can be helpful for admins or
   developers to see the same identifier in logs on the master and the slave
   which is the only reason it is communicated.

   The *pypi_url* is the URL the slave should use to fetch packages from PyPI.

3. The build slave sends "IDLE" to indicate that it is ready to accept a
   build job. The "IDLE" message is accompanied with the data ``[now,
   disk_total, disk_free, mem_total, mem_free, load_avg, cpu_temp]`` where:

   * *now* is a :class:`~datetime.datetime` indicating the current time on the
     build slave.

   * *disk_total* is the total size (in bytes) of the file-system used to build
     wheels.

   * *disk_free* is the number of bytes free in the file-system used to build
     wheels.

   * *mem_total* is the total size (in bytes) of the RAM on the build slave.

   * *mem_free* is the number of bytes of RAM currently available (not
     necessarily unused, but potentially useable by builds).

   * *load_avg* is the one minute load average.

   * *cpu_temp* is the temperature, in degrees celsius of the CPU.

4. The master can reply with "SLEEP" which indicates that no jobs are
   currently available for that slave (e.g. the master is paused, or the build
   queue is empty, or there are no builds for the slave's particular ABI at
   this time). In this case the build slave should pause a while (the current
   implementation waits 10 seconds) before retrying "IDLE".

5. The master can also reply with "DIE" which indicates the build slave should
   shutdown. In this case, after cleaning up any resources the build slave
   should send back "BYE" and terminate (generally speaking, whenever the slave
   terminates it should send "BYE" no matter where in the protocol it occurs;
   the master will take this as a sign of termination).

6. The master can also reply "BUILD" with data ``[package, version]`` where
   *package* is the name of a package to build and *version* is the version to
   build. At this point, the build slave should attempt to locate the package
   on PyPI and build a wheel from it.

7. While the build is underway, the slave must periodically ping the master
   with the "BUSY" message, which is accompanied by the exact same stats as in
   the "IDLE" message.

8. If the master wishes the build slave to continue with the build it will
   reply with "CONT". If the master wants to build slave to terminate the build
   early it will reply with "DONE" (goto step 13).

9. Assuming the master doesn't request termination of the build, eventually it
   will finish. In response to the next "CONT" message, the slave sends "BUILT"
   with data ``[status, duration, output, files]``:

   * *status* is ``True`` if the build succeeded and ``False`` otherwise.

   * *duration* is a :class:`~datetime.timedelta` value indicating the length
     of time it took to build in seconds.

   * *output* is a string containing the complete build log.

   * *files* is a :class:`list` of file state tuples containing the following
     fields in the specified order:

     - *filename* is the filename of the wheel.

     - *filesize* is the size in bytes of the wheel.

     - *filehash* is the SHA256 hash of the wheel contents.

     - *package_tag* is the package tag extracted from the filename.

     - *package_version_tag* is the version tag extracted from the filename.

     - *py_version_tag* is the python version tag extracted from the
       filename.

     - *abi_tag* is the ABI tag extracted from the filename (sanitized).

     - *platform_tag* is the platform tag extracted from the filename.

     - *dependencies* is a :class:`set` of dependency tuples containing the
       following fields in the specified order:

       + *tool* is the name of the tool used to install the dependency

       + *package* is the name of the package to install with the tool

10. If the build succeeded, the master will send "SEND" with data ``filename``
    where *filename* is one of the names transmitted in the prior "BUILT"
    message.

11. At this point the slave should use the :ref:`file-juggler-protocol`
    protocol documented below to transmit the contents of the specified file to
    the master. When the file transfer is complete, the build slave sends
    "SENT" to the master.

12. If the file transfer fails to verify, or if there are more files to send
    the master will repeat the "SEND" message. Otherwise, if all transfers have
    completed and have been verified, the master replies with "DONE".

13. The build slave is now free to destroy all resources associated with the
    build, and returns to step 3 ("IDLE").

If at any point, the master takes longer than *master_timeout* (default: 5
minutes) to respond to a slave's request, the slave will assume the master has
disappeared. If a build is still active, it will be cleaned up and terminated,
the connection to the master will be closed, the slave's ID will be reset and
the slave must restart the protocol from the top ("HELLO").

This permits the master to be upgraded or replaced without having to shutdown
and restart the slaves manually. It is possible that the master is restarted
too fast for the slave to notice. In this case the slave's next message will be
mis-interpreted by the master as an invalid initial message, and it will be
ignored. However, this is acceptable behaviour as the re-connection protocol
described above will then effectively restart the slave after the
*master_timeout* has elapsed.


Mr Chase (importing)
--------------------

The queue that talks to :ref:`mr-chase` is a ZeroMQ REQ socket, hence the
protocol follows a strict request-reply sequence which is illustrated below
(see below for documentation of the "REMOVE" path):

.. image:: images/import_protocol.*
    :align: center

1. The importer sends "IMPORT" with data ``[slave_id, package, version,
   abi_tag, status, duration, output, files]``:

   * *slave_id* is the integer id of the build slave that created the wheel.
     This is usually 0 and is ignored by the master anyway.

   * *package* is the name of the package that the build is for.

   * *version* is the version of the package that the build is for.

   * *abi_tag* is either ``None``, indicating that the master should use the
     "default" (minimum) build ABI registered in the system, or is a string
     indicating the ABI that the build was attempted for.

   * *status* is ``True`` if the build succeeded and ``False`` otherwise.

   * *duration* is a :class:`float` value indicating the length of time it took
     to build in seconds.

   * *output* is a string containing the complete build log.

   * *files* is a list of file state tuples containing the following fields
     in the specified order:

     - *filename* is the filename of the wheel.

     - *filesize* is the size in bytes of the wheel.

     - *filehash* is the SHA256 hash of the wheel contents.

     - *package_tag* is the package tag extracted from the filename.

     - *package_version_tag* is the version tag extracted from the filename.

     - *py_version_tag* is the python version tag extracted from the
       filename.

     - *abi_tag* is the ABI tag extracted from the filename (sanitized).

     - *platform_tag* is the platform tag extracted from the filename.

     - *dependencies* is a :class:`set` of dependency tuples containing the
       following fields in the specified order:

       + *tool* is the name of the tool used to install the dependency

       + *package* is the name of the package to install with the tool

2. If the import information is insufficient or incorrect, the master will send
   "ERROR" with data ``message`` which is the description of the error that
   occurred.

3. If the import information is okay, the master will send "SEND" with data
   ``filename`` for each file mentioned in the build.

4. At this point the importer should use the :ref:`file-juggler-protocol`
   protocol to transmit the contents of the specified file to the master. When
   the file transfer is complete, the importer sends "SENT" to the
   master.

5. If the file transfer fails to verify, or if there are more files to send the
   master will repeat the "SEND" message. Otherwise, if all transfers have
   completed and have been verified, the master replies with "DONE".

6. The importer is now free to remove all files associated with the build, if
   requested to.


Mr Chase (removing)
-------------------

The queue that talks to :ref:`mr-chase` is a ZeroMQ REQ socket, hence the
protocol follows a strict request-reply sequence which is illustrated below
(see above for documentation of the ``IMPORT`` path):

.. image:: images/import_protocol.*
    :align: center

1. The utility sends "REMOVE" with data ``[package, version, skip]``:

   * *package* is the name of the package to remove.

   * *version* is the version of the package to remove.

   * *skip* is a string containing the reason the version should never be
     built again, or is a blank string indicating the version should be
     rebuilt.

2. If the removal fails (e.g. if the package or version does not exist), the
   master will send "ERROR" with data ``message`` (a string describing the
   error that occurred).

3. If the removal is successful, the master replies with "DONE".


Mr Chase (rebuilding)
---------------------

The queue that talks to :ref:`mr-chase` is a ZeroMQ REQ socket, hence the
protocol follows a strict request-reply sequence which is illustrated below
(see above for documentation of the ``IMPORT`` path):

.. image:: images/import_protocol.*
    :align: center

1. The utility sends "REBUILD" with data ``[part, package]``:

   * *part* is the part of the website to rebuild. It must be one of "HOME",
     "SEARCH", "PROJECT" or "BOTH".

   * *package* is the name of the package to rebuild indexes and/or project
     pages for or ``None`` if pages for all packages should be rebuilt. This
     parameter is omitted if *part* is "HOME" or "SEARCH".

2. If the rebuild request fails (e.g. if the package does not exist), the
   master will send "ERROR" with data ``message`` (a string describing the
   error that occurred).

3. If the rebuild request is successful, the master replies with "DONE".


.. _file-juggler-protocol:

File Juggler
------------

The queue that talks to :ref:`file-juggler` is a ZeroMQ DEALER socket. This is
because the protocol is semi-asynchronous (for performance reasons). For the
sake of illustration, a synchronous version of the protocol is illustrated
below:

.. image:: images/file_protocol.*
    :align: center

1. The build slave initially sends "HELLO" with data ``slave_id`` where
   *slave_id* is the integer identifier of the slave. The master knows what
   file it requested from this slave (with "SEND" to the Slave Driver), and
   knows the file hash it is expecting from the "BUILT" message.

2. The master replies with "FETCH" with data ``[offset, length]`` where
   *offset* is a byte offset into the file, and *length* is the number of bytes
   to send.

3. The build slave replies with "CHUNK" with ``data`` where *data* is a
   byte-string containing the requested bytes from the file.

4. The master now either replies with another "FETCH" message or, when it has
   all chunks successfully received, replies with "DONE" indicating the
   build slave can now close the file (though it can't delete it yet; see
   the "DONE" message on the Slave Driver side for that).

"FETCH" messages may be repeated if the master drops packets (due to an
overloaded queue). Furthermore, because the protocol is semi-asynchronous
multiple "FETCH" messages will be sent before the master waits for any
returning "CHUNK" messages.


Security
========

Care must be taken when running the build slave. Building all packages in PyPI
effectively invites the denizens of the Internet to run arbitrary code on your
machine. For this reason, the following steps are recommended:

1. Never run the build slave on the master; ensure they are entirely separate
   machines.

2. Run the build slave as an unprivileged user which has access to nothing it
   doesn't absolutely require (it shouldn't have any access to the master's
   file-system, the master's database, etc.)

3. Install the build slave's code in a location the build slave's unprivileged
   user does not have write access (i.e. *not* in a virtualenv under the user's
   home dir).

4. Consider whether to make the unprivileged user's home-directory read-only.

We have experimented with read-only home directories, but a significant portion
of (usually scientifically oriented) packages attempt to be "friendly" and
either write data to the user's home directory or modify the user's profile
(:file:`~/.bashrc` and so forth).

The quandry is whether it is better to fail with such packages (a read-only
home-directory will most likely crash such setup scripts, failing the build),
or partially support them (leaving the home-directory writeable even though the
modifications on the build-slave won't be recorded in the resulting wheel and
thus won't be replicated on user's machines). There is probably no universally
good answer.

Currently, while the build slave cleans up the temporary directory used by pip
during wheel building, it doesn't attempt to clean its own home directory
(which setup scripts are free to write to). This is something that ought to be
addressed in future as it's a potentially exploitable hole.


.. _PostgreSQL: https://postgresql.org/
.. _ZeroMQ: https://zeromq.org/
.. _CBOR: https://cbor.io/
