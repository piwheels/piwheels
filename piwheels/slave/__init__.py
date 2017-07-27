import os
import argparse
import locale
import logging
from datetime import datetime
from time import sleep
from threading import Event, Thread
from signal import pause
from pathlib import Path

import zmq

from .builder import PiWheelsBuilder
from ..terminal import TerminalApplication
from .. import __version__


class PiWheelsSlave(TerminalApplication):
    def __init__(self):
        super().__init__(__version__)
        self.parser.add_argument(
            '-m', '--master', default=os.environ.get('PW_MASTER', 'localhost'),
            help='The IP address or hostname of the master server; defaults to '
            ' the value of the PW_MASTER env-var (%(default)s)')
        self.parser.add_argument(
            '-i', '--id', '--slave-id', default=os.environ.get('PW_SLAVE', '1'),
            help='The identifier of the slave; defaults to the value of the '
            'PW_SLAVE env-var (%(default)s)')

    def main(self, args):
        print('PiWheels Slave version {}'.format(__version__))
        self.slave_id = args.id
        self.ctx = zmq.Context()
        self.build_queue = ctx.socket(zmq.PULL)
        self.build_queue.hwm = 10 # only allow 10 jobs to build up in queue
        self.build_queue.ipv6 = True
        self.build_queue.connect('tcp://{args.master}:5555'.format(args=args))
        self.log_queue = ctx.socket(zmq.PUSH)
        self.log_queue.ipv6 = True
        self.log_queue.connect('tcp://{args.master}:5556'.format(args=args))
        self.ctrl_queue = ctx.socket(zmq.SUB)
        self.ctrl_queue.ipv6 = True
        self.ctrl_queue.connect('tcp://{args.master}:5557'.format(args=args))
        self.run = Event()
        self.terminate = Event()
        self.builds = {} # map of filename->build
        self.send_queue = []
        self.ctrl_thread = Thread(self.ctrl_run, daemon=True)
        self.build_thread = Thread(self.build_run, daemon=True)
        self.files_thread = Thread(self.files_run, daemon=True)
        self.ctrl_thread.start()
        self.build_thread.start()
        self.files_thread.start()
        try:
            self.terminate.wait()
        finally:
            self.close()

    def close(self):
        self.run.clear()
        self.terminate.set()
        self.files_thread.join()
        self.ctrl_thread.join()
        self.build_thread.join()
        self.log_queue.close()
        self.build_queue.close()
        self.ctrl_queue.close()
        self.ctx.term()

    def ctrl_run(self):
        self.run.set()
        while not self.terminate.wait(0):
            events = self.ctrl_queue.poll(1000)
            if events:
                target_id, cmd, *args = self.ctrl_queue.recv_json()
                if target_id in (self.slave_id, '*'):
                    if cmd == 'QUIT':
                        logging.warning('Terminating')
                        self.run.clear()
                        self.terminate.set()
                    elif cmd == 'PAUSE':
                        logging.warning('Pausing')
                        self.run.clear()
                    elif cmd == 'RESUME':
                        logging.warning('Resuming')
                        self.run.set()
                    elif cmd == 'PING':
                        self.log_queue.send_json((self.slave_id, 'PONG'))
                    elif cmd == 'SEND':
                        filename, = args
                        try:
                            build = self.builds.pop(filename)
                        except KeyError:
                            if not filename in [build.filename for build in self.send_queue]:
                                self.log_queue.send_json((self.slave_id, 'LOST', filename))
                        else:
                            self.send_queue.append(build)


    def build_run(self):
        while not self.terminate.wait(0):
            if not self.run.wait(1):
                continue
            if self.build_queue.poll(1000):
                package, version = build_queue.recv_json()
                logging.info('building package %s version %s', package, version)
                builder = PiWheelsBuilder(package, version)
                builder.build_wheel()
                if builder.status:
                    self.builds[builder.filename] = builder
                self.log_queue.send_json((
                    self.slave_id,
                    'BUILT',
                    builder.package,
                    builder.version,
                    builder.status,
                    builder.output,
                    builder.filename,
                    builder.filesize,
                    builder.duration,
                    builder.package_version_tag,
                    builder.py_version_tag,
                    builder.abi_tag,
                    builder.platform_tag,
                ))
            else:
                logging.info('Idle: polling master for more jobs')
                log_queue.send_json((self.slave_id, 'IDLE'))

    def files_run(self):
        while not self.terminate.wait(1):
            pass


main = PiWheelsSlave()
