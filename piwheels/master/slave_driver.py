import logging
import pickle
from datetime import datetime

import zmq

from .states import SlaveState, FileState
from .tasks import Task, TaskQuit
from .the_oracle import DbClient
from .file_juggler import FsClient


logger = logging.getLogger('master.slave_driver')


class SlaveDriver(Task):
    """
    This task handles interaction with the build slaves using the slave
    protocol. Interaction is driven by the slaves (i.e. the master doesn't
    *push* jobs, rather the slaves *request* a job and the master replies with
    the next (package, version) tuple from the internal "builds" queue).

    The task also incidentally interacts with several other queues: the internal
    "status" queue is sent details of every reply sent to a build slave (the
    :meth:`main` task passes this information on to any listening monitors).
    Also, the internal "indexes" queue is informed of any packages that need web
    page indexes re-building (as a result of a successful build).
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
        self.db = DbClient(config)
        self.fs = FsClient(config)
        self.slaves = {}

    def close(self):
        super().close()
        self.build_queue.close()
        self.status_queue.close()
        self.fs.close()
        self.db.close()
        SlaveState.status_queue = None

    def handle_control(self, q):
        msg, *args = q.recv_pyobj()
        if msg == 'QUIT':
            raise TaskQuit
        elif msg == 'PAUSE':
            self.paused = True
        elif msg == 'RESUME':
            self.paused = False

    def handle_slave(self, q):
        try:
            address, empty, msg = q.recv_multipart()
        except ValueError:
            self.logger.error('invalid message structure from slave')
        else:
            msg, *args = pickle.loads(msg)
            logger.debug('RX: %s %r', msg, args)

            try:
                slave = self.slaves[address]
            except KeyError:
                if msg != 'HELLO':
                    self.logger.error('invalid first message from slave: %s', msg)
                    return
                slave = SlaveState(address, *args)
            slave.request = [msg] + args

            handler = getattr(self, 'do_%s' % msg, None)
            if handler is None:
                logger.error(
                    'slave %d: protocol error (%s)',
                    slave.slave_id, msg)
            else:
                reply = handler(slave)
                if reply is not None:
                    slave.reply = reply
                    q.send_multipart([
                        address,
                        empty,
                        pickle.dumps(reply)
                    ])
                    self.logger.debug('TX: %r', reply)

    def do_HELLO(self, slave):
        self.logger.warning('slave %d: hello (timeout=%s, abi=%s, platform=%s)',
                            slave.slave_id, slave.timeout,
                            slave.native_abi, slave.native_platform)
        self.slaves[slave.address] = slave
        return ['HELLO', slave.slave_id]

    def do_BYE(self, slave):
        self.logger.warning('slave %d: shutdown', slave.slave_id)
        del self.slaves[slave.address]
        return None

    def do_IDLE(self, slave):
        if slave.reply[0] not in ('HELLO', 'SLEEP', 'DONE'):
            self.logger.error(
                'slave %d: protocol error (IDLE after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif slave.terminated:
            return ['BYE']
        elif self.paused:
            logger.info(
                'slave %d: sleeping because master is paused', slave.slave_id)
            return ['SLEEP']
        else:
            self.build_queue.send_pyobj(slave.native_abi)
            task = self.build_queue.recv_pyobj()
            if task is not None:
                if task not in self.active_builds():
                    package, version = task
                    self.logger.info(
                        'slave %d: build %s %s', slave.slave_id, package, version)
                    return ['BUILD', package, version]
            self.logger.info(
                'slave %d: sleeping because no builds', slave.slave_id)
            return ['SLEEP']

    def do_BUILT(self, slave):
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
            self.build_armv6l_hack(slave.build)
            self.db.log_build(slave.build)
            if slave.build.status and not slave.build.transfers_done:
                self.fs.expect(slave.slave_id, slave.build.files[slave.build.next_file])
                self.logger.info(
                    'slave %d: send %s', slave.slave_id, slave.build.next_file)
                return ['SEND', slave.build.next_file]
            else:
                self.logger.info('slave %d: build failed', slave.slave_id)
                return ['DONE']

    def do_SENT(self, slave, *args):
        if slave.reply[0] != 'SEND':
            self.logger.error(
                'slave %d: protocol error (SENT after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif self.fs.verify(slave.slave_id, slave.build.package):
            slave.build.files[slave.build.next_file].verified()
            self.logger.info(
                'slave %d: verified transfer of %s',
                slave.slave_id, slave.reply[1])
            if slave.build.transfers_done:
                return ['DONE']
            else:
                self.fs.expect(slave.slave_id, slave.build.files[slave.build.next_file])
                self.logger.info(
                    'slave %d: send %s', slave.slave_id, slave.build.next_file)
                return ['SEND', slave.build.next_file]
        else:
            logger.info(
                'slave %d: send %s', slave.slave_id, slave.build.next_file)
            return ['SEND', slave.build.next_file]

    def active_builds(self):
        for slave in self.slaves.values():
            if slave.reply is not None and slave.reply[0] == 'BUILD':
                if slave.last_seen + slave.timeout > datetime.utcnow():
                    yield (slave.reply[1], slave.reply[2])

    def build_armv6l_hack(self, build):
        # NOTE: dirty hack; if the build contains any arch-specific wheels for
        # armv7l, generate equivalent armv6l entries from them
        for file in list(build.files.values()):
            if file.platform_tag == 'linux_armv7l':
                arm7_name = file.filename
                arm6_name = arm7_name[:-16] + 'linux_armv6l.whl'
                build.files[arm6_name] = FileState(
                    arm6_name, file.filesize, file.filehash, file.package_tag,
                    file.package_version_tag, file.py_version_tag, file.abi_tag,
                    'linux_armv6l', True)
