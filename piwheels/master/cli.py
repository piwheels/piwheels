import logging
from time import sleep
from threading import Event, Thread
from collections import namedtuple

import zmq
from sqlalchemy import MetaData, Table, create_engine

from .cmdline import Cmd, CmdError, CmdSyntaxError
from .db import PiWheelsDatabase
from .. import __version__


Build = namedtuple('Build', (
    'package',
    'version',
    'status',
    'output',
    'filename',
    'filesize',
    'duration',
    'package_version_tag',
    'py_version_tag',
    'abi_tag',
    'platform_tag',
    'built_by',
))


class PiWheelsCmd(Cmd):
    prompt = 'PW> '

    def __init__(self, args):
        super().__init__()
        self.pprint('PiWheels Master version {}'.format(__version__))
        self.pprint(
            'Type "help" for more information, '
            'or "find" to locate PiWheels slaves')

    def preloop(self):
        super().preloop()

    def postloop(self):
        logging.warning('Shutting down...')
        super().postloop()

    def do_log(self, arg=''):
        """
        Control the logging output.

        Syntax: log pause|resume

        The log command can be used to pause or resume the printing of output
        from the background tasks. This is particularly useful when you don't
        want the output of other commands swamped.
        """
        if arg == 'pause':
            self.logging_handler.pause()
        elif arg == 'resume':
            self.logging_handler.resume()
        else:
            raise CmdSyntaxError('invalid argument to log: {}'.format(arg))

