==========
piw-logger
==========

The piw-logger script is intended for use as an Apache "piped log script" but
can also be used to feed pre-existing Apache logs to the master by feeding
logs to the script's stdin. This script must be run on the same node as the
:doc:`master` script.

Synopsis
========

.. code-block:: text

    piw-logger [-h] [--version] [-c FILE] [-q] [-v] [-l FILE]
                    [--format FORMAT] [--log-queue ADDR] [--drop]
                    [files [files ...]]


Description
===========

.. program:: piw-logger

.. option:: files

    The log file(s) to load into the master; if omitted or "-" then stdin will
    be read which is the default for piped log usage

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

.. option:: --format FORMAT

    The Apache log format that log lines will be expected to be in (default:
    combined); the short-cuts common, combined and common_vhost can be used in
    addition to Apache LogFormat strings

.. option:: --log-queue ADDR

    The address of the queue used by piw-logger (default:
    (ipc:///tmp/piw-logger); this should always be an ipc address

.. option:: --drop

    Drop log records if unable to send them to the master after a short
    timeout; this should generally be specified when :program:`piw-logger` is
    used as a `piped log`_ script


Usage
=====

This utility is typically used to pipe logs from a web-server, such as
`Apache`_ into the piwheels database where they can be used for analysis, and
to keep the stats on the homepage up to date. Apache provides a capability to
pipe all logs to a given script which can be used directly with
:program:`piw-logger`.

A typical configuration under a Debian-like operating system might use the
Apache `CustomLog`_ directive as follows, within the Apache virtual host
reponsible for serving files to ``pip`` clients:

.. code-block:: apacheconf

    ErrorLog ${APACHE_LOG_DIR}/ssl_error.log
    CustomLog ${APACHE_LOG_DIR}/ssl_access.log combined
    CustomLog "|/usr/local/bin/piw-logger --drop" combined

.. _Apache: https://httpd.apache.org/
.. _CustomLog: http://httpd.apache.org/docs/current/mod/mod_log_config.html#customlog
.. _piped log: http://httpd.apache.org/docs/current/logs.html#piped
