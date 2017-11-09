"""
The piwheels project provides a set of tools for generating wheels from the
PyPI repository for a given set of Python ABIs. Currently, three scripts are
defined:

* ``piw-slave`` - this is the simple build slave script. Build slaves should be
  deployed using the ``deploy_slave.sh`` script from the source repository.
  This ensures that slaves are set up with a non-root user for building which
  has no write access to its own source code, and that common library
  dependencies for various builds are pre-installed.

* ``piw-master`` - this is the coordinating server script. It handles querying
  PyPI for packages to build, handing jobs to build slaves, receiving the
  results of builds, transferring files from build slaves, generating the
  package index, and keeping the PostgreSQL database up to date. In future this
  may be split into several scripts for performance or security reasons.

* ``piw-monitor`` - this is the curses-style monitoring client which can be run
  to watch the state of ``piw-master``. It also provides interactive functions
  for killing build slaves, and pausing / resuming / killing the master process
  itself.
"""

# Stop pylint's crusade against nicely aligned code
# pylint: disable=bad-whitespace
# flake8: noqa

__project__      = 'piwheels'
__version__      = '0.8'
__keywords__     = ['raspberrypi', 'pip', 'wheels']
__author__       = 'Ben Nuttall'
__author_email__ = 'ben@raspberrypi.org'
__url__          = 'https://www.piwheels.hostedpi.com/'
__platforms__    = 'ALL'

__requires__ = ['pyzmq']

__extra_requires__ = {
    'monitor': ['urwid'],
    'master':  ['sqlalchemy'],
    'slave':   ['pip', 'wheel', 'python-dateutil'],
    'test':    ['pytest'],
}

__classifiers__ = [
    'Development Status :: 4 - Beta',
    'Environment :: Console',
    'Intended Audience :: Science/Research',
    'License :: OSI Approved :: BSD License',
    'Operating System :: POSIX',
    'Operating System :: Unix',
    'Programming Language :: Python :: 3',
]

__entry_points__ = {
    'console_scripts': [
        'piw-master = piwheels.master:main',
        'piw-slave = piwheels.slave:main',
        'piw-monitor = piwheels.monitor:main',
    ],
}
