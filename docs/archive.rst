==========================
Archiving and piw-archive
==========================

piwheels moves wheel files whose builds see little download traffic off the
master onto a separate archive server, to keep the master's disk usage down,
and moves them back if they become popular again. This is done automatically
by the master, with :program:`piw-archive` available as a manual override
for one-off moves.

Automatic archiving
====================

The :program:`piw-master` service runs an internal task, ``TheArchivist``,
which periodically:

#. Queries the database for files whose builds received few downloads in the
   last month, and moves them from the master to the archive server.
#. Queries the database for archived files whose builds have become popular
   again, and moves them back to the master.
#. For each affected package, updates the database's record of the new
   file location(s) and requests a rebuild of that package's index page.
#. Deletes the source-side copy of each file once it's confirmed to have
   been copied and the database/index have been updated.

This task is only enabled when :option:`piw-master --archive-dir` is given
(pointing at the archive server's mount point). Its behaviour can be tuned
with :option:`piw-master --archive-threshold`,
:option:`piw-master --unarchive-threshold`, and
:option:`piw-master --archive-interval`; see :doc:`master` for details.

.. _archive-audit-runbook:

Manual audit and symlink repair
================================

The automatic task only copies files, updates the database, and rebuilds
indexes; it deliberately does **not** audit the resulting directories or
repair symlinks, since these are filesystem consistency checks best run
without a build in progress for the package concerned. Run these manually
from time to time (e.g. after a large batch of archiving, or if
:program:`piw-audit-packages` or the website reports missing files):

.. code-block:: console

    $ piw-audit-packages <package> --delete-extras --ensure-project-symlinks \
        --archive-dir /path/to/archive/www

See :program:`piw-audit-packages` for the full set of options.

armv6l wheels are relative symlinks to their armv7l counterpart (see
:func:`~piwheels.states.BuildState.create_armv6_symlink`). Moving the
armv7l file to or from the archive without its armv6l symlink (or vice
versa) leaves a dangling symlink on whichever side no longer has both. To
find and repair these after an archiving run, from the directory containing
the list of moved ``package/filename`` entries:

.. code-block:: console

    $ BASE=/path/to/simple  # master or archive "simple" directory, as appropriate
    $ while read -r f; do
    >     path="$BASE/$f"
    >     [ -L "$path" ] && ! [ -e "$path" ] && echo "$f"
    > done < files.txt > broken.txt
    $ grep armv6l broken.txt | sed 's/armv6l/armv7l/g' > armv7.txt
    $ while read -r f; do
    >     armv7="$BASE/$f"
    >     armv6="${armv7/armv7l/armv6l}"
    >     [ -e "$armv7" ] && [ ! -e "$armv6" ] && [ ! -L "$armv6" ] && \
    >         ln -s "$(basename "$armv7")" "$armv6"
    > done < armv7.txt

piw-archive
===========

The :program:`piw-archive` script is used to manually move files from the
master to the archive or vice-versa. Unlike the automatic task, it only
copies files; it does not update the database or rebuild indexes, so it
should be followed by a manual database update and, if needed, the audit
steps above. This script must be run on the same node as the
:doc:`piw-master <master>` service.

Synopsis
--------

.. code-block:: text

    piw-archive [-h] [--version] [-o PATH] --archive-dir PATH [--unarchive]
                files_file

Description
-----------

.. program:: piw-archive

.. option:: files_file

    The text file containing the list of wheels to archive, one
    ``package/filename`` per line

.. option:: -h, --help

    Show this help message and exit

.. option:: --version

    Show program's version number and exit

.. option:: -o PATH, --output-path PATH

    The path under which the website is stored

.. option:: --archive-dir PATH

    The location of the archive server's mount point (required)

.. option:: --unarchive

    Move files from the archive back to the master, instead of from the
    master to the archive
