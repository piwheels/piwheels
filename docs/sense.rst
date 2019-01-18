=========
piw-sense
=========

The piw-sense application is an alternative monitor for the piw-master script
that uses the Raspberry Pi Sense HAT as its user interface.  Upon startup it
will request the status of all build slaves currently known to the master, and
will then continually update its display as the slaves progress through builds.
The Sense HAT's joystick can be used to navigate information about current
builds, and kill builds slaves that are having issues, or terminate the master
itself.


Synopsis
========

.. code-block:: text

    piw-sense [-h] [--version] [-c FILE] [--status-queue ADDR]
                   [--control-queue ADDR] [-r DEGREES]


Description
===========

.. program:: piw-sense

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

.. option:: -r DEGREES, --rotate DEGREES

    The rotation of the HAT in degrees; must be 0 (the default), 90, 180,
    or 270


Usage
=====

The Sense monitor can be started on the same machine as the master after the
:doc:`master` script has been started.  After initialization it will request
the current status of all build slaves from the master.


Layout
------

The top three (normally blue) rows of the display are used for some important
statistics:

* The top row represents the ping time from the master, or more specifically
  the time since the last message was received. This will continually increase
  (changing white), and reset with each message received. If 30 seconds elapse
  without any messages being received, this row will pulse red until another
  message is received, resetting the count.

* The second row represents available disk space for the output directory on
  the master. White pixels represent remaining space, and the scale is simply
  percentage (all blue = 0%, all white = 100%).

* The third row represents the number of pending builds on the master. The
  scale is one white pixel = 8 builds in the queue (with partial shades
  representing <8 builds).

The remaining rows represent all build slaves. Each pixel represents a single
build slave, working vertically then horizontally. Build slaves are sorted
first by ABI, then by label (as in :doc:`monitor`).

* A gray pixel indicates an idle build slave.

* A green pixel indicates an active build.

* A blue pixel indicates an active file transfer after a successful build.

* A purple pixel indicates a build slave cleaning up after a build.

* A yellow pixel indicates an active build that's been running for more than
  15 minutes; not necessarily a problem but longer than average.

* A red pixel indicates a build slave that's either timed out or been
  terminated; it should disappear from the display within a few seconds.


Navigation
----------

The pixel that pulses white indicates your current position, which can be moved
with the Sense HAT joystick. Pressing the joystick in when a build-slave is
selected (indicated by it pulsing white) will bring up detailed information on
that build slave.

Scroll left and right to navigate through the build-slave information (label,
ABI, current task, and kill option). Press the joystick in to return to the
main display (optionally killing the build slave if the kill screen is
selected).

Scroll the cursor off the top of the display to go to detailed statistics
information. Scroll left and right to navigate through the available statistics
(ping time, disk free, queue size, build rate, total build time, and total
build size). Most statistics are displayed as scrolling text, and a background
fill representing the information graphically. Scroll down to return to the
main screen.

Scroll the cursor off the bottom of the display to go to the quit and terminate
options (scroll left and right to navigate between them). Press the joystick in
to activate either option, or scroll up to return to the main screen.
