===========
piw-rebuild
===========

The piw-rebuild script is used to inject rebuild requests for various web
pages into the piwheels system. This script must be run on the same node as
the piw-master script.

Synopsis
========

.. code-block:: text

    piw-rebuild [-h] [--version] [-c FILE] [-q] [-v] [-l FILE] [-y]
                [--import-queue ADDR]
                part [package]


Description
===========

.. program:: piw-rebuild

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

.. option:: --import-queue ADDR

    The address of the queue used by :program:`piw-rebuild` (default:
    (ipc:///tmp/piw-import); this should always be an ipc address


Usage
=====

This utility is used to request rebuilds of parts of the piwheels website. This
is primarily useful after manual fixes to the database, manipulation of the
file-system, or after large-scale upgrades which require rebuilding many pages.

The mandatory *part* parameter can be one of the following values, which
specify which part of the website to rebuild:

+---------+---------------------------------------------------------+
| Part    | Description                                             |
+=========+=========================================================+
| home    | Rebuild the home-page (/index.html)                     |
+---------+---------------------------------------------------------+
| search  | Rebuild the JSON search-index (/packages.json)          |
+---------+---------------------------------------------------------+
| project | Rebuild the project-page for the specified package      |
|         | (/project/*package*/index.html)                         |
+---------+---------------------------------------------------------+
| index   | Rebuild the simple-index *and* the project-page         |
|         | for the specified package (/simple/*package*/index.html |
|         | *and* /project/*package*/index.html)                    |
+---------+---------------------------------------------------------+

If *part* is "project" or "index" you may optionally specify a *package* name
for which to rebuild the specified part. If the *package* name is omitted, the
utility will request a rebuild of the specified part for **all** known packages
in the system.

.. warning::

    In the case a rebuild of **all** packages is requested, you will be
    prompted to make sure you wish to continue (this option can take hours to
    process on a system with many builds). The :option:`--yes` option can be
    used to skip this prompt but should be used carefully!

Note that the utility only requests the rebuild of the specified part. This
request will be queued, and acted upon as soon as :ref:`the-scribe` reaches it
but there is no guarantee this has occurred by the time the utility exits. The
return code will be 0 if the rebuild request was queued successfully. If
anything fails the return code will be non-zero and the request may or may not
have been queued.

The utility should only ever be run directly on the master node (opening the
import queue to other machines is a potential security risk).
