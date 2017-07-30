import io
import os
import cmd
import argparse
import locale
import logging
import tempfile
from datetime import datetime
from threading import Thread, Event
from collections import namedtuple
from signal import pause
from pathlib import Path

import zmq
from zmq.utils import jsonapi
from sqlalchemy import create_engine

from .cli import PiWheelsCmd
from .db import PiWheelsDatabase
from ..terminal import TerminalApplication
from .ranges import exclude, intersect
from .. import __version__


BuildState = namedtuple('BuildState', (
    'slave_id',
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
))


class SlaveState:
    counter = 0

    def __init__(self):
        PiWheelsSlave.counter += 1
        self._slave_id = PiWheelsSlave.counter
        self._last_seen = None
        self._last_request = None
        self._last_reply = None
        self._last_build = None

    @property
    def slave_id(self):
        return self._slave_id

    @property
    def last_seen(self):
        return self._last_seen

    @property
    def last_build(self):
        return self._last_build

    @property
    def last_request(self):
        return self._last_request

    @last_request.setter
    def last_request(self, value):
        self._last_seen = datetime.utcnow()
        self._last_request = value
        if value[0] == 'BUILT':
            self._last_build = BuildState(self._slave_id, *value[1:])

    @property
    def last_reply(self):
        return self._last_reply

    @last_reply.setter
    def last_reply(self, value):
        self._last_reply = value
        if value[0] == 'DONE':
            self._last_build = None


class TransferState:
    chunk_size = 65536

    def __init__(self, output_path, build):
        self._build = build
        self._file = tempfile.NamedTemporaryFile(dir=output_path)
        self._file.seek(build.filesize)
        self._file.truncate()
        # _offset is the position that we will next return when the fetch()
        # method is called (or rather, it's the minimum position we'll return)
        # whilst _map is a sorted list of ranges indicating which bytes of the
        # file we have yet to received; this is manipulated by chunk()
        self._offset = 0
        self._map = [range(build.filesize)]

    def fetch(self):
        fetch_range = range(self._offset, self._offset + self.chunk_size)
        while True:
            for map_range in self._map:
                result = intersect(map_range, fetch_range)
                if result:
                    self._offset = result.stop
                    return result
                elif map_range.start > fetch_range.start:
                    fetch_range = range(map_range.start, map_range.start + self.chunk_size)
            fetch_range = range(self._map[0].start, self._map[0].start + self.chunk_size)

    def chunk(self, offset, data):
        self._file.seek(offset)
        self._file.write(data)
        self._map = list(exclude(self._map, range(offset, offset + len(data))))

    def done(self):
        assert not self._map
        os.rename(self._file.name, self._build.filename)


class PiWheelsMaster(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, __doc__)
        self.parser.add_argument('-d', '--dsn', default='postgres:///piwheels',
                                 help='The SQLAlchemy DSN used to connect to '
                                 'the piwheels database (default: %(default)s)')
        self.parser.add_argument('-o', '--output', default='/var/www',
                                 help='The path to write wheels into '
                                 '(default: %(default)s')

    def main(self, args):
        self.slaves = {}
        self.transfers = {}
        db_engine = create_engine(args.dsn)
        output_path = Path(args.output)
        try:
            output_path.mkdir()
        except FileExistsError:
            pass
        packages_thread = Thread(target=web_scraper, args=(db_engine,))
        builds_thread = Thread(target=queue_filler, args=(db_engine,))
        slave_thread = Thread(target=slave_driver, args=(db_engine,))
        files_thread = Thread(target=build_catcher, args=(output_path,))
        packages_thread.start()
        builds_thread.start()
        job_router.start()
        file_handler.start()
        pause()

    def web_scraper(self, db_engine):
        with PiWheelsDatabase(self.db_engine) as db:
            while True:
                # XXX terminate via socket
                db.update_package_list()
                for package in db.get_all_packages():
                    db.update_package_version_list(package)

    def queue_filler(self, db_engine):
        ctx = zmq.Context.instance()
        build_queue = ctx.socket(zmq.PUSH)
        build_queue.bind('inproc://builds')
        try:
            with PiWheelsDatabase(self.db_engine) as db:
                while True:
                    # XXX terminate via socket
                    for package, version in db.get_build_queue():
                        build_queue.send_json((package, version))
        finally:
            build_queue.close()

    def slave_driver(self, db_engine):
        slave_counter = 0
        ctx = zmq.Context.instance()
        slave_queue = ctx.socket(zmq.ROUTER)
        slave_queue.ipv6 = True
        slave_queue.bind('tcp://*:5555')
        build_queue = ctx.socket(zmq.PULL)
        build_queue.connect('inproc://builds')
        try:
            with PiWheelsDatabase(self.db_engine) as db:
                while True:
                    # XXX terminate via socket
                    try:
                        address, empty, msg = slave_queue.recv_multipart()
                    except ValueError:
                        logging.error('Invalid message structure from slave')
                        continue
                    msg, *args = jsonapi.loads(msg)

                    try:
                        slave = self.slaves[address]
                    except KeyError:
                        if msg != 'HELLO':
                            logging.error('Invalid first message from slave: %s', msg)
                            continue
                        slave = SlaveState()
                        self.slaves[address] = slave
                    slave.last_request = [msg] + args

                    if msg == 'HELLO':
                        logging.info('New slave: %d', slave.slave_id)
                        reply = ['HELLO', slave.slave_id]

                    elif msg == 'IDLE':
                        events = build_queue.poll(0)
                        if events:
                            package, version = build_queue.recv_json()
                            reply = ['BUILD', package, version]
                        else:
                            reply = ['SLEEP']
                        # XXX When do we send BYE?

                    elif msg == 'BUILT':
                        db.log_build(slave.last_build)
                        if slave.last_build.status:
                            reply = ['SEND']
                        else:
                            reply = ['DONE']

                    elif msg == 'SENT':
                        if send_succeeded: # TODO
                            reply = ['DONE']
                        else:
                            reply = ['SEND']

                    else:
                        logging.error('Invalid message from existing slave: %s', msg)

                    slave.last_reply = reply
                    slave_queue.send_multipart([
                        address,
                        empty,
                        jsonapi.dumps(reply)
                    ])
        finally:
            build_queue.close()
            slave_queue.close()

    def build_catcher(self, output_path):
        ctx = zmq.Context.instance()
        file_queue = ctx.socket(zmq.ROUTER)
        file_queue.ipv6 = True
        file_queue.bind('tcp://*:5556')
        while True:
            # XXX terminate via socket
            address, msg, *args = file_queue.recv_multipart()
            try:
                transfer = self.transfers[address]
            except KeyError:
                if msg != b'HELLO':
                    logging.error('Invalid start transfer from slave: %s', msg)
                    continue
                try:
                    slave_id = int(args[0])
                    slave = [
                        slave for slave in self.slaves.values()
                        if slave.slave_id == slave_id
                    ][0]
                except ValueError:
                    logging.error('Invalid slave_id during start transfer: %s', args[0])
                    continue
                except IndexError:
                    logging.error('Unknown slave_id during start transfer: %d', slave_id)
                    continue
                transfer = TransferState(output_path, slave.last_build)
                self.transfers[address] = transfer
            else:
                if msg != b'CHUNK':
                    logging.error('Invalid chunk header from slave: %s', msg)
            file_queue.send_multipart([address] + transfer.fetch())


main = PiWheelsMaster()
