==========
piw-import
==========

The piw-import script is used to inject the specified file(s) manually into the
piwheels database and file-system. This script must be run on the same node as
the piw-master script.

Synopsis
========

::

    usage: piw-import [-h] [--version] [-c FILE] [-q] [-v] [-l FILE]
                      [--package PACKAGE] [--package-version VERSION] [--abi ABI]
                      [--duration DURATION] [--output FILE] [-y] [-d]
                      [--import-queue ADDR]
                      files [files ...]


Description
===========

.. program:: piw-import

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

.. option:: --package PACKAGE

    The name of the package to import; if omitted this will be derived from the
    file(s) specified

.. option:: --package-version VERSION

    The version of the package to import; if omitted this will be derived from
    the file(s) specified

.. option:: --abi ABI

    The ABI of the package to import; if omitted this will be derived from the
    file(s) specified

.. option:: --duration DURATION

    The time taken to build the package (default: 0s)

.. option:: --output FILE

    The filename containing the build output to insert into the database; if
    this is omitted an appropriate message will be inserted instead

.. option:: -y, --yes

    Run non-interactively; never prompt during operation

.. option:: -d, --delete

    Remove the specified file(s) after a successful import; if the import
    fails, no files will be removed

.. option:: --import-queue ADDR

    The address of the queue used by piw-import (default:
    (ipc:///tmp/piw-import); this should always be an ipc address


Protocols
=========

The following section documents the protocol used between the importer and
the tasks that it talks to in the :doc:`master`. Each protocol operates over
a separate queue. All protocols in the piwheels system follow a similar
structure:

1. Each message is a list of Python objects.

2. The first element in the list is a string indicating the type of message.

3. Additional elements depend on the type of the message.

4. A given message type always contains the same number of elements (there are
   no variable length messages).


Mr Chase
--------

The queue that talks to :ref:`mr-chase` is a ZeroMQ REQ socket, hence the
protocol follows a strict request-reply sequence which is illustrated below:

.. image:: import_protocol.*
    :align: center

1. The importer sends ``["IMPORT", abi_tag, package, version, status, duration,
   output, files]``:

   * *abi_tag* is either ``None``, indicating that the master should use the
     "default" (minimum) build ABI registered in the system, or is a string
     indicating the ABI that the build was attempted for.

   * *package* is the name of the package that the build is for.

   * *version* is the version of the package that the build is for.

   * *status* is ``True`` if the build succeeded and ``False`` otherwise.

   * *duration* is a :class:`float` value indicating the length of time it took
     to build in seconds.

   * *output* is a string containing the complete build log.

   * *files* is a list of file state tuples containing the following fields
     in the specified order:

     - *filename* is the filename of the wheel.

     - *filesize* is the size in bytes of the wheel.

     - *filehash* is the SHA256 hash of the wheel contents.

     - *pacakge_tag* is the package tag extracted from the filename.

     - *package_version_tag* is the version tag extracted from the filename.

     - *py_version_tag* is the python version tag extracted from the
       filename.

     - *abi_tag* is the ABI tag extracted from the filename (sanitized).

     - *platform_tag* is the platform tag extracted from the filename.

2. If the import information is insufficient or incorrect, the master will
   send ``["ERROR", args, ...]`` where args and any further fields are the
   arguments of the exception that was raised.

3. If the import information is okay, the master will send ``["SEND",
   filename]`` for each file mentioned in the build.

4. At this point the importer should use the :ref:`file-juggler-protocol`
   protocol to transmit the contents of the specified file to the master. When
   the file transfer is complete, the importer sends ``["SENT"]`` to the
   master.

5. If the file transfer fails to verify, or if there are more files to send the
   master will repeat the "SEND" message. Otherwise, if all transfers have
   completed and have been verified, the master replies with ``["DONE"]``.

6. The importer is now free to remove all files associated with the build, if
   requested to.


Usage
=====

This script is used to import wheels manually into the system. This is useful
with packages which have no source available on PyPI, or binary-only packages
from third parties. If invoked with multiple files, all files will be
associated with a single "build" and the build will be for the package and
version of the first file specified. No checks are made for equality of package
name or version (as several packages on PyPI would violate such a rule!).

The utility can be run in a batch mode with :option:`--yes` but still requires
invoking once per build required (you cannot register multiple builds in a
single invocation).

The return code will be 0 if the build was registered and all files were
uploaded successfully. Additionally the :option:`--delete` option can be
specified to remove the source files once all uploads are completed
successfully. If anything fails, the return code will be non-zero and no files
will be deleted.

The utility should only ever be run directly on the master node (opening the
import queue to other machines is a potential security risk).
