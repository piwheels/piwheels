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
        self.args = args

    def preloop(self):
        super().preloop()
        self.idle = Event()
        self.terminate = Event()
        self.pong_set = set()
        # Configure the SQLAlchemy engine and meta-data storage; table
        # definitions are loaded automatically from the database which must
        # be pre-built with the provided creation script
        self.db_engine = create_engine(self.args.dsn)
        # Configure the primary 0MQ queue used to pass control messages to the
        # slaves. This is used by the main application's thread
        self.zmq_context = zmq.Context()
        self.ctrl_queue = self.zmq_context.socket(zmq.PUB)
        self.ctrl_queue.ipv6 = True
        self.ctrl_queue.bind('tcp://*:5557')
        # Set up the various background threads; these construct their own
        # database connections from the engine, and their own queues from the
        # 0MQ context
        self.pkg_thread = Thread(target=self.update_pkgs, daemon=True)
        self.job_thread = Thread(target=self.queue_jobs, daemon=True)
        self.log_thread = Thread(target=self.log_results, daemon=True)
        self.pkg_thread.start()
        self.job_thread.start()
        self.log_thread.start()

    def postloop(self):
        logging.warning('Shutting down...')
        self.terminate.set()
        self.job_thread.join()
        self.log_thread.join()
        self.pkg_thread.join()
        self.ctrl_queue.send_json(('*', 'QUIT'))
        self.ctrl_queue.close()
        self.zmq_context.term()
        super().postloop()

    def update_pkgs(self):
        with PiWheelsDatabase(self.db_engine) as db:
            while True:
                db.update_package_list()
                for package in db.get_all_packages():
                    db.update_package_version_list(package)
                    if self.terminate.wait(0): # check terminate regularly
                        break
                if self.terminate.wait(60):
                    break

    def queue_jobs(self):
        q = self.zmq_context.socket(zmq.PUSH)
        q.ipv6 = True
        q.bind('tcp://*:5555')
        try:
            with PiWheelsDatabase(self.db_engine) as db:
                while True:
                    if self.idle.wait(0):
                        for package, version in db.get_build_queue():
                            q.send_json((package, version))
                            if self.terminate.wait(0): # check terminate regularly
                                break
                        self.idle.clear()
                    if self.terminate.wait(10):
                        break
        finally:
            q.close()

    def log_results(self):
        q = self.zmq_context.socket(zmq.PULL)
        q.ipv6 = True
        q.bind('tcp://*:5556')
        try:
            with PiWheelsDatabase(self.db_engine) as db:
                while not self.terminate.wait(0):
                    events = q.poll(1000)
                    if events:
                        slave_id, msg, *args = q.recv_json()
                        if msg == 'IDLE':
                            logging.warning('Slave %s is idle', slave_id)
                            self.idle.set()
                        elif msg == 'PONG':
                            self.pong_set.add(slave_id)
                        elif msg == 'BUILT':
                            db.log_build(Build(*args))
        finally:
            q.close()

    def do_find(self, arg=''):
        """
        Find all the build slaves currently in existence.

        This command sends a PING command to all slaves, waits a second and
        lists the IDs of all slaves that responded.
        """
        self.pong_set.clear()
        self.ctrl_queue.send_json(('*', 'PING'))
        sleep(1)
        self.pprint('{} slaves responded'.format(len(self.pong_set)))
        if self.pong_set:
            self.pprint()
            self.pprint_table(
                [(slave_id,) for slave_id in self.pong_set],
                header_rows=0)

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

