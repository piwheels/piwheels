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
        self.parser.add_argument('-d', '--dsn', default='postgres:///piwheels',
                                 help='The SQLAlchemy DSN used to connect to '
                                 'the piwheels database (default: %(default)s)')

    def main(self, args):
        cmd = PiWheelsCmd(args)
        cmd.cmdloop()


main = PiWheelsMaster()
