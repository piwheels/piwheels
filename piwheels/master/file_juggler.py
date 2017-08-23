import logging

import zmq

from .tasks import Task, TaskQuit
from .states import TransferState


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
    def __init__(self, **config)
        super().__init__(**config)
        self.file_queue = self.ctx.socket(zmq.ROUTER)
        self.file_queue.ipv6 = True
        self.file_queue.hwm = TransferState.pipeline_size * 50
        self.file_queue.bind(config['file_queue'])

    def close(self):
        self.file_queue.close()
        super().close()

    def run(self):
        try:
            while True:
                self.handle_control()
                if not self.file_queue.poll(1000):
                    continue
                address, msg, *args = self.file_queue.recv_multipart()

                try:
                    transfer = self.transfers[address]

                except KeyError:
                    if msg == b'CHUNK':
                        logging.debug('Ignoring redundant CHUNK from prior transfer')
                        continue
                    elif msg != b'HELLO':
                        logging.error('Invalid start transfer from slave: %s', msg)
                        continue
                    try:
                        slave_id = int(args[0])
                        # XXX Yucky; in fact the whole "transfer state generated
                        # by the slave thread then passed to the transfer
                        # thread" is crap. Would be slightly nicer to ... ?
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
                            self.file_queue.send_multipart([address, b'DONE'])
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
                    self.file_queue.send_multipart([
                        address, b'FETCH',
                        str(fetch_range.start).encode('ascii'),
                        str(len(fetch_range)).encode('ascii')
                    ])
                    fetch_range = transfer.fetch()
        except TaskQuit:
            pass
