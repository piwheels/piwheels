import os
import math
import logging
import tempfile
import hashlib
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
from .ranges import exclude, intersect
from ..terminal import TerminalApplication
from .. import __version__


BuildState = namedtuple('BuildState', (
    'slave_id',
    'package',
    'version',
    'status',
    'output',
    'filename',
    'filesize',
    'filehash',
    'duration',
    'package_version_tag',
    'py_version_tag',
    'abi_tag',
    'platform_tag',
))


class SlaveState:
    counter = 0
    status_queue = None

    def __init__(self):
        SlaveState.counter += 1
        self._slave_id = SlaveState.counter
        self._last_seen = None
        self._request = None
        self._reply = None
        self._build = None
        self._transfer = None

    @property
    def slave_id(self):
        return self._slave_id

    @property
    def last_seen(self):
        return self._last_seen

    @property
    def build(self):
        return self._build

    @property
    def transfer(self):
        return self._transfer

    @property
    def request(self):
        return self._request

    @request.setter
    def request(self, value):
        self._last_seen = datetime.utcnow()
        self._request = value
        if value[0] == 'BUILT':
            self._build = BuildState(self._slave_id, *value[1:])
            SlaveState.status_queue.send_json(
                [self._slave_id, self._last_seen.timestamp()] + value)

    @property
    def reply(self):
        return self._reply

    @reply.setter
    def reply(self, value):
        self._reply = value
        if value[0] == 'SEND':
            self._transfer = TransferState(self._build.filesize)
        elif value[0] == 'DONE':
            self._build = None
            self._transfer = None


class TransferState:
    chunk_size = 65536
    pipeline_size = 10
    output_path = Path('.')

    def __init__(self, filesize):
        self._file = tempfile.NamedTemporaryFile(
            dir=str(self.output_path), delete=False)
        self._file.seek(filesize)
        self._file.truncate()
        # XXX Calculate max pipeline required from filesize
        self._credit = min(self.pipeline_size, math.ceil(filesize / self.chunk_size))
        # _offset is the position that we will next return when the fetch()
        # method is called (or rather, it's the minimum position we'll return)
        # whilst _map is a sorted list of ranges indicating which bytes of the
        # file we have yet to received; this is manipulated by chunk()
        self._offset = 0
        self._map = [range(filesize)]

    @property
    def done(self):
        return not self._map

    def fetch(self):
        if self._credit:
            self._credit -= 1
            assert self._credit >= 0
            fetch_range = range(self._offset, self._offset + self.chunk_size)
            while True:
                for map_range in self._map:
                    result = intersect(map_range, fetch_range)
                    if result:
                        self._offset = result.stop
                        return result
                    elif map_range.start > fetch_range.start:
                        fetch_range = range(map_range.start, map_range.start + self.chunk_size)
                try:
                    fetch_range = range(self._map[0].start, self._map[0].start + self.chunk_size)
                except IndexError:
                    return None

    def chunk(self, offset, data):
        self._file.seek(offset)
        self._file.write(data)
        self._map = list(exclude(self._map, range(offset, offset + len(data))))
        if not self._map:
            self._credit = 0
        else:
            self._credit += 1

    def reset_credit(self):
        if self._credit == 0:
            self._credit = self.pipeline_size
        else:
            logging.warning('Transfer still has credit; no need for reset')

    def verify(self, build):
        self._file.seek(0)
        m = hashlib.md5()
        while True:
            buf = self._file.read(self.chunk_size)
            if buf:
                m.update(buf)
            else:
                break
        self._file.close()
        p = Path(self._file.name)
        if m.hexdigest().lower() == build.filehash:
            p.chmod(0o644)
            p.rename(p.with_name(build.filename))
            return True
        else:
            p.unlink()
            return False


