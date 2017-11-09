============
Build Slaves
============

The piwheels build slaves are small, simple scripts which communicate with the
master to receive tasks, and to send the results of those builds back (along
with any files generated).


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
   platform_tag]`` where:

   * ``timeout`` is the slave's configured timeout (the length of time after
     which it will assume a build has failed and attempt to terminate it)

   * ``py_version_tag`` is the python version the slave will build for
     (e.g. "27", "35", etc.)

   * ``abi_tag`` is the ABI the slave will build for (e.g. "cp35m")

   * ``platform_tag`` is the platform of the slave (e.g. "linux_armv7l")

2. The master replies with ``["HELLO", slave_id]`` where ``slave_id`` is an
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
   ``package`` is the name of a package to build and ``version`` is the version
   to build. At this point, the build slave should attempt to locate the
   package on PyPI and build a wheel from it.

7. Whatever the outcome of the build, the slave sends ``["BUILT", package,
   version, status, duration, output, files]``:

   * ``package`` is the name of the package that was built (the master should
     check this matches what the slave was asked to build).

   * ``version`` is the version of the package that was built (again, the
     master should check this matches what the slave was asked to do).

   * ``status`` is ``True`` if the build succeeded and ``False`` otherwise.

   * ``duration`` is a :class:`~datetime.timedelta` value indicating the length
     of time it took to build.

   * ``output`` is a string containing the complete build log.

   * ``files`` is a list of file state tuples containing the following fields
     in the specified order:

     - ``filename`` is the filename of the wheel.

     - ``filesize`` is the size in bytes of the wheel.

     - ``filehash`` is the SHA256 hash of the wheel contents.

     - ``pacakge_tag`` is the package tag extracted from the filename.

     - ``package_version_tag`` is the version tag extracted from the filename.

     - ``py_version_tag`` is the python version tag extracted from the
       filename.

     - ``abi_tag`` is the ABI tag extracted from the filename (sanitized).

     - ``platform_tag`` is the platform tag extracted from the filename.

8. If the build succeeded, the master will send ``["SEND", filename]`` where
   ``filename`` is one of the names transmitted in the prior "BUILT" message.

9. At this point the slave should use the :ref:`file-juggler` protocol
   documented below to transmit the contents of the specified file to the
   master. When the file transfer is complete, the build slave sends
   ``["SENT"]`` to the master.

10. If the file transfer fails to verify, or if there are more files to send
    the master will repeat the "SEND" message. Otherwise, if all transfers have
    completed and have been verified, the master replies with ``["DONE"]``.

11. The build slave is now free to destroy all resources associated with the
    build, and returns to step 3 ("IDLE").


File Juggler
------------

The queue that talks to :ref:`file-juggler` is a ZeroMQ DEALER socket. This is
because the protocol is semi-asynchronous (for performance reasons). For the
sake of illustration, a synchronous version of the protocol is illustrated
below:

.. image:: file_protocol.*
    :align: center


Security
========
