===========
piw-monitor
===========

The piw-monitor application is used to monitor (and optionally control) the
piw-master script. Upon startup it will request the status of all build slaves
currently known to the master, and will then continually update its display as
the slaves progress through builds. The controls at the bottom of the display
allow the administrator to pause or resume the master script, kill build
slaves that are having issues (e.g. excessive resource consumption from a huge
build) or terminate the master itself.


Synopsis
========

.. code-block:: text

    piw-monitor [-h] [--version] [-c FILE] [--status-queue ADDR]
                [--control-queue ADDR]


Description
===========

.. program:: piw-monitor

.. option:: -h, --help

    Show this help message and exit

.. option:: --version

    Show program's version number and exit

.. option:: -c FILE, --configuration FILE

    Specify a configuration file to load

.. option:: --status-queue ADDR

    The address of the queue used to report status to monitors (default:
    ipc:///tmp/piw-status)

.. option:: --control-queue ADDR

    The address of the queue a monitor can use to control the master (default:
    ipc:///tmp/piw-control)


Usage
=====

The monitor application should be started on the same machine as the master
after the :doc:`master` script has been started. After initialization it will
request the current status of all build slaves from the master, displaying this
in a list in the middle of the screen.

The :kbd:`Tab` key can be used to navigate between the list of build slaves and
the controls at the bottom of the screen. Mouse control is also supported,
provided the terminal emulator supports it. Finally, hot-keys for all actions
are available. The actions are as follows:


Pause
-----

Hotkey: :kbd:`p`

Pauses operations on the master. This causes :ref:`cloud-gazer` to stop
querying PyPI, :ref:`slave-driver` to return "SLEEP" in response to any build
slave requesting new packages, and so on. This is primarily a debugging tool to
permit the developer to peek at the system in a more or less frozen state
before resuming things.


Resume
------

Hotkey: :kbd:`r`

Resumes operations on the master when paused.


Kill Slave
----------

Hotkey: :kbd:`k`

The next time the selected build slave requests a new package (with "IDLE") the
master will return "BYE" indicating the slave should terminate. Note that this
cannot kill a slave in the middle of a build (that would require a more complex
asynchronous protocol in :ref:`slave-driver`), but is useful for shutting
things down in an orderly fashion.


Terminate Master
----------------

Hotkey: :kbd:`t`

Tells the master to shut itself down. In a future version, the master *should*
request all build slaves to terminate as well, but currently this is
unimplemented.


Quit
----

Hotkey: :kbd:`q`

Terminate the monitor. Note that this won't affect the master.
