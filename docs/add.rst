=======
piw-add
=======

The piw-add script is used to manually add new packages (and versions of
packages) to the system. This script must be run on the same node as the
piw-master script.

Synopsis
========

.. code-block:: text

    piw-add [-h] [--version] [-c FILE] [-q] [-v] [-l FILE] [-y] [-s REASON]
                 [--unskip] [-d TEXT] [-a NAME] [-r TIMESTAMP] [--yank]
                 [--unyank] [--import-queue ADDR]
                 package [version]

Description
===========

.. program:: piw-add

.. option:: package

    The name of the package to add

.. option:: version

    The version of the package to add; if omitted, adds the package only

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

.. option:: -y, --yes

    Run non-interactively; never prompt during operation

.. option:: -s REASON, --skip REASON

    Mark the package or version with a skip reason to prevent build attempts

.. option:: --unskip

    Remove a skip reason for the package or version to enable build attempts

.. option:: -d TEXT, --description TEXT

    The package description; defaults to retrieving the description from PyPI

.. option:: -a ALIAS, --alias ALIAS

    Any package aliases to use; may be specified multiple times

.. option:: -r TIMESTAMP, --released TIMESTAMP

    The version's release date (can only be provided for a new version, cannot
    be updated); defaults to now

.. option:: --yank

    Mark the version as yanked (can only be applied to a new version - use
    :doc:`remove` to yank a known version

.. option:: --unyank

    Mark a known version as not yanked

.. option:: --import-queue ADDR

    The address of the queue used by piw-add (default: (ipc:///tmp/piw-import);
    this should always be an ipc address


Usage
=====

This utility is intended to permit administrators to tweak the content of the
database to correct issues that arise from either incorrect scraping of the
PyPI history, inadvertent mistakes made with :doc:`remove`, or other
inconsistencies found in the database.

The utility can be run in a batch mode with :option:`--yes` but still requires
invoking once per addition required (you cannot define multiple packages or
versions in a single invocation).

The return code will be 0 if the package (or version) was successfully added to
the database. If anything fails, the return code will be non-zero and the
database should remain unchanged.

The utility should only ever be run directly on the master node (opening the
import queue to other machines is a potential security risk).
