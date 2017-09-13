import os
import logging
from pathlib import Path

import zmq

from .tasks import Task, TaskQuit
from .states import FileState, TransferState


logger = logging.getLogger('master.file_juggler')


class TransferError(Exception):
    pass


class TransferIgnoreChunk(TransferError):
    pass


class TransferDone(TransferError):
    pass


class FileJuggler(Task):
    """
    This task handles file transfers from the build slaves. The specifics of the
    file transfer protocol are best understood from the implementation of the
    :class:`FileState` class.

    However, to detail how a file transfer begins: when a build slave has
    successfully completed a build it informs the master via the
    :class:`SlaveDriver` task. That task replies with a "SEND" instruction to
    the slave (including a filename). The slave then initiates the transfer with
    a "HELLO" message to this task. Once transfers are complete the slave sends
    a "SENT" message to the :meth:`slave_driver` task which verifies the
    transfer and either retries it (when verification fails) or sends back
    "DONE" indicating the slave can wipe the source file.
    """
    def __init__(self, **config):
        super().__init__(**config)
        self.output_path = Path(config['output_path'])
        self.file_queue = self.ctx.socket(zmq.ROUTER)
        self.file_queue.ipv6 = True
        self.file_queue.hwm = TransferState.pipeline_size * 50
        self.file_queue.bind(config['file_queue'])
        self.fs_queue = self.ctx.socket(zmq.REP)
        self.fs_queue.hwm = 1
        self.fs_queue.bind(config['fs_queue'])
        self.index_queue = self.ctx.socket(zmq.PUSH)
        self.index_queue.hwm = 10
        self.index_queue.connect(config['index_queue'])
        TransferState.output_path = self.output_path
        self.transfers = {}

    def close(self):
        super().close()
        self.file_queue.close()
        self.fs_queue.close()
        self.index_queue.close()
        logger.info('closed')

    def run(self):
        logger.info('starting')
        poller = zmq.Poller()
        try:
            poller.register(self.control_queue, zmq.POLLIN)
            poller.register(self.file_queue, zmq.POLLIN)
            poller.register(self.fs_queue, zmq.POLLIN)
            while True:
                socks = dict(poller.poll(1000))
                if self.control_queue in socks:
                    self.handle_control()
                if self.fs_queue in socks:
                    self.handle_fs_request()
                if self.file_queue in socks:
                    try:
                        self.handle_file()
                    except TransferIgnoreChunk as e:
                        logger.debug(str(e))
                    except TransferDone as e:
                        logger.info(str(e))
                    except TransferError as e:
                        logger.error(str(e))
        except TaskQuit:
            pass

    def handle_fs_request(self):
        msg, *args = self.fs_queue.recv_json()
        try:
            handler = getattr(self, 'do_%s' % msg)
            result = handler(*args)
        except Exception as e:
            logger.error('error handling fs request: %s', msg)
            # REP *must* send a reply even when stuff goes wrong
            # otherwise the send/recv cycle that REQ/REP depends
            # upon breaks
            self.fs_queue.send_json(['ERR', str(e)])
        else:
            self.fs_queue.send_json(['OK', result])

    def do_EXPECT(self, slave_id, *file_state):
        file_state = FileState(*file_state)
        self.transfers[slave_id] = TransferState(file_state)

    def do_VERIFY(self, slave_id, package):
        transfer = self.transfers[slave_id]
        try:
            transfer.verify()
        except IOError as e:
            transfer.rollback()
            raise
        else:
            transfer.commit(package)

    def do_STATVFS(self):
        return list(os.statvfs(str(self.output_path)))

    def handle_file(self):
        address, msg, *args = self.file_queue.recv_multipart()

        try:
            transfer = self.transfers[address]
        except KeyError:
            transfer = self.new_transfer(msg, *args)
            self.transfers[address] = transfer
        else:
            try:
                self.current_transfer(transfer, msg, *args)
            except TransferDone:
                self.file_queue.send_multipart([address, b'DONE'])
                self.index_queue.send_json(['PKG', slave.build.package])
                del self.transfers[address]
                raise

        fetch_range = transfer.fetch()
        while fetch_range:
            self.file_queue.send_multipart([
                address, b'FETCH',
                str(fetch_range.start).encode('ascii'),
                str(len(fetch_range)).encode('ascii')
            ])
            fetch_range = transfer.fetch()

    def new_transfer(self, msg, *args):
        if msg == b'CHUNK':
            raise TransferIgnoreChunk('Ignoring redundant CHUNK from prior transfer')
        elif msg != b'HELLO':
            raise TransferError('Invalid start transfer from slave: %s' % msg)
        try:
            slave_id = int(args[0])
            transfer = TransferState(self.incoming.pop(slave_id))
        except ValueError:
            raise TransferError('Invalid slave id: %s' % args[0])
        except KeyError:
            raise TransferError('No active transfer for slave: %d' % slave_id)
        return transfer

    def current_transfer(self, transfer, msg, *args):
        if msg == b'CHUNK':
            transfer.chunk(int(args[0].decode('ascii')), args[1])
            if transfer.done:
                raise TransferDone('File transfer complete')

        elif msg == b'HELLO':
            # This only happens if we've dropped a *lot* of packets,
            # and the slave's timed out waiting for another FETCH.
            # In this case reset the amount of "credit" on the
            # transfer so it can start fetching again
            # XXX Should check slave ID reported in HELLO matches
            # the slave retrieved from the cache
            transfer.reset_credit()

        else:
            raise TransferError('Invalid chunk header from slave: %s' % msg)
            # XXX Delete the transfer object?
            # XXX Remove transfer from slave?


class FsClient:
    def __init__(self, **config):
        self.ctx = zmq.Context.instance()
        self.fs_queue = self.ctx.socket(zmq.REQ)
        self.fs_queue.hwm = 1
        self.fs_queue.connect(config['fs_queue'])

    def close(self):
        self.fs_queue.close()

    def _execute(self, msg):
        self.fs_queue.send_json(msg)
        status, result = self.fs_queue.recv_json()
        if status == 'OK':
            if result:
                return result
        else:
            raise IOError(result)

    def expect(self, file_state):
        self._execute(['EXPECT', file_state])

    def verify(self, build_state):
        try:
            self._execute(['VERIFY', build_state.slave_id, build_state.package])
        except IOError:
            return False
        else:
            return True

    def statvfs(self):
        return os.statvfs_result(self._execute(['STATVFS']))
