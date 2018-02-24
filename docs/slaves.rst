=========
piw-slave
=========

The piw-slave script is intended to be run on a standalone machine to build
packages on behalf of the piw-master script. It is intended to be run as an
unprivileged user with a clean home-directory. Any build dependencies you wish
to use must already be installed. The script will run until it is explicitly
terminated, either by Ctrl+C, SIGTERM, or by the remote piw-master script.


Synopsis
========

::

    usage: piw-slave [-h] [--version] [-c FILE] [-q] [-v] [-l FILE] [-m HOST]
                     [-t DURATION]

Description
===========

.. program:: piw-slave

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

.. option:: -m HOST, --master HOST

    The IP address or hostname of the master server (default: localhost)

.. option:: -t DURATION, --timeout DURATION

    The time to wait before assuming a build has failed; (default: 3h)


Protocols
=========

The following sections document the protocols used between the build slaves and
the two sub-tasks that they talk to in the :doc:`master`. Each protocol
operates over a separate queue. All protocols in the piwheels system follow a
similar structure:

1. Each message is a list of Python objects.

2. The first element in the list is a string indicating the type of message.

3. Additional elements depend on the type of the message.

4. A given message type always contains the same number of elements (there are
   no variable length messages).


Slave Driver
------------

The queue that talks to :ref:`slave-driver` is a ZeroMQ REQ socket, hence the
protocol follows a strict request-reply sequence which is illustrated below:

.. image:: slave_protocol.*
    :align: center

1. The new build slave sends ``["HELLO", timeout, py_version_tag, abi_tag,
   platform_tag, label]`` where:

   * ``timeout`` is the slave's configured timeout (the length of time after
     which it will assume a build has failed and attempt to terminate it)

   * ``py_version_tag`` is the python version the slave will build for
     (e.g. "27", "35", etc.)

   * ``abi_tag`` is the ABI the slave will build for (e.g. "cp35m")

   * ``platform_tag`` is the platform of the slave (e.g. "linux_armv7l")

   * ``label`` is an identifying label for the slave (e.g. "slave2"); note
     that this label doesn't have to be anything specific, it's purely a
     convenience for administrators displayed in the monitor. In the current
     implementation this is the unqualified hostname of the slave

2. The master replies with ``["HELLO", slave_id]`` where *slave_id* is an
   integer identifier for the slave. Strictly speaking, the build slave doesn't
   need this identifier but it can be helpful for admins or developers to see
   the same identifier in logs on the master and the slave which is the only
   reason it is communicated.

3. The build slave sends ``["IDLE"]`` to indicate that it is ready to accept a
   build job.

4. The master can reply with ``["SLEEP"]`` which indicates that no jobs are
   currently available for that slave (e.g. the master is paused, or the build
   queue is empty, or there are no builds for the slave's particular ABI at
   this time). In this case the build slave should pause a while (the current
   implementation waits 10 seconds) before retrying IDLE.

5. The master can also reply wih ``["BYE"]`` which indicates the build slave
   should shutdown. In this case, after cleaning up any resources the build
   slave should send back ``["BYE"]`` and terminate (generally speaking,
   whenever the slave terminates it should send ``["BYE"]`` no matter where in
   the protocol it occurs; the master will take this as a sign of termination).

6. The master can also reply with ``["BUILD", package, version]`` where
   *package* is the name of a package to build and *version* is the version
   to build. At this point, the build slave should attempt to locate the
   package on PyPI and build a wheel from it.

7. Whatever the outcome of the build, the slave sends ``["BUILT", status,
   duration, output, files]``:

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

8. If the build succeeded, the master will send ``["SEND", filename]`` where
   *filename* is one of the names transmitted in the prior "BUILT" message.

9. At this point the slave should use the :ref:`file-juggler-protocol` protocol
   documented below to transmit the contents of the specified file to the
   master. When the file transfer is complete, the build slave sends
   ``["SENT"]`` to the master.

10. If the file transfer fails to verify, or if there are more files to send
    the master will repeat the "SEND" message. Otherwise, if all transfers have
    completed and have been verified, the master replies with ``["DONE"]``.

11. The build slave is now free to destroy all resources associated with the
    build, and returns to step 3 ("IDLE").

If at any point, the master takes more than 60 seconds to respond to a slave's
request, the slave will assume the master has disappeared. If a build is still
active, it will be cleaned up and terminated, the connection to the master will
be closed, the slave's ID will be reset and the slave must restart the protocol
from the top ("HELLO").

This permits the master to be upgraded or replaced without having to shutdown
and restart the slaves manually. It is possible that the master is restarted
too fast for the slave to notice. In this case the slave's next message will be
mis-interpreted by the master as an invalid initial message, and it will be
ignored. However, this is acceptable behaviour as the re-connection protocol
described above will then effectively restart the slave after the 60 second
timeout has elapsed.


.. _file-juggler-protocol:

File Juggler
------------

The queue that talks to :ref:`file-juggler` is a ZeroMQ DEALER socket. This is
because the protocol is semi-asynchronous (for performance reasons). For the
sake of illustration, a synchronous version of the protocol is illustrated
below:

.. image:: file_protocol.*
    :align: center

1. The build slave initially sends ``["HELLO", slave_id]`` where *slave_id* is
   the integer identifier of the slave. The master knows what file it requested
   from this slave (with "SEND" to the Slave Driver), and knows the file hash
   it is expecting from the "BUILT" message.

2. The master replies with ``["FETCH", offset, length]`` where *offset* is a
   byte offset into the file, and *length* is the number of bytes to send.

3. The build slave replies with ``["CHUNK", data]`` where *data* is a
   byte-string containing the requested bytes from the file.

4. The master now either replies with another "FETCH" message or, when it has
   all chunks successfully received, replies with ``["DONE"]`` indicating the
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
