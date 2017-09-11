import os
import signal
import logging
from configparser import ConfigParser

import zmq

from .. import __version__
from ..terminal import TerminalApplication
from .high_priest import HighPriest
from .big_brother import BigBrother
from .the_architect import TheArchitect
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
            'fs_queue':          'inproc://fs',
            'db_queue':          'inproc://db',
            'ext_control_queue': 'ipc:///tmp/piw-control',
            'ext_status_queue':  'ipc:///tmp/piw-status',
            'slave_queue':       'tcp://*:5555',
            'file_queue':        'tcp://*:5556',
        })
        parser.add_section('master')
        parser.add_section('slave')
        if args.configuration is not None:
            parser.read(args.configuration)
        else:
            parser.read([
                '/etc/piwheels.conf',
                '/usr/local/etc/piwheels.conf',
                os.path.expanduser('~/.config/piwheels/piwheels.conf'),
            ])
        # Expand any ~ in output_path
        parser['master']['output_path'] = os.path.expanduser(parser['master']['output_path'])
        return parser['master']

    def main(self, args):
        signal.signal(signal.SIGTERM, self.sig_term)
        logging.info('PiWheels Master version {}'.format(__version__))
        config = self.load_configuration(args)
        ctx = zmq.Context.instance()
        tasks = [
            task(**config)
            for task in (
                HighPriest,
                TheOracle,
                IndexScribe,
                FileJuggler,
                BigBrother,
                CloudGazer,
                TheArchitect,
                SlaveDriver,
            )
        ]
        for task in tasks:
            task.start()
        try:
            tasks[0].join()
        except SystemExit:
            logging.warning('Shutting down on SIGTERM')
            self.send_quit(ctx, config)
        except KeyboardInterrupt:
            logging.warning('Shutting down on Ctrl+C')
            self.send_quit(ctx, config)
        finally:
            for task in tasks:
                task.close()
            ctx.term()

    def send_quit(self, ctx, config):
        q = ctx.socket(zmq.PUSH)
        q.connect(config['ext_control_queue'])
        q.send_json(['QUIT'])
        q.close()

    def sig_term(signo, stack_frame):
        raise SystemExit(0)


main = PiWheelsMaster()
