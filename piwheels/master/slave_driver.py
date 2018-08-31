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
Defines the :class:`SlaveDriver` task; see class for more details.

.. autoclass:: SlaveDriver
    :members:
"""

import pickle
from datetime import datetime
from collections import defaultdict

import zmq

from .. import const
from .states import SlaveState, FileState
from .tasks import Task, TaskQuit
from .the_oracle import DbClient
from .file_juggler import FsClient


class SlaveDriver(Task):
    """
    This task handles interaction with the build slaves using the slave
    protocol. Interaction is driven by the slaves (i.e. the master doesn't
    *push* jobs, rather the slaves *request* a job and the master replies with
    the next (package, version) tuple from the internal "builds" queue).

    The task also incidentally interacts with several other queues: the
    internal "status" queue is sent details of every reply sent to a build
    slave (the :meth:`~.PiWheelsMaster.main_loop` method passes this
    information on to any listening monitors).  Also, the internal "indexes"
    queue is informed of any packages that need web page indexes re-building
    (as a result of a successful build).
    """
    # pylint: disable=too-many-instance-attributes
    name = 'master.slave_driver'

    def __init__(self, config):
        super().__init__(config)
        self.paused = False
        self.abi_queues = defaultdict(set)
        slave_queue = self.ctx.socket(zmq.ROUTER)
        slave_queue.ipv6 = True
        slave_queue.bind(config.slave_queue)
        self.register(slave_queue, self.handle_slave)
        builds_queue = self.ctx.socket(zmq.PULL)
        builds_queue.hwm = 10
        builds_queue.connect(config.builds_queue)
        self.register(builds_queue, self.handle_build)
        self.status_queue = self.ctx.socket(zmq.PUSH)
        self.status_queue.hwm = 10
        self.status_queue.connect(const.INT_STATUS_QUEUE)
        SlaveState.status_queue = self.status_queue
        self.index_queue = self.ctx.socket(zmq.PUSH)
        self.index_queue.hwm = 10
        self.index_queue.connect(config.index_queue)
        self.stats_queue = self.ctx.socket(zmq.PUSH)
        self.stats_queue.hwm = 10
        self.stats_queue.connect(config.stats_queue)
        self.db = DbClient(config)
        self.fs = FsClient(config)
        self.slaves = {}
        self.pypi_simple = config.pypi_simple

    def close(self):
        self.status_queue.close()
        self.index_queue.close()
        self.stats_queue.close()
        super().close()

    def list_slaves(self):
        """
        Additional task control method to trigger a "HELLO" message to the
        internal control queue. See :meth:`~.tasks.Task.quit` for more
        information.
        """
        self._ctrl(['HELLO'])

    def kill_slave(self, slave_id):
        """
        Additional task control method to trigger a "KILL" message to the
        internal control queue. See :meth:`~.tasks.Task.quit` for more
        information.
        """
        self._ctrl(['KILL', slave_id])

    def loop(self):
        """
        Remove slaves which have exceeded their timeout.
        """
        expired = {
            address: slave
            for address, slave in self.slaves.items()
            if slave.expired
        }
        for address, slave in expired.items():
            self.logger.warning('slave %d (%s): timed out',
                                slave.slave_id, slave.label)
            # Send a fake BYE message to the status queue so that listening
            # monitors know to remove the entry
            slave.reply = ['BYE']
            del self.slaves[address]

    def handle_control(self, queue):
        """
        Handle incoming requests to the internal control queue.

        Whilst the :class:`SlaveDriver` task is "pauseable", it can't simply
        stop responding to requests from build slaves. Instead, its pause is
        implemented as an internal flag. While paused it simply tells build
        slaves requesting a new job that none are currently available but
        otherwise continues servicing requests.

        It also understands a couple of extra control messages unique to it,
        specifically "KILL" to tell a build slave to terminate, and "HELLO"
        to cause all "HELLO" messages from build slaves to be replayed (for
        the benefit of a newly attached monitor process).
        """
        msg, *args = queue.recv_pyobj()
        if msg == 'QUIT':
            # TODO Kill all slaves...
            raise TaskQuit
        elif msg == 'PAUSE':
            self.paused = True
        elif msg == 'RESUME':
            self.paused = False
        elif msg == 'KILL':
            for slave in self.slaves.values():
                if slave.slave_id == args[0]:
                    slave.kill()
                    break
        elif msg == 'HELLO':
            for slave in self.slaves.values():
                slave.hello()

    def handle_build(self, queue):
        """
        Build up ABI-specific queues of package versions waiting to be built.
        The queues are limited to 1000 packages per ABI, and are kept as sets
        to eliminate duplicate versions that will inevitably appear due to
        re-runs of the build-queue query (in :class:`TheArchitect`) while
        queried versions are actively being built.
        """
        abi, package, version = queue.recv_pyobj()
        queue = self.abi_queues[abi]
        if len(queue) < 1000:
            queue.add((package, version))
        self.stats_queue.send_pyobj(['STATBQ', {
            abi: len(queue) for (abi, queue) in self.abi_queues.items()
        }])

    def handle_slave(self, queue):
        """
        Handle requests from build slaves.

        See the :doc:`slaves` chapter for an overview of the protocol for
        messages between build slaves and :class:`SlaveDriver`.  This method
        retrieves the message from the build slave, finds the associated
        :class:`~.states.SlaveState` and updates it with the message, then
        calls the appropriate message handler. The handler will be expected to
        return a reply (in the usual form of a list of strings) or ``None`` if
        no reply should be sent (e.g. for a final "BYE" message).
        """
        try:
            address, empty, msg = queue.recv_multipart()
        except ValueError:
            self.logger.error('invalid message structure from slave')
        else:
            msg, *args = pickle.loads(msg)
            self.logger.debug('RX: %s %r', msg, args)

            try:
                slave = self.slaves[address]
            except KeyError:
                if msg == 'HELLO':
                    slave = SlaveState(address, *args)
                else:
                    self.logger.error('invalid first message from slave: %s',
                                      msg)
                    return

            slave.request = [msg] + args
            try:
                handler = {
                    'HELLO': self.do_hello,
                    'BYE': self.do_bye,
                    'IDLE': self.do_idle,
                    'BUILT': self.do_built,
                    'SENT': self.do_sent,
                }[msg]
            except KeyError:
                self.logger.error(
                    'slave %d (%s): protocol error (%s)',
                    slave.slave_id, slave.label, msg)
            else:
                reply = handler(slave)
                if reply is not None:
                    slave.reply = reply
                    queue.send_multipart([address, empty, pickle.dumps(reply)])
                    self.logger.debug('TX: %r', reply)

    def do_hello(self, slave):
        """
        Handler for the build slave's initial "HELLO" message. This associates
        the specified *slave* state with the slave's address and returns
        "HELLO" with the master's id for the slave (the id communicated back
        simply for consistency of logging; administrators can correlate master
        log messages with slave log messages when both have the same id
        number; we can't use IP address for this as multiple slaves can run on
        one machine).

        :param SlaveState slave:
            The object representing the current status of the build slave.
        """
        self.logger.warning(
            'slave %d: hello (timeout=%s, abi=%s, platform=%s, label=%s)',
            slave.slave_id, slave.timeout, slave.native_abi,
            slave.native_platform, slave.label)
        self.slaves[slave.address] = slave
        return ['HELLO', slave.slave_id, self.pypi_simple]

    def do_bye(self, slave):
        """
        Handler for the build slave's final "BYE" message upon shutdown. This
        removes the associated state from the internal ``slaves`` dict.

        :param SlaveState slave:
            The object representing the current status of the build slave.
        """
        self.logger.warning('slave %d (%s): shutdown',
                            slave.slave_id, slave.label)
        # Send a fake BYE message to the status queue so that listening
        # monitors know to remove the entry
        slave.reply = ['BYE']
        del self.slaves[slave.address]
        return None

    def do_idle(self, slave):
        """
        Handler for the build slave's "IDLE" message (which is effectively the
        slave requesting work). If the master wants to terminate the slave,
        it sends back "BYE". If the build queue (for the slave's ABI) is empty
        or the task is currently paused, "SLEEP" is returned indicating the
        slave should wait a while and then try again.

        If a job can be retrieved from the (ABI specific) build queue, then
        a "BUILD" message is sent back with the required package and version.

        :param SlaveState slave:
            The object representing the current status of the build slave.
        """
        if slave.reply[0] not in ('HELLO', 'SLEEP', 'DONE'):
            self.logger.error(
                'slave %d (%s): protocol error (IDLE after %s)',
                slave.slave_id, slave.label, slave.reply[0])
            return ['BYE']
        elif slave.terminated:
            return ['BYE']
        elif self.paused:
            self.logger.info(
                'slave %d (%s): sleeping because master is paused',
                slave.slave_id, slave.label)
            return ['SLEEP']
        else:
            try:
                package, version = self.abi_queues[slave.native_abi].pop()
            except KeyError:
                pass
            else:
                if (package, version) not in self.active_builds():
                    self.logger.info(
                        'slave %d: build %s %s',
                        slave.slave_id, package, version)
                    return ['BUILD', package, version]
            self.logger.info(
                'slave %d (%s): sleeping because no builds',
                slave.slave_id, slave.label)
            return ['SLEEP']

    def do_built(self, slave):
        """
        Handler for the build slave's "BUILT" message, which is sent after an
        attempted package build succeeds or fails. The handler logs the result
        in the database and, if files have been generated by the build, informs
        the :class:`~.file_juggler.FileJuggler` task to expect a file transfer
        before sending "SEND" back to the build slave with the required
        filename.

        If no files were generated (e.g. in the case of a failed build, or a
        degenerate success), "DONE" is returned indicating that the build slave
        is free to discard all resources generated during the build and return
        to its idle state.
        """
        if slave.reply[0] != 'BUILD':
            self.logger.error(
                'slave %d (%s): protocol error (BUILD after %s)',
                slave.slave_id, slave.label, slave.reply[0])
            return ['BYE']
        else:
            build_armv6l_hack(slave.build)
            self.db.log_build(slave.build)
            if slave.build.status and not slave.build.transfers_done:
                self.logger.info('slave %d (%s): build succeeded',
                                 slave.slave_id, slave.label)
                self.fs.expect(slave.slave_id,
                               slave.build.files[slave.build.next_file])
                self.logger.info('slave %d (%s): send %s',
                                 slave.slave_id, slave.label,
                                 slave.build.next_file)
                return ['SEND', slave.build.next_file]
            else:
                self.logger.info('slave %d (%s): build failed',
                                 slave.slave_id, slave.label)
                self.index_queue.send_pyobj(['PKG', slave.build.package])
                return ['DONE']

    def do_sent(self, slave):
        """
        Handler for the build slave's "SENT" message indicating that it's
        finished sending the requested file to :class:`FileJuggler`. The
        :class:`FsClient` RPC mechanism is used to ask :class:`FileJuggler` to
        verify the transfer against the stored hash and, if this is successful,
        a message is sent to :class:`IndexScribe` to regenerate the package's
        index.

        If further files remain to be transferred, another "SEND" message is
        returned to the build slave. Otherwise, "DONE" is sent to free all
        build resources.

        If a transfer fails to verify, another "SEND" message with the same
        filename is returned to the build slave.
        """
        if slave.reply[0] != 'SEND':
            self.logger.error(
                'slave %d (%s): protocol error (SENT after %s)',
                slave.slave_id, slave.label, slave.reply[0])
            return ['BYE']
        elif self.fs.verify(slave.slave_id, slave.build.package):
            self.index_queue.send_pyobj(['PKG', slave.build.package])
            slave.build.files[slave.build.next_file].verified()
            self.logger.info(
                'slave %d (%s): verified transfer of %s',
                slave.slave_id, slave.label, slave.reply[1])
            if slave.build.transfers_done:
                return ['DONE']
            else:
                self.fs.expect(slave.slave_id,
                               slave.build.files[slave.build.next_file])
                self.logger.info('slave %d (%s): send %s',
                                 slave.slave_id, slave.label,
                                 slave.build.next_file)
                return ['SEND', slave.build.next_file]
        else:
            self.logger.info('slave %d (%s): send %s',
                             slave.slave_id, slave.label,
                             slave.build.next_file)
            return ['SEND', slave.build.next_file]

    def active_builds(self):
        """
        Generator method which yields all (package, version) tuples currently
        being built by build slaves.
        """
        for slave in self.slaves.values():
            if slave.reply is not None and slave.reply[0] == 'BUILD':
                if slave.last_seen + slave.timeout > datetime.utcnow():
                    yield (slave.reply[1], slave.reply[2])


def build_armv6l_hack(build):
    """
    A dirty hack for armv6l wheels; if the build contains any arch-specific
    wheels for armv7l, generate equivalent armv6l entries from them (with
    the transferred flag set to True as nothing actually needs transferring).
    """
    for file in list(build.files.values()):
        if file.platform_tag == 'linux_armv7l':
            arm7_name = file.filename
            arm6_name = arm7_name[:-16] + 'linux_armv6l.whl'
            if arm6_name not in build.files:
                build.files[arm6_name] = FileState(
                    arm6_name, file.filesize, file.filehash, file.package_tag,
                    file.package_version_tag, file.py_version_tag,
                    file.abi_tag, 'linux_armv6l', True)
