import signal
import logging
from configparser import ConfigParser
from pathlib import Path
from signal import pause

import zmq

from .. import __version__
from ..terminal import TerminalApplication
from .high_priest import HighPriest
from .big_brother import BigBrother
from .the_oracle import TheOracle
from .slave_driver import SlaveDriver
from .file_juggler import FileJuggler
from .index_scribe import IndexScribe
from .cloud_gazer import CloudGazer


class PiWheelsMaster(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, __doc__)
        self.parser.add_argument(
            '-c', '--configuration', metavar='FILE', default=None,
            help='Specify a configuration file to load')

    def load_configuration(self, args):
        parser = ConfigParser(interpolation=None, defaults={
            'database':          'postgres:///piwheels',
            'pypi_root':         'https://pypi.python.org/pypi',
            'output_path':       '/var/www',
            'int_control_queue': 'inproc://control',
            'int_status_queue':  'inproc://status',
            'index_queue':       'inproc://indexes',
            'build_queue':       'inproc://builds',
            'ext_control_queue': 'ipc:///tmp/piw-control',
            'ext_status_queue':  'ipc:///tmp/piw-status',
            'slave_queue':       'tcp://*:5555',
            'file_queue':        'tcp://*:5556',
        })
        parser.add_section('master')
        parser.add_section('slave')
        if args.config is not None:
            parser.read(args.config)
        else:
            parser.read([
                '/etc/piwheels.conf',
                '/usr/local/etc/piwheels.conf',
                str(Path('~/.config/piwheels/piwheels.conf').expanduser()),
            ])
        return parser['master']

    def main(self, args):
        signal.signal(signal.SIGTERM, self.sig_term)
        logging.info('PiWheels Master version {}'.format(__version__))
        config = self.load_configuration(args)
        self.setup_paths(args)
        ctx = zmq.Context.instance()
        tasks = [
            task(**config)
            for task in (
                HighPriest,
                BigBrother,
                CloudGazer,
                TheOracle,
                SlaveDriver,
                FileJuggler,
                IndexScribe,
            )
        ]
        try:
            pause()
        except SystemExit:
            logging.warning('Shutting down on SIGTERM')
        except KeyboardInterrupt:
            logging.warning('Shutting down on Ctrl+C')
        finally:
            for task in tasks:
                task.close()
            ctx.term()

    def sig_term(signo, stack_frame):
        raise SystemExit(0)


main = PiWheelsMaster()
