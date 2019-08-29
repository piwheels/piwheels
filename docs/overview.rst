========
Overview
========

The piwheels project is designed to automate building of wheels from packages
on PyPI for a set of pre-configured ABIs. As the name suggests, it was
originally built for Raspberry Pis but there's nothing particular in the
codebase that should limit it to that platform. The system relies on the
following components:

+-----------------+---------------------------------------------------+
| Component       | Description                                       |
+=================+===================================================+
| :doc:`master`   | Coordinates the various build slaves, using the   |
|                 | database to store all relevant information, and   |
|                 | keeps the web site up to date.                    |
+-----------------+---------------------------------------------------+
| :doc:`slaves`   | Builds package on behalf of the piwheels master.  |
|                 | Is intended to run on separate machines to the    |
|                 | master, partly for performance and partly for     |
|                 | security.                                         |
+-----------------+---------------------------------------------------+
| :doc:`monitor`  | Provides a friendly curses-based UI for           |
|                 | interacting with the piwheels master.             |
+-----------------+---------------------------------------------------+
| :doc:`sense`    | Provides a friendly Sense HAT-based UI for        |
|                 | interacting with the piwheels master.             |
+-----------------+---------------------------------------------------+
| :doc:`initdb`   | A simple maintenance script for initializing or   |
|                 | upgrading the database to the current version.    |
+-----------------+---------------------------------------------------+
| :doc:`importer` | A tool for importing wheels manually into the     |
|                 | piwheels database and file-system.                |
+-----------------+---------------------------------------------------+
| :doc:`remove`   | A tool for manually removing builds from the      |
|                 | database and file-system.                         |
+-----------------+---------------------------------------------------+
| :doc:`rebuild`  | A tool for regenerating certain elements of the   |
|                 | piwheels web-site.                                |
+-----------------+---------------------------------------------------+
| :doc:`logger`   | A tool for transferring download statistics into  |
|                 | the piwheels database.                            |
+-----------------+---------------------------------------------------+
| database server | Currently only `PostgreSQL`_ is supported (and    |
|                 | frankly that's all we're ever likely to support). |
|                 | This provides the master's data store.            |
+-----------------+---------------------------------------------------+
| web server      | Anything that can serve from a static directory   |
|                 | is fine here. We use `Apache`_ in production.     |
+-----------------+---------------------------------------------------+

.. note::

    At present the master is a monolithic application, but the internal
    architecture is such that it could, in future, be split into three parts:
    one that deals exclusively with the database server, one that deals
    exclusively with the file-system served by the web server, and one that
    talks to the piwheels slave and monitor processes.

.. _PostgreSQL: https://postgresql.org/
.. _Apache: https://httpd.apache.org/
