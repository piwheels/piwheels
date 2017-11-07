import os
import signal
import logging

import zmq

from .. import __version__
from ..terminal import TerminalApplication
from .tasks import TaskQuit
from .big_brother import BigBrother
from .the_architect import TheArchitect
from .the_oracle import TheOracle
from .seraph import Seraph
from .slave_driver import SlaveDriver
from .file_juggler import FileJuggler
from .index_scribe import IndexScribe
from .cloud_gazer import CloudGazer


class TaskFailure(RuntimeError):
    pass


class PiWheelsMaster(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, __doc__)
        self.logger = logging.getLogger('master')

    def load_configuration(self, args):
        config = super().load_configuration(args, default={
            'master': {
                'database':          'postgres:///piwheels',
                'pypi_root':         'https://pypi.python.org/pypi',
                'output_path':       '/var/www',
                'int_status_queue':  'inproc://status',
                'index_queue':       'inproc://indexes',
                'build_queue':       'inproc://builds',
                'fs_queue':          'inproc://fs',
                'db_queue':          'inproc://db',
                'oracle_queue':      'inproc://oracle',
                'control_queue':     'ipc:///tmp/piw-control',
                'ext_status_queue':  'ipc:///tmp/piw-status',
                'slave_queue':       'tcp://*:5555',
                'file_queue':        'tcp://*:5556',
            },
        })
        config = dict(config['master'])
        # Expand any ~ in paths
        config['output_path'] = os.path.expanduser(config['output_path'])
        for item, value in list(config.items()):
            if item.endswith('_queue') and value.startswith('ipc://'):
                config[item] = os.path.expanduser(value)
        return config

    def main(self, args, config):
        self.logger.info('PiWheels Master version {}'.format(__version__))
        ctx = zmq.Context.instance()
        self.control_queue = ctx.socket(zmq.PULL)
        self.control_queue.hwm = 10
        self.control_queue.bind(config['control_queue'])
        self.int_status_queue = ctx.socket(zmq.PULL)
        self.int_status_queue.hwm = 10
        self.int_status_queue.bind(config['int_status_queue'])
        self.ext_status_queue = ctx.socket(zmq.PUB)
        self.ext_status_queue.hwm = 10
        self.ext_status_queue.bind(config['ext_status_queue'])
        self.tasks = [
            task(config)
            for task in (
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
        self.logger.info('starting tasks')
        for task in self.tasks:
            task.start()
        self.logger.info('started all tasks')
        signal.signal(signal.SIGTERM, self.sig_term)
        try:
            self.main_loop()
        except TaskQuit:
            pass
        except SystemExit:
            self.logger.warning('shutting down on SIGTERM')
        except KeyboardInterrupt:
            self.logger.warning('shutting down on Ctrl+C')
        finally:
            self.logger.info('closing tasks')
            for task in reversed(self.tasks):
                task.quit()
                task.close()
            self.logger.info('closed all tasks')
            ctx.destroy(linger=0)
            ctx.term()

    def main_loop(self):
        poller = zmq.Poller()
        poller.register(self.control_queue, zmq.POLLIN)
        poller.register(self.int_status_queue, zmq.POLLIN)
        while True:
            socks = dict(poller.poll())
            if self.int_status_queue in socks:
                self.ext_status_queue.send(self.int_status_queue.recv())
            if self.control_queue in socks:
                msg, *args = self.control_queue.recv_pyobj()
                try:
                    handler = getattr(self, 'do_%s' % msg)
                except AttributeError:
                    self.logger.error('ignoring invalid %s message', msg)
                else:
                    handler(args)

    def do_QUIT(self, args):
        self.logger.warning('shutting down on QUIT message')
        raise TaskQuit

    def do_KILL(self, args):
        self.logger.warning('killing slave %d', args[0])
        for task in self.tasks:
            if isinstance(task, SlaveDriver):
                task.kill_slave(args[0])

    def do_PAUSE(self, args):
        self.logger.warning('pausing operations')
        for task in self.tasks:
            task.pause()

    def do_RESUME(self, args):
        self.logger.warning('resuming operations')
        for task in self.tasks:
            task.resume()

    def do_HELLO(self, args):
        self.logger.warning('sending status to new monitor')
        for task in self.tasks:
            if isinstance(task, SlaveDriver):
                task.list_slaves()

    def sig_term(self, signo, stack_frame):
        raise SystemExit(0)


main = PiWheelsMaster()
