import cmd
import argparse
import locale
import logging
from threading import Thread, Event
from signal import pause

import zmq

from .cli import PiWheelsCmd
from ..terminal import TerminalApplication
from .. import __version__


class PiWheelsMaster(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, __doc__)
        self.parser.add_argument('-d', '--database', '--db', default='piwheels',
                                 help='The name of the PostgreSQL database to '
                                 'connect to (default: %(default)s)')
        self.parser.add_argument('-H', '--host',
                                 help='The hostname of the PostgreSQL server '
                                 '(default: local machine)')
        self.parser.add_argument('-u', '--username',
                                 help='The username to use when connecting to '
                                 'the database (default: local machine '
                                 'connection uses logged on user)')
        self.parser.add_argument('-p', '--password',
                                 help='The password for the PostgreSQL user '
                                 '(default: implicit authentication for local '
                                 'machine users)')

    def main(self, args):
        cmd = PiWheelsCmd(args)
        cmd.cmdloop()


main = PiWheelsMaster()
