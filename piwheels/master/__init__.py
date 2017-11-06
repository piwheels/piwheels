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
from .seraph import Seraph
from .slave_driver import SlaveDriver
from .file_juggler import FileJuggler
from .index_scribe import IndexScribe
from .cloud_gazer import CloudGazer


logger = logging.getLogger('master')


class TaskFailure(RuntimeError):
    pass


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
            'oracle_queue':      'inproc://oracle',
            'ext_control_queue': 'ipc:///tmp/piw-control',
            'ext_status_queue':  'ipc:///tmp/piw-status',
            'slave_queue':       'tcp://*:5555',
            'file_queue':        'tcp://*:5556',
        })
        parser.add_section('master')
        parser.add_section('slave')
        if args.configuration is not None:
            config_files = parser.read(args.configuration)
        else:
            config_files = parser.read([
                '/etc/piwheels.conf',
                '/usr/local/etc/piwheels.conf',
                os.path.expanduser('~/.config/piwheels/piwheels.conf'),
            ])
        for f in config_files:
            logger.info('read configuration from %s', f)
        # Expand any ~ in output_path
        parser['master']['output_path'] = os.path.expanduser(parser['master']['output_path'])
        return parser['master']

    def main(self, args):
        signal.signal(signal.SIGTERM, self.sig_term)
        logger.info('PiWheels Master version {}'.format(__version__))
        config = self.load_configuration(args)
        ctx = zmq.Context.instance()
        tasks = [
            task(config)
            for task in (
                HighPriest,
                Seraph,
                TheOracle,
                TheOracle,
                TheOracle,
                TheArchitect,
                IndexScribe,
                FileJuggler,
                BigBrother,
                CloudGazer,
                SlaveDriver,
            )
        ]
        logger.info('starting tasks')
        for task in tasks:
            task.start()
        try:
            while True:
                for task in tasks:
                    task.join(1)
                    if not task.is_alive():
                        # As soon as any task dies, terminate
                        raise TaskFailure(task.name)
        except TaskFailure as e:
            # This isn't logged as a warning because it's normal: when QUIT is
            # sent (e.g. by the external monitor) tasks will start to close and
            # the loop above terminates
            logger.info('Shutting down on %s task termination', task.name)
            self.send_quit(ctx, config)
        except SystemExit:
            logger.warning('Shutting down on SIGTERM')
            self.send_quit(ctx, config)
        except KeyboardInterrupt:
            logger.warning('Shutting down on Ctrl+C')
            self.send_quit(ctx, config)
        finally:
            logger.info('closing tasks')
            for task in reversed(tasks):
                task.close()
            ctx.destroy(linger=0)
            ctx.term()

    def send_quit(self, ctx, config):
        q = ctx.socket(zmq.PUSH)
        try:
            q.connect(config['ext_control_queue'])
            q.send_pyobj(['QUIT'])
        finally:
            q.close(linger=0)

    def sig_term(self, signo, stack_frame):
        raise SystemExit(0)


main = PiWheelsMaster()
