"Defines the :class:`SlaveDriver` task; see class for more details"

import pickle
from datetime import datetime

import zmq

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
    slave (the :meth:`main` task passes this information on to any listening
    monitors).  Also, the internal "indexes" queue is informed of any packages
    that need web page indexes re-building (as a result of a successful build).
    """
    name = 'master.slave_driver'

    def __init__(self, config):
        super().__init__(config)
        self.paused = False
        slave_queue = self.ctx.socket(zmq.ROUTER)
        slave_queue.ipv6 = True
        slave_queue.bind(config['slave_queue'])
        self.register(slave_queue, self.handle_slave)
        self.status_queue = self.ctx.socket(zmq.PUSH)
        self.status_queue.hwm = 10
        self.status_queue.connect(config['int_status_queue'])
        SlaveState.status_queue = self.status_queue
        self.build_queue = self.ctx.socket(zmq.REQ)
        self.build_queue.hwm = 1
        self.build_queue.connect(config['build_queue'])
        self.index_queue = self.ctx.socket(zmq.PUSH)
        self.index_queue.hwm = 10
        self.index_queue.connect(config['index_queue'])
        self.db = DbClient(config)
        self.fs = FsClient(config)
        self.slaves = {}

    def list_slaves(self):
        """
        Additional task control method to trigger a HELLO message to the
        internal control queue. See :meth:`Task.quit` for more information.
        """
        self._ctrl(['HELLO'])

    def kill_slave(self, slave_id):
        """
        Additional task control method to trigger a KILL message to the
        internal control queue. See :meth:`Task.quit` for more information.
        """
        self._ctrl(['KILL', slave_id])

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

    def handle_slave(self, queue):
        """
        Handle requests from build slaves.

        See the ``docs/slave_protocol`` chart for a graphical overview of the
        protocol for messages between build slaves and :class:`SlaveDriver`.
        This method retrieves the message from the build slave, finds the
        associated :class:`SlaveState` and updates it with the message, then
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
                if msg != 'HELLO':
                    self.logger.error('invalid first message from slave: %s',
                                      msg)
                    return
                slave = SlaveState(address, *args)
            slave.request = [msg] + args

            handler = getattr(self, 'do_%s' % msg.lower(), None)
            if handler is None:
                self.logger.error(
                    'slave %d: protocol error (%s)',
                    slave.slave_id, msg)
            else:
                reply = handler(slave)
                if reply is not None:
                    slave.reply = reply
                    queue.send_multipart([
                        address,
                        empty,
                        pickle.dumps(reply)
                    ])
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
            'slave %d: hello (timeout=%s, abi=%s, platform=%s)',
            slave.slave_id, slave.timeout, slave.native_abi,
            slave.native_platform)
        self.slaves[slave.address] = slave
        return ['HELLO', slave.slave_id]

    def do_bye(self, slave):
        """
        Handler for the build slave's final "BYE" message upon shutdown. This
        removes the associated state from the internal ``slaves`` dict.

        :param SlaveState slave:
            The object representing the current status of the build slave.
        """
        self.logger.warning('slave %d: shutdown', slave.slave_id)
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
                'slave %d: protocol error (IDLE after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif slave.terminated:
            return ['BYE']
        elif self.paused:
            self.logger.info(
                'slave %d: sleeping because master is paused', slave.slave_id)
            return ['SLEEP']
        else:
            self.build_queue.send_pyobj(slave.native_abi)
            task = self.build_queue.recv_pyobj()
            if task is not None:
                if task not in self.active_builds():
                    package, version = task
                    self.logger.info(
                        'slave %d: build %s %s',
                        slave.slave_id, package, version)
                    return ['BUILD', package, version]
            self.logger.info(
                'slave %d: sleeping because no builds', slave.slave_id)
            return ['SLEEP']

    def do_built(self, slave):
        """
        Handler for the build slave's "BUILT" message, which is sent after an
        attempted package build succeeds or fails. The handler logs the result
        in the database and, if files have been generated by the build, informs
        the :class:`FileJuggler` task to expect a file transfer before sending
        "SEND" back to the build slave with the required filename.

        If no files were generated (e.g. in the case of a failed build, or a
        degenerate success), "DONE" is returned indicating that the build slave
        is free to discard all resources generated during the build and return
        to its idle state.
        """
        if slave.reply[0] != 'BUILD':
            self.logger.error(
                'slave %d: protocol error (BUILD after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif slave.reply[1] != slave.build.package:
            self.logger.error(
                'slave %d: protocol error (BUILT %s instead of %s)',
                slave.slave_id, slave.build.package, slave.reply[1])
            return ['BYE']
        else:
            if slave.reply[2] != slave.build.version:
                self.logger.warning(
                    'slave %d: build version mismatch: %s != %s',
                    slave.slave_id, slave.reply[2],
                    slave.build.version)
            build_armv6l_hack(slave.build)
            self.db.log_build(slave.build)
            if slave.build.status and not slave.build.transfers_done:
                self.fs.expect(slave.slave_id,
                               slave.build.files[slave.build.next_file])
                self.logger.info(
                    'slave %d: send %s', slave.slave_id, slave.build.next_file)
                return ['SEND', slave.build.next_file]
            else:
                self.logger.info('slave %d: build failed', slave.slave_id)
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
                'slave %d: protocol error (SENT after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif self.fs.verify(slave.slave_id, slave.build.package):
            self.index_queue.send_pyobj(['PKG', slave.build.package])
            slave.build.files[slave.build.next_file].verified()
            self.logger.info(
                'slave %d: verified transfer of %s',
                slave.slave_id, slave.reply[1])
            if slave.build.transfers_done:
                return ['DONE']
            else:
                self.fs.expect(slave.slave_id,
                               slave.build.files[slave.build.next_file])
                self.logger.info(
                    'slave %d: send %s', slave.slave_id, slave.build.next_file)
                return ['SEND', slave.build.next_file]
        else:
            self.logger.info(
                'slave %d: send %s', slave.slave_id, slave.build.next_file)
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
    wheels for armv7l, generate equivalent armv6l entries from them.
    """
    for file in list(build.files.values()):
        if file.platform_tag == 'linux_armv7l':
            arm7_name = file.filename
            arm6_name = arm7_name[:-16] + 'linux_armv6l.whl'
            build.files[arm6_name] = FileState(
                arm6_name, file.filesize, file.filehash, file.package_tag,
                file.package_version_tag, file.py_version_tag, file.abi_tag,
                'linux_armv6l', True)
