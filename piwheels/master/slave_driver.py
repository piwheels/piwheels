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

from datetime import datetime, timedelta, timezone

from .. import const, protocols, tasks, transport
from ..states import SlaveState, FileState
from .the_oracle import DbClient
from .file_juggler import FsClient


UTC = timezone.utc


class SlaveDriver(tasks.PausingTask):
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
        super().__init__(config, control_protocol=protocols.slave_driver_control)
        self.abi_queues = {}
        self.recent_builds = {}
        self.recent_deletes = set()
        slave_queue = self.socket(
            transport.ROUTER, protocol=protocols.slave_driver)
        slave_queue.bind(config.slave_queue)
        self.register(slave_queue, self.handle_slave)
        builds_queue = self.socket(
            transport.PULL, protocol=reversed(protocols.the_architect))
        builds_queue.hwm = 10
        builds_queue.bind(config.builds_queue)
        self.register(builds_queue, self.handle_build)
        self.status_queue = self.socket(
            transport.PUSH, protocol=protocols.monitor_stats)
        self.status_queue.hwm = 10
        self.status_queue.connect(const.INT_STATUS_QUEUE)
        SlaveState.status_queue = self.status_queue
        self.web_queue = self.socket(
            transport.REQ, protocol=reversed(protocols.the_scribe))
        self.web_queue.connect(config.web_queue)
        self.stats_queue = self.socket(
            transport.PUSH, protocol=reversed(protocols.big_brother))
        self.stats_queue.connect(config.stats_queue)
        delete_queue = self.socket(
            transport.REP, protocol=reversed(protocols.cloud_gazer))
        delete_queue.bind(const.SKIP_QUEUE)
        self.register(delete_queue, self.handle_delete)
        self.db = DbClient(config, self.logger)
        self.fs = FsClient(config, self.logger)
        self.slaves = {}
        self.pypi_simple = config.pypi_simple
        self.every(timedelta(seconds=10), self.remove_expired)

    def close(self):
        self.fs.close()
        self.db.close()
        SlaveState.status_queue = None
        super().close()

    def list_slaves(self):
        """
        Additional task control method to trigger a "HELLO" message to the
        internal control queue. See :meth:`~.tasks.Task.quit` for more
        information.
        """
        self._ctrl('HELLO')

    def kill_slave(self, slave_id):
        """
        Additional task control method to trigger a "KILL" message to the
        internal control queue. See :meth:`handle_control` for more
        information.
        """
        self._ctrl('KILL', slave_id)

    def sleep_slave(self, slave_id):
        """
        Additional task control method to trigger a "SLEEP" message to the
        internal control queue. See :meth:`handle_control` for more
        information.
        """
        self._ctrl('SLEEP', slave_id)

    def skip_slave(self, slave_id):
        """
        Additional task control method to trigger a "SKIP" message to the
        internal control queue. See :meth:`handle_control` for more
        information.
        """
        self._ctrl('SKIP', slave_id)

    def wake_slave(self, slave_id):
        """
        Additional task control method to trigger a "WAKE" message to the
        internal control queue. See :meth:`handle_control` for more
        information.
        """
        self._ctrl('WAKE', slave_id)

    def remove_expired(self):
        """
        Remove slaves which have exceeded their timeout.
        """
        expired = {
            address: slave
            for address, slave in self.slaves.items()
            if slave.expired
        }
        for address, slave in expired.items():
            if slave.reply[0] == 'BUILD':
                package, version = slave.reply[1]
                self.logger.warning(
                    'slave %d (%s): timed out while building %s %s for %s',
                    slave.slave_id, slave.label, package, version,
                    slave.native_abi)
            else:
                self.logger.warning(
                    'slave %d (%s): timed out during %s',
                    slave.slave_id, slave.label, slave.reply[0])
            # Send a fake DIE message to the status queue so that listening
            # monitors know to remove the entry
            slave.reply = ('DIE', None)
            del self.slaves[address]

    def handle_control(self, queue):
        """
        Handle incoming requests to the internal control queue.

        This class understands a couple of extra control messages unique to it,
        specifically "KILL" to tell a build slave to terminate, "SKIP" to tell
        a build slave to terminate its current build immmediately, and "HELLO"
        to cause all "HELLO" messages from build slaves to be replayed (for the
        benefit of a newly attached monitor process).
        """
        try:
            super().handle_control(queue)
        except tasks.TaskControl as ctrl:
            if ctrl.msg in ('KILL', 'SLEEP', 'SKIP', 'WAKE'):
                for slave in self.slaves.values():
                    if ctrl.data is None or slave.slave_id == ctrl.data:
                        {
                            'KILL':  slave.kill,
                            'SLEEP': slave.sleep,
                            'SKIP':  slave.skip,
                            'WAKE':  slave.wake,
                        }[ctrl.msg]()
            elif ctrl.msg == 'HELLO':
                for slave in self.slaves.values():
                    slave.hello()
            else:
                raise  # pragma: no cover

    def handle_build(self, queue):
        """
        Refresh the ABI-specific queues of package versions waiting to be
        built. The queues are limited to 1000 packages per ABI, and are kept as
        lists ordered by release date. When a message arrives from
        :class:`TheArchitect` it refreshes (replaces) all current queues. There
        is, however, still a duplication possibility as :class:`TheArchitect`
        doesn't know what packages are actively being built; this method
        handles filtering out such packages.

        Even if the active builds fail (because build slaves crash, or the
        network dies) this doesn't matter as a future re-run of the build
        queue query will return these packages again, and if no build slaves
        are actively working on them at that time they will then be retried.
        """
        try:
            msg, new_queues = queue.recv_msg()
        except IOError as e:
            self.logger.error(str(e))
        else:
            now = datetime.now(tz=UTC)
            # Prune expired entries from the recent_builds buffer and add empty
            # dicts for new ABIs
            for abi in new_queues:
                if abi in self.recent_builds:
                    self.recent_builds[abi] = {
                        key: expires
                        for key, expires in self.recent_builds[abi].items()
                        if expires > now
                    }
                else:
                    self.recent_builds[abi] = {}
            # Set up the new queues without recent builds (and converting
            # list-pairs into tuples)
            self.abi_queues = {
                abi: [
                    (package, version) for package, version in new_queue
                    if (package, version) not in self.recent_builds[abi]
                    and (package, version) not in self.recent_deletes
                    and (package, None) not in self.recent_deletes
                ]
                for abi, new_queue in new_queues.items()
            }
            self.stats_queue.send_msg('STATBQ', {
                abi: len(queue)
                for (abi, queue) in self.abi_queues.items()
            })
            # Wipe the recent_deletes set; it only exists to prune recently
            # deleted packages from in-flight build-queue queries
            self.recent_deletes = set()

    def handle_delete(self, queue):
        """
        Handle package or version deletion requests.

        When the PyPI upstream deletes a version or package, the
        :class:`CloudGazer` task requests that other tasks perform the deletion
        on its behalf. In the case of this task, this involves cancelling any
        pending builds of that package (version), and ignoring any builds
        involving that package (version) in the next queue update from
        :class:`TheArchitect`.
        """
        msg, data = queue.recv_msg()
        if msg == 'DELVER':
            del_pkg, del_ver = data
        elif msg == 'DELPKG':
            del_pkg, del_ver = data, None
        self.recent_deletes.add((del_pkg, del_ver))
        for slave in self.slaves.values():
            if slave.reply[0] == 'BUILD':
                build_pkg, build_ver = slave.reply[1]
                if build_pkg == del_pkg and del_ver in (None, build_ver):
                    slave.skip()
        queue.send_msg('OK')

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
            address, msg, data = queue.recv_addr_msg()
        except IOError as e:
            self.logger.error(str(e))
            return

        try:
            slave = self.slaves[address]
        except KeyError:
            if msg == 'HELLO':
                slave = SlaveState(address, *data)
            else:
                # XXX Tell the slave to die?
                self.logger.error('invalid first message from slave: %s', msg)
                return

        slave.request = msg, data
        handler = {
            'HELLO': self.do_hello,
            'BYE':   self.do_bye,
            'IDLE':  self.do_idle,
            'BUSY':  self.do_busy,
            'BUILT': self.do_built,
            'SENT':  self.do_sent,
        }[msg]
        msg, data = handler(slave)
        if msg is not None:
            slave.reply = msg, data
            queue.send_addr_msg(address, msg, data)

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
            'slave %d (%s): hello (build_timeout=%s, busy_timeout=%s, abi=%s, '
            'platform=%s, os_name=%s, os_version=%s, board_revision=%s, '
            'board_serial=%s)',
            slave.slave_id, slave.label, slave.build_timeout,
            slave.busy_timeout, slave.native_abi, slave.native_platform,
            slave.os_name, slave.os_version, slave.board_revision,
            slave.board_serial)
        self.slaves[slave.address] = slave
        return 'ACK', [slave.slave_id, self.pypi_simple]

    def do_bye(self, slave):
        """
        Handler for the build slave's final "BYE" message upon shutdown. This
        removes the associated state from the internal ``slaves`` dict.

        :param SlaveState slave:
            The object representing the current status of the build slave.
        """
        self.logger.warning('slave %d (%s): shutdown',
                            slave.slave_id, slave.label)
        # Send a fake DIE message to the status queue so that listening
        # monitors know to remove the entry
        slave.reply = 'DIE', protocols.NoData
        del self.slaves[slave.address]
        return None, None

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
        if slave.reply[0] not in ('ACK', 'SLEEP', 'DONE'):
            self.logger.error(
                'slave %d (%s): protocol error (IDLE after %s)',
                slave.slave_id, slave.label, slave.reply[0])
            return 'DIE', protocols.NoData
        elif slave.killed:
            return 'DIE', protocols.NoData
        elif self.paused:
            self.logger.info(
                'slave %d (%s): sleeping because master is paused',
                slave.slave_id, slave.label)
            return 'SLEEP', True
        else:
            try:
                abi_queue = self.abi_queues[slave.native_abi]
                recent_builds = self.recent_builds[slave.native_abi]
            except KeyError:
                abi_queue = []
            try:
                while abi_queue:
                    package, version = abi_queue.pop(0)
                    if (package, version) not in recent_builds:
                        self.logger.info(
                            'slave %d (%s): build %s %s',
                            slave.slave_id, slave.label, package, version)
                        recent_builds[(package, version)] = (
                            datetime.now(tz=UTC) + slave.build_timeout)
                        return 'BUILD', [package, version]
                self.logger.info(
                    'slave %d (%s): sleeping because no builds',
                    slave.slave_id, slave.label)
                return 'SLEEP', False
            finally:
                # Only push queue stats if there's space in the stats_queue
                # (it's not essential; just a nice-to-have)
                if self.stats_queue.poll(0, transport.POLLOUT):
                    self.stats_queue.send_msg('STATBQ', {
                        abi: len(queue)
                        for (abi, queue) in self.abi_queues.items()
                    })

    def do_busy(self, slave):
        """
        Handler for the build slave's "BUSY" message, which is sent
        periodically during package builds. If the slave fails to respond with
        a BUSY ping for a duration longer than :attr:`SlaveState.busy_timeout`
        then the master will assume the slave has died and remove it from the
        internal state mapping (if the slave happens to resurrect itself later
        the master will simply treat it as a new build slave).

        In response to "BUSY" the master can respond "CONT" to indicate the
        build should continue processing, or "DONE" to indicate that the build
        slave should immediately terminate and discard the build and return to
        "IDLE" state.
        """
        if slave.skipped:
            self.logger.info('slave %d (%s): build skipped',
                             slave.slave_id, slave.label)
            return 'DONE', protocols.NoData
        else:
            return 'CONT', protocols.NoData

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
                'slave %d (%s): protocol error (BUILT after %s)',
                slave.slave_id, slave.label, slave.reply[0])
            return 'DIE', protocols.NoData
        elif slave.skipped:
            # If the build was skipped, throw away the result without recording
            # success or failure (it may have been skipped because we know
            # there's something wrong with the slave)
            self.logger.info('slave %d (%s): build skipped',
                             slave.slave_id, slave.label)
            return 'DONE', protocols.NoData
        else:
            build_armv6l_hack(slave.build)
            if slave.build.status and not slave.build.transfers_done:
                self.logger.info('slave %d (%s): build succeeded',
                                 slave.slave_id, slave.label)
                self.fs.expect(slave.slave_id,
                               slave.build.files[slave.build.next_file])
                self.logger.info('slave %d (%s): send %s',
                                 slave.slave_id, slave.label,
                                 slave.build.next_file)
                return 'SEND', slave.build.next_file
            else:
                self.logger.info('slave %d (%s): build failed',
                                 slave.slave_id, slave.label)
                self.db.log_build(slave.build)
                self.web_queue.send_msg('PROJECT', slave.build.package)
                self.web_queue.recv_msg()
                return 'DONE', protocols.NoData

    def do_sent(self, slave):
        """
        Handler for the build slave's "SENT" message indicating that it's
        finished sending the requested file to :class:`FileJuggler`. The
        :class:`FsClient` RPC mechanism is used to ask :class:`FileJuggler` to
        verify the transfer against the stored hash and, if this is successful,
        a message is sent to :class:`TheScribe` to regenerate the package's
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
            return 'DIE', protocols.NoData
        elif self.fs.verify(slave.slave_id, slave.build.package):
            slave.build.files[slave.build.next_file].verified()
            self.logger.info(
                'slave %d (%s): verified transfer of %s',
                slave.slave_id, slave.label, slave.reply[1])
            if slave.build.transfers_done:
                self.db.log_build(slave.build)
                self.web_queue.send_msg('BOTH', slave.build.package)
                self.web_queue.recv_msg()
                return 'DONE', protocols.NoData
            else:
                self.fs.expect(slave.slave_id,
                               slave.build.files[slave.build.next_file])
                self.logger.info('slave %d (%s): send %s',
                                 slave.slave_id, slave.label,
                                 slave.build.next_file)
                return 'SEND', slave.build.next_file
        else:
            self.logger.info('slave %d (%s): re-send %s',
                             slave.slave_id, slave.label,
                             slave.build.next_file)
            return 'SEND', slave.build.next_file


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
                    file.abi_tag, 'linux_armv6l', file.dependencies, True)
