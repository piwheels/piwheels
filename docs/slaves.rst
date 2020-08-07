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

.. code-block:: text

    piw-slave [-h] [--version] [-c FILE] [-q] [-v] [-l FILE] [-m HOST]
              [-t DURATION]


Description
===========

.. program:: piw-slave

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

.. option:: -m HOST, --master HOST

    The IP address or hostname of the master server (default: localhost)

.. option:: -t DURATION, --timeout DURATION

    The time to wait before assuming a build has failed (default: 3h)


Deployment
==========

Our typical method of deployment is to spin up a new Pi as a build slave
(through Mythic Beasts' control panel) then execute a script to install the
piwheels code, and all the build dependencies that we feel are reasonable to
support under various Raspbian versions. The deployment script can be found
in the root of the piwheels repository:

.. code-block:: console

    # wget https://raw.githubusercontent.com/piwheels/piwheels/master/deploy_slave.sh
    # chmod +x deploy_slave.sh
    # ./deploy_slave.sh

However, you will very likely wish to customize this script for your own
purposes, e.g. to support a different set of dependencies, or to customize the
typical build environment.

Once the script is complete, simply switch to the unprivileged user used to
run the build slave, and execute :doc:`slaves`. For example, assuming the
master's IP address is 10.0.0.1:

.. code-block:: console

    # su - piwheels
    $ piw-slave -m 10.0.0.1


Automatic start
===============

If you wish to ensure that the build slave starts on every boot-up, you may
wish to define a systemd unit for it. Example units can be also be found in
the root of the piwheels repository:

.. code-block:: console

    # wget https://raw.githubusercontent.com/piwheels/piwheels/master/piwheels-slave.service
    # cp piwheels-slave.service /etc/systemd/system/
    # systemctl daemon-reload
    # systemctl enable piwheels-slave
    # systemctl start piwheels-slave

.. warning::

    Be aware that this example unit forces a reboot in the case that the build
    slave fails (as occasionally happens with excessively complex packages).

    Because of this you *must* ensure that the slave executes successfully
    prior to installing the unit, otherwise you're liable to leave your build
    slave in permanent reboot cycle. This isn't a huge issue for a build slave
    that's physically in front of you (from which you can detach and tweak the
    storage), but it may be an issue if you're dealing with a cloud builder.
