from threading import Event, Thread

import zmq
from sqlalchemy import MetaData, Table, create_engine

from .cmdline import Cmd
from .db import PiWheelsDatabase
from .. import __version__

class PiWheelsCmd(Cmd):
    prompt = 'PW: '

    def __init__(self, args):
        super().__init__()
        self.pprint('PiWheels Master version {}'.format(__version__))
        self.pprint(
            'Type "help" for more information, '
            'or "find" to locate PiWheels slaves')
        self.args = args

    def preloop(self):
        self.terminate = Event()
        self.pong_set = {}
        # Configure the SQLAlchemy engine and meta-data storage; table
        # definitions are loaded automatically from the database which must
        # be pre-built with the provided creation script
        self.db_engine = create_engine(self.args.dsn)
        self.db_meta = MetaData
        self.db_meta.bind = self.db_engine
        Table('packages', self.db_meta, autoload=True)
        Table('versions', self.db_meta, autoload=True)
        Table('builds', self.db_meta, autoload=True)
        Table('files', self.db_meta, autoload=True)
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

    def update_pkgs(self):
        with PiWheelsDatabase(**vars(self.args)) as db:
            while not self.terminate.wait(60):
                db.update_package_list()
                db.update_package_version_list()

    def queue_jobs(self):
        q = self.zmq_context.socket(zmq.PUSH)
        q.ipv6 = True
        q.bind('tcp://*:5555')
        try:
            with PiWheelsDatabase(**vars(self.args)) as db:
                while not self.terminate.wait(5):
                    if idle.wait(0):
                        for package, version in db.get_build_queue():
                            q.send_json((package, version))
                            if self.terminate.wait(0): # check terminate regularly
                                break
                        idle.clear()
        finally:
            q.close()

    def log_results(self):
        q = self.zmq_context.socket(zmq.PULL)
        q.ipv6 = True
        q.bind('tcp://*:5556')
        try:
            with PiWheelsDatabase(**vars(self.args)) as db:
                while not self.terminate.wait(0):
                    events = q.poll(1000)
                    if events:
                        slave_id, msg, *args = q.recv_json()
                        if msg == 'IDLE':
                            logging.warning('Slave %s is idle', slave_id)
                            idle.set()
                        elif msg == 'PONG':
                            self.pong_set.add(slave_id)
                        else:
                            db.log_build(*msg)
        finally:
            q.close()

