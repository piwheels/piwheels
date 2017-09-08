import logging

import zmq

from .tasks import Task, TaskQuit
from .states import TransferState


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
        self.file_queue = self.ctx.socket(zmq.ROUTER)
        self.file_queue.ipv6 = True
        self.file_queue.hwm = TransferState.pipeline_size * 50
        self.file_queue.bind(config['file_queue'])
        self.fs_queue = self.ctx.socket(zmq.REP)
        self.fs_queue.hwm = 1
        self.fs_queue.bind(config['fs_queue'])
        self.transfers = {}
        self.incoming = {}

    def close(self):
        self.file_queue.close()
        super().close()

    def run(self):
        poller = zmq.Poller()
        try:
            poller.register(self.control_queue, zmq.POLLIN)
            poller.register(self.file_queue, zmq.POLLIN)
            poller.register(self.fs_queue, zmq.POLLIN)
            while True:
                socks = poller.poll(1000)
                if self.control_queue in socks:
                    self.handle_control()
                if self.fs_queue in socks:
                    self.handle_fs_request()
                if self.file_queue in socks:
                    try:
                        self.handle_file()
                    except TransferIgnoreChunk as e:
                        logging.debug(str(e))
                    except TransferDone:
                        logging.info(str(e))
                    except TransferError as e:
                        logging.error(str(e))
        except TaskQuit:
            pass

    def handle_fs_request(self):
        msg, *args = self.fs_queue.recv_json()
        if msg == 'INCOMING':
            pass
        elif msg == 'VERIFY':
            pass
        elif msg == 'STATVFS':
            pass
        else:
            logging.error('Invalid fs request: %s', msg)

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


class FileClient:
    def __init__(self, **config):
        pass
