import os
import logging
import tempfile
from time import sleep
from datetime import datetime, timedelta
from threading import Thread
from pathlib import Path

import sqlalchemy as sa
import zmq
from pkg_resources import resource_string, resource_stream

from .states import FileState, SlaveState, TransferState
from ..terminal import TerminalApplication
from .. import __version__


class PiWheelsMaster(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, __doc__)
        self.parser.add_argument('-p', '--pypi-root', metavar='URL',
                                 default='https://pypi.python.org/pypi',
                                 help='The root URL of the PyPI repository '
                                 '(default: %(default)s)')
        self.parser.add_argument('-d', '--dsn', metavar='URL',
                                 default='postgres:///piwheels',
                                 help='The SQLAlchemy DSN used to connect to '
                                 'the piwheels database (default: %(default)s)')
        self.parser.add_argument('-o', '--output', metavar='PATH',
                                 default=Path(os.path.expanduser('~/www')),
                                 help='The path to write wheels into '
                                 '(default: %(default)s)')

    def setup_paths(self, args):
        output_path = Path(args.output)
        try:
            output_path.mkdir()
        except FileExistsError:
            pass
        try:
            (output_path / 'simple').mkdir()
        except FileExistsError:
            pass
        for filename in ('raspberry-pi-logo.svg', 'python-logo.svg'):
            with (output_path / filename).open('wb') as f:
                source = resource_stream(__name__, filename)
                f.write(source.read())
                source.close()
        TransferState.output_path = output_path

    def main(self, args):
        """
        The "main" task is responsible for constructing (and starting) the
        threads for all the sub-tasks. It also creates the queues used to
        interact with any monitors ("piw-control" and "piw-status"). Finally, it
        also creates and controls the internal "quit" queue, used to indicate to
        the sub-tasks when termination has been requested.
        """
        logging.info('PiWheels Master version {}'.format(__version__))
        self.db_engine = sa.create_engine(args.dsn)
        self.pypi_root = args.pypi_root
        self.setup_paths(args)
        packages_thread = Thread(target=self.web_scraper, daemon=True)
        builds_thread = Thread(target=self.queue_stuffer, daemon=True)
        status_thread = Thread(target=self.big_brother, daemon=True)
        slave_thread = Thread(target=self.slave_driver, daemon=True)
        files_thread = Thread(target=self.build_catcher, daemon=True)
        index_thread = Thread(target=self.index_scribbler, daemon=True)
        packages_thread.start()
        builds_thread.start()
        files_thread.start()
        status_thread.start()
        slave_thread.start()
        index_thread.start()
        try:
        except KeyboardInterrupt:
            logging.warning('Shutting down on Ctrl+C')
        finally:
            # Give all slaves 30 seconds to quit; this may seem rather arbitrary
            # but it's entirely possible there're dead slaves hanging around in
            # the slaves dict and there's no way (in our ridiculously simple
            # protocol) to terminate a slave in the middle of a build so an
            # arbitrary timeout is about the best we can do
            logging.warning('Waiting up to 30 seconds for slave shutdown')
            for slave in self.slaves.values():
                slave.kill()
            for i in range(30):
                if not self.slaves:
                    break
                sleep(1)
            int_control_queue.send_string('QUIT')
            index_thread.join()
            slave_thread.join()
            status_thread.join()
            files_thread.join()
            builds_thread.join()
            packages_thread.join()
            ctx.term()


main = PiWheelsMaster()
