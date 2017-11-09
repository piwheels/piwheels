========
Overview
========

The piwheels project is designed to automate building of wheels from packages
on PyPI for a set of pre-configured ABIs. As the name suggests, it was
originally built for Raspberry Pis but there's nothing particular in the
codebase that should limit it to that platform. The system relies on the
following components:

+-------------------------+---------------------------------------------------+
| Component               | Description                                       |
+=========================+===================================================+
| piwheels :doc:`master`  | Coordinates the various build slaves, using the   |
|                         | database to store all relevant information, and   |
|                         | keeps the web site up to date.                    |
+-------------------------+---------------------------------------------------+
| piwheels :doc:`slave`   | Builds package on behalf of the piwheels master.  |
|                         | Is intended to run on separate machines to the    |
|                         | master, partly for performance and partly for     |
|                         | security.                                         |
+-------------------------+---------------------------------------------------+
| piwheels :doc:`monitor` | Provides a friendly curses-based UI for           |
|                         | interacting with the piwheels master.             |
+-------------------------+---------------------------------------------------+
| database server         | Currently only `PostgreSQL`_ is supported (and    |
|                         | frankly that's all we're ever likely to support). |
|                         | This provides the master's data store.            |
+-------------------------+---------------------------------------------------+
| web server              | Anything that can serve from a static directory   |
|                         | is fine here. We use `Apache`_ in production.     |
+-------------------------+---------------------------------------------------+

.. note::

    At present the master is a monolithic application, but the internal
    architecture is such that it could, in future, be split into three parts:
    one that deals exclusively with the database server, one that deals
    exclusively with the file-system served by the web server, and one that
    talks to the piwheels slave and monitor processes.


Deployment
==========

A typical deployment of the master service on a Raspbian server goes something
like this (all chunks assume you start as root):

1. Install the pre-requisite software:

   .. code-block:: console

       # apt install postgresql-9.6 apache2
       # pip install piwheels

2. Set up the (unprivileged) piwheels user and the output directory:

   .. code-block:: console

       # groupadd piwheels
       # useradd -g piwheels -m piwheels
       # mkdir /var/www/piwheels
       # chown piwheels:piwheels /var/www/piwheels

3. Set up the database:

   .. code-block:: console

       # su - postgres
       $ createuser piwheels
       $ createdb -O postgres piwheels
       $ piw-init-db piwheels

4. Set up the web server:

   * Point the document root to the output path (:file:`/var/www/piwheels`
     above, but it can be anywhere your piwheels user has write access to;
     naturally you want to make sure your web-server's user only has *read*
     access to the location).
   * Set up SSL for the web server (e.g. with `Let's Encrypt`_; the
     `dehydrated`_ utility is handy for getting and maintaining the SSL
     certificates).

5. Start the master running (it'll take quite a while to populate the list of
   packages and versions from PyPI on the initial run so get this going before
   you start bringing up build slaves):

   .. code-block:: console

       # su - piwheels
       $ piw-master -v

6. Deploy some build slaves *on separate machines*:

   .. code-block:: console

       # wget https://github.com/bennuttall/piwheels/master/deploy_slave.sh
       # chmod +x deploy_slave.sh
       # ./deploy_slave.sh

7. Start the build slave running (assuming your master's IP address is
   10.0.0.1):

   .. code-block:: console

       # su - piwheels
       $ piw-slave -v -m 10.0.0.1


Upgrades
========

The master will check that build slaves have the same version number and will
reject them if they do not. Furthermore, it will check the version number in
the database's *configuration* table matches its own and fail if it does not.
Re-run the :program:`piw-init-db` script as the postgres super-user to upgrade
the database between versions (downgrades are not supported, so take a backup
first!).

.. _PostgreSQL: https://postgresql.org/
.. _Apache: https://httpd.apache.org/
.. _Let's Encrypt: https://letsencrypt.org/
.. _dehydrated: https://github.com/lukas2511/dehydrated
