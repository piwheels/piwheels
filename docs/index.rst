========
piwheels
========

Welcome to the developer and administrator documentation for the piwheels
service. If you simply want to *use* piwheels to install Python packages more
quickly on your Raspberry Pi, head over to the `piwheels homepage`_ for the
relevant information.

However, if you want to set up your own instance of piwheels, or hack on the
piwheels codebase, you're in the right place! These documents are far from
comprehensive and there's really no substitute for just playing with the system
at first, but hopefully they'll provide some answers to anyone who gets
confused wandering through the code (although much of the documentation is
derived from the code) and some starting points for those that want to get
involved. For reference, the `piwheels code`_ is available from GitHub
(naturally) which also hosts the `issue tracker`_. Note there is a separate
issue tracker for reporting issues with packages built by piwheels.org, which
can be found at `piwheels/packages`_.


Table of Contents
=================

.. toctree::
    :maxdepth: 1
    :numbered:

    overview
    master
    slaves
    monitor
    sense
    initdb
    importer
    rebuild
    remove
    logger
    development
    modules
    license


Indexes and Tables
==================

* :ref:`genindex`
* :ref:`search`


.. _piwheels homepage: https://www.piwheels.org/
.. _piwheels code: https://github.com/piwheels/piwheels
.. _issue tracker: https://github.com/piwheels/piwheels/issues
.. _piwheels/packages: https://github.com/piwheels/packages/issues
