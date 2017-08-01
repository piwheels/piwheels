__project__      = 'piwheels'
__version__      = '0.3'
__keywords__     = ['raspberrypi', 'pip', 'wheels']
__author__       = 'Ben Nuttall'
__author_email__ = 'ben@raspberrypi.org'
__url__          = 'http://www.piwheels.pihosted.com/'
__platforms__    = 'ALL'

__requires__ = ['pyzmq']

__extra_requires__ = {
    'monitor': ['urwid'],
    'master':  ['psycopg2', 'sqlalchemy', 'requests'],
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

