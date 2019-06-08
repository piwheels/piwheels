==========
piw-import
==========

The piw-import script is used to inject the specified file(s) manually into the
piwheels database and file-system. This script must be run on the same node as
the piw-master script. If multiple files are specified, they are registered
as produced by a *single* build.

Synopsis
========

.. code-block:: text

    piw-import [-h] [--version] [-c FILE] [-q] [-v] [-l FILE]
               [--package PACKAGE] [--package-version VERSION] [--abi ABI]
               [--duration DURATION] [--output FILE] [-y] [-d]
               [--import-queue ADDR]
               files [files ...]


Description
===========

.. program:: piw-import

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

    The address of the queue used by :program:`piw-import` (default:
    (ipc:///tmp/piw-import); this should always be an ipc address


Usage
=====

This utility is used to import wheels manually into the system. This is useful
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
