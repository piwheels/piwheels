# The piwheels project
#   Copyright (c) 2017 Ben Nuttall <https://github.com/bennuttall>
#   Copyright (c) 2017 Dave Jones <dave@waveform.org.uk>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
Defines the :class:`FileJuggler` task and the :class:`FsClient` RPC class
for interacting with it.

.. autoexception:: TransferError

.. autoexception:: TransferIgnoreChunk

.. autoexception:: TransferDone

.. autoclass:: FileJuggler
    :members:

.. autoclass:: FsClient
    :members:
"""

from pathlib import Path

from .. import transport, protocols, tasks, info
from ..states import TransferState, FileState


class TransferError(Exception):
    """
    Base class for errors raised during a file transfer.
    """


class TransferIgnoreChunk(TransferError):
    """
    Exception raised when a build slave sends CHUNK instead of HELLO as the
    first message (see :meth:`FileJuggler.new_transfer`).
    """


class TransferDone(TransferError):
    """
    Exception raised when a transfer is complete. It may seem a little odd to
    use an exception for this, but it is "exceptional" behaviour to terminate
    the file transfer.
    """


class FileJuggler(tasks.NonStopTask):
    """
    This task handles file transfers from the build slaves. The specifics of
    the file transfer protocol are best understood from the implementation of
    the :class:`~.states.FileState` class.

    However, to detail how a file transfer begins: when a build slave has
    successfully completed a build it informs the master via the
    :class:`~.slave_driver.SlaveDriver` task. That task replies with a "SEND"
    instruction to the slave (including a filename). The slave then initiates
    the transfer with a "HELLO" message to this task. Once transfers are
    complete the slave sends a "SENT" message to the
    :class:`~.slave_driver.SlaveDriver` task which verifies the transfer and
    either retries it (when verification fails) or sends back "DONE" indicating
    the slave can wipe the source file.
    """
    name = 'master.file_juggler'

    def __init__(self, config):
        super().__init__(config)
        self.output_path = Path(config.output_path)
        TransferState.output_path = self.output_path
        file_queue = self.socket(
            transport.ROUTER, protocol=protocols.file_juggler_files)
        file_queue.hwm = TransferState.pipeline_size * 50
        file_queue.bind(config.file_queue)
        fs_queue = self.socket(
            transport.REP, protocol=protocols.file_juggler_fs)
        fs_queue.hwm = 10
        fs_queue.bind(config.fs_queue)
        self.stats_queue = self.socket(
            transport.PUSH, protocol=reversed(protocols.big_brother))
        self.stats_queue.hwm = 10
        self.stats_queue.connect(config.stats_queue)
        self.register(file_queue, self.handle_file)
        self.register(fs_queue, self.handle_fs_request)
        self.pending = {}   # keyed by slave_id
        self.active = {}    # keyed by slave address
        self.complete = {}  # keyed by slave_id

    def once(self):
        self.stats_queue.send_msg(
            'STATFS', info.get_disk_stats(str(self.output_path)))

    def handle_fs_request(self, queue):
        """
        Handle incoming messages from :class:`FsClient` instances.
        """
        try:
            msg, data = queue.recv_msg()
        except IOError as e:
            self.logger.error(str(e))
            queue.send_msg('ERROR', str(e))
        else:
            try:
                handler = {
                    'EXPECT': self.do_expect,
                    'VERIFY': self.do_verify,
                }[msg]
                result = handler(*data)
            except Exception as exc:
                self.logger.error('error handling fs request: %s', msg)
                queue.send_msg('ERROR', str(exc))
            else:
                queue.send_msg('OK', result)

    def do_expect(self, slave_id, file_state):
        """
        Message sent by :class:`FsClient` to inform file juggler that a build
        slave is about to start a file transfer. The message includes the full
        :class:`~.states.FileState`. The state is stored in the ``pending``
        map.

        :param int slave_id:
            The identity of the build slave about to begin the transfer.

        :param list file_state:
            The details of the file to be transferred including the expected
            hash.
        """
        file_state = FileState.from_message(file_state)
        self.pending[slave_id] = TransferState(slave_id, file_state)
        self.logger.info('expecting transfer: %s', file_state.filename)

    def do_verify(self, slave_id, package):
        """
        Message sent by :class:`FsClient` to request that juggler verify a file
        transfer against the expected hash and, if it matches, rename the file
        into its final location.

        :param int slave_id:
            The identity of the build slave that sent the file.

        :param str package:
            The name of the package that the file is to be committed to, if
            valid.
        """
        transfer = self.complete.pop(slave_id)
        try:
            transfer.verify()
        except IOError:
            transfer.rollback()
            self.logger.warning('verification failed: %s',
                                transfer.file_state.filename)
            raise
        else:
            transfer.commit(package)
            self.logger.info('verified: %s', transfer.file_state.filename)
            self.stats_queue.send_msg(
                'STATFS', info.get_disk_stats(str(self.output_path)))

    def handle_file(self, queue):
        """
        Handle incoming file-transfer messages from build slaves.

        The file transfer protocol is in some ways very simple (see the chart
        in the :doc:`slaves` chapter for an overview of the message sequence)
        and in some ways rather complex (read the ZeroMQ guide chapter on file
        transfers for more detail on why multiple messages must be allowed in
        flight simultaneously).

        The "normal" state for a file transfer is to be requesting and
        receiving chunks. Anything else, including redundant re-sends, and
        transfer completion is handled as an exceptional case.
        """
        address, msg, *args = queue.recv_multipart()
        try:
            transfer = None
            try:
                transfer = self.active[address]
            except KeyError:
                transfer = self.new_transfer(msg, *args)
                self.active[address] = transfer
            else:
                self.current_transfer(transfer, msg, *args)
        except TransferDone as exc:
            self.logger.info(str(exc))
            del self.active[address]
            self.complete[transfer.slave_id] = transfer
            queue.send_multipart([address, b'DONE'])
            return
        except TransferIgnoreChunk as exc:
            self.logger.debug('ignored chunk: %s', str(exc))
            return
        except TransferError as exc:
            self.logger.exception('transfer error')
            # XXX Delete the transfer object?
            if transfer is None:
                return
            # XXX Remove transfer from slave?

        fetch_range = transfer.fetch()
        while fetch_range:
            queue.send_multipart([
                address, b'FETCH',
                str(fetch_range.start).encode('ascii'),
                str(len(fetch_range)).encode('ascii')
            ])
            fetch_range = transfer.fetch()

    def new_transfer(self, msg, *args):
        r"""
        Called for messages initiating a new file transfer.

        The first message must be HELLO along with the id of the slave starting
        the transfer. The metadata for the transfer will be looked up in the
        ``pending`` list (which is written to by :meth:`do_expect`).

        :param str msg:
            The message sent to start the transfer (must be "HELLO")

        :param \*args:
            All additional arguments (expected to be an integer slave id).
        """
        if msg == b'CHUNK':
            raise TransferIgnoreChunk('ignoring redundant CHUNK from prior '
                                      'transfer')
        elif msg != b'HELLO':
            raise TransferError('invalid start transfer from slave: %s' % msg)
        try:
            slave_id = int(args[0])
            transfer = self.pending.pop(slave_id)
        except ValueError:
            raise TransferError('invalid slave id: %s' % args[0])
        except KeyError:
            raise TransferError('unexpected transfer from slave: %d' % slave_id)
        return transfer

    def current_transfer(self, transfer, msg, *args):
        r"""
        Called for messages associated with an existing file transfer.

        Usually this is "CHUNK" indicating another chunk of data. Rarely, it
        can be "HELLO" if the master has fallen silent and dropped tons of
        packets.

        :param TransferState transfer:
            The object representing the state of the transfer.

        :param str msg:
            The message sent during the transfer.

        :param \*args:
            All additional arguments; for "CHUNK" the first must be the file
            offset and the second the data to write to that offset.
        """
        # pylint: disable=no-self-use
        if msg == b'CHUNK':
            transfer.chunk(int(args[0].decode('ascii')), args[1])
            if transfer.done:
                raise TransferDone('transfer complete: %s' %
                                   transfer.file_state.filename)
        else:
            # This only happens if there's either a corrupted package, or we've
            # dropped a *lot* of packets, and the slave's timed out waiting for
            # another FETCH. In either case reset the amount of "credit" on the
            # transfer so it can start fetching again
            transfer.reset_credit()
            # XXX Should check slave ID reported in HELLO matches the slave
            # retrieved from the cache
            if msg != b'HELLO':
                raise TransferError(
                    'invalid chunk header from slave: %s' % msg)


class FsClient:
    """
    RPC client class for talking to :class:`FileJuggler`.
    """
    def __init__(self, config, logger=None):
        self.ctx = transport.Context()
        self.fs_queue = self.ctx.socket(
            transport.REQ, protocol=reversed(protocols.file_juggler_fs),
            logger=logger)
        self.fs_queue.hwm = 10
        self.fs_queue.connect(config.fs_queue)

    def close(self):
        self.fs_queue.close()

    def _execute(self, msg, data=protocols.NoData):
        # If sending blocks this either means we're shutting down, or
        # something's gone horribly wrong (either way, raising EAGAIN is fine)
        self.fs_queue.send_msg(msg, data, flags=transport.NOBLOCK)
        status, result = self.fs_queue.recv_msg()
        if status == 'OK':
            return result
        else:
            raise IOError(result)

    def expect(self, slave_id, file_state):
        """
        See :meth:`FileJuggler.do_expect`.
        """
        self._execute('EXPECT', [slave_id, file_state.as_message()])

    def verify(self, slave_id, package):
        """
        See :meth:`FileJuggler.do_verify`.
        """
        try:
            self._execute('VERIFY', [slave_id, package])
        except IOError:
            return False
        else:
            return True