class PiWheelsMaster(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, __doc__)
        self.parser.add_argument('-d', '--dsn', default='postgres:///piwheels',
                                 help='The SQLAlchemy DSN used to connect to '
                                 'the piwheels database (default: %(default)s)')
        self.parser.add_argument('-o', '--output', default=Path('~/www').expanduser(),
                                 help='The path to write wheels into '
                                 '(default: %(default)s)')

    def main(self, args):
        logging.info('PiWheels Master version {}'.format(__version__))
        self.slaves = {}
        self.transfers = {}
        db_engine = create_engine(args.dsn)
        output_path = Path(args.output)
        try:
            output_path.mkdir()
        except FileExistsError:
            pass
        ctx = zmq.Context.instance()
        ctrl_queue = ctx.socket(zmq.PUB)
        ctrl_queue.hwm = 1
        ctrl_queue.bind('inproc://control')
        status_queue = ctx.socket(zmq.PUB)
        status_queue.hwm = 10
        status_queue.bind('ipc:///tmp/piw-status')
        SlaveState.status_queue = status_queue
        TransferState.output_path = output_path
        packages_thread = Thread(target=self.web_scraper, args=(db_engine,))
        builds_thread = Thread(target=self.queue_filler, args=(db_engine,))
        files_thread = Thread(target=self.build_catcher)
        slave_thread = Thread(target=self.slave_driver, args=(db_engine,))
        packages_thread.start()
        builds_thread.start()
        files_thread.start()
        slave_thread.start()
        try:
            pause()
        except KeyboardInterrupt:
            logging.warning('Shutting down at user request')
        finally:
            ctrl_queue.send_string('QUIT')
            slave_thread.join()
            files_thread.join()
            builds_thread.join()
            packages_thread.join()
            SlaveState.status_queue = None
            ctrl_queue.close()
            status_queue.close()
            ctx.term()

    def web_scraper(self, db_engine):
        ctx = zmq.Context.instance()
        ctrl_queue = ctx.socket(zmq.SUB)
        ctrl_queue.connect('inproc://control')
        ctrl_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        try:
            with PiWheelsDatabase(db_engine) as db:
                while not ctrl_queue.poll(1000):
                    db.update_package_list()
                    for package in db.get_all_packages():
                        db.update_package_version_list(package)
                        if ctrl_queue.poll(0):
                            break
        finally:
            ctrl_queue.close()

    def queue_filler(self, db_engine):
        ctx = zmq.Context.instance()
        ctrl_queue = ctx.socket(zmq.SUB)
        ctrl_queue.connect('inproc://control')
        ctrl_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        build_queue = ctx.socket(zmq.PUSH)
        build_queue.hwm = 10
        build_queue.bind('inproc://builds')
        try:
            with PiWheelsDatabase(db_engine) as db:
                while not ctrl_queue.poll(0):
                    for package, version in db.get_build_queue():
                        while not ctrl_queue.poll(0):
                            if build_queue.poll(1000, zmq.POLLOUT):
                                build_queue.send_json((package, version))
                                break
                        if ctrl_queue.poll(0):
                            break
        finally:
            build_queue.close()
            ctrl_queue.close()

    def slave_driver(self, db_engine):
        ctx = zmq.Context.instance()
        ctrl_queue = ctx.socket(zmq.SUB)
        ctrl_queue.connect('inproc://control')
        ctrl_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        slave_queue = ctx.socket(zmq.ROUTER)
        slave_queue.ipv6 = True
        slave_queue.bind('tcp://*:5555')
        build_queue = ctx.socket(zmq.PULL)
        build_queue.hwm = 10
        build_queue.connect('inproc://builds')
        try:
            with PiWheelsDatabase(db_engine) as db:
                while not ctrl_queue.poll(0):
                    if not slave_queue.poll(1000):
                        continue
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
                    slave.request = [msg] + args

                    if msg == 'HELLO':
                        logging.info('New slave: %d', slave.slave_id)
                        reply = ['HELLO', slave.slave_id]

                    elif msg == 'BYE':
                        logging.warning('Slave shutdown: %d', slave.slave_id)
                        del self.slaves[address]
                        reply = []

                    elif msg == 'IDLE':
                        events = build_queue.poll(0)
                        if events:
                            package, version = build_queue.recv_json()
                            reply = ['BUILD', package, version]
                        else:
                            reply = ['SLEEP']
                        # XXX When do we send BYE?

                    elif msg == 'BUILT':
                        db.log_build(slave.build)
                        if slave.build.status:
                            reply = ['SEND']
                        else:
                            reply = ['DONE']

                    elif msg == 'SENT':
                        if not slave.transfer:
                            logging.error('No transfer to verify from slave')
                            continue
                        if slave.transfer.verify(slave.build):
                            reply = ['DONE']
                        else:
                            reply = ['SEND']

                    else:
                        logging.error('Invalid message from existing slave: %s', msg)

                    slave.reply = reply
                    if reply:
                        slave_queue.send_multipart([
                            address,
                            empty,
                            jsonapi.dumps(reply)
                        ])
        finally:
            build_queue.close()
            slave_queue.close()
            ctrl_queue.close()

    def build_catcher(self):
        ctx = zmq.Context.instance()
        ctrl_queue = ctx.socket(zmq.SUB)
        ctrl_queue.connect('inproc://control')
        ctrl_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        file_queue = ctx.socket(zmq.ROUTER)
        file_queue.ipv6 = True
        file_queue.hwm = TransferState.pipeline_size * 10
        file_queue.bind('tcp://*:5556')
        try:
            while not ctrl_queue.poll(0):
                if not file_queue.poll(1000):
                    continue
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
                    transfer = slave.transfer
                    if transfer is None:
                        logging.error('No active transfer for slave: %d', slave_id)
                    self.transfers[address] = transfer

                else:
                    if msg == b'CHUNK':
                        transfer.chunk(int(args[0].decode('ascii')), args[1])
                        if transfer.done:
                            file_queue.send_multipart([address, b'DONE'])
                            del self.transfers[address]
                            continue

                    elif msg == b'HELLO':
                        # This only happens if we've dropped a *lot* of packets,
                        # and the slave's timed out waiting for another FETCH.
                        # In this case reset the amount of "credit" on the
                        # transfer so it can start fetching again
                        # XXX Should check slave ID reported in HELLO matches
                        # the slave retrieved from the cache
                        transfer.reset_credit()

                    else:
                        logging.error('Invalid chunk header from slave: %s', msg)
                        # XXX Delete the transfer object?
                        # XXX Remove transfer from slave?

                fetch_range = transfer.fetch()
                while fetch_range:
                    file_queue.send_multipart([
                        address, b'FETCH',
                        str(fetch_range.start).encode('ascii'),
                        str(len(fetch_range)).encode('ascii')
                    ])
                    fetch_range = transfer.fetch()
        finally:
            file_queue.close()
            ctrl_queue.close()


main = PiWheelsMaster()
