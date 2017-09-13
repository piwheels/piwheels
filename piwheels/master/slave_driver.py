import logging
from datetime import datetime

import zmq
from zmq.utils import jsonapi

from .states import SlaveState, FileState
from .tasks import Task, TaskQuit
from .the_oracle import DbClient


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
    def __init__(self, **config):
        super().__init__(**config)
        self.paused = False
        self.status_queue = self.ctx.socket(zmq.PUSH)
        self.status_queue.hwm = 10
        self.status_queue.connect(config['int_status_queue'])
        SlaveState.status_queue = self.status_queue
        self.slave_queue = self.ctx.socket(zmq.ROUTER)
        self.slave_queue.ipv6 = True
        self.slave_queue.bind(config['slave_queue'])
        self.build_queue = self.ctx.socket(zmq.PULL)
        self.build_queue.hwm = 1
        self.build_queue.connect(config['build_queue'])
        self.fs_queue = self.ctx.socket(zmq.REQ)
        self.fs_queue.hwm = 1
        self.fs_queue.connect(config['fs_queue'])
        self.db = DbClient(**config)

    def close(self):
        super().close()
        self.build_queue.close()
        self.slave_queue.close()
        self.status_queue.close()
        self.fs_queue.close()
        self.db.close()
        SlaveState.status_queue = None
        logger.info('closed')

    def run(self):
        logger.info('starting')
        poller = zmq.Poller()
        try:
            poller.register(self.control_queue, zmq.POLLIN)
            poller.register(self.slave_queue, zmq.POLLIN)
            while True:
                socks = dict(poller.poll(1000))
                if self.control_queue in socks:
                    self.handle_control()
                if self.slave_queue in socks:
                    self.handle_slave()
        except TaskQuit:
            pass

    def handle_control(self):
        msg, *args = self.control_queue.recv_json()
        if msg == 'QUIT':
            raise TaskQuit
        elif msg == 'PAUSE':
            self.paused = True
        elif msg == 'RESUME':
            self.paused = False

    def handle_slave(self):
        try:
            address, empty, msg = self.slave_queue.recv_multipart()
        except ValueError:
            logger.error('invalid message structure from slave')
        else:
            msg, *args = jsonapi.loads(msg)
            logger.debug('RX: %s %r', msg, args)

            try:
                slave = self.slaves[address]
            except KeyError:
                if msg != 'HELLO':
                    logger.error('invalid first message from slave: %s', msg)
                    return
                slave = SlaveState(*args)
            slave.request = [msg] + args

            handler = getattr(self, 'do_%s' % msg, None)
            if handler is None:
                logger.error(
                    'slave %d: Protocol error (%s)',
                    slave.slave_id, msg)
            else:
                reply = handler(slave)
                if reply is not None:
                    slave.reply = reply
                    self.slave_queue.send_multipart([
                        address,
                        empty,
                        jsonapi.dumps(reply)
                    ])
                    logger.debug('TX: %r', reply)

    def do_HELLO(self, slave):
        logger.warning('slave %d: Hello (timeout=%s, abi=%s, platform=%s)',
                       slave.slave_id, slave.timeout,
                       slave.native_abi, slave.native_platform)
        self.slaves[slave.address] = slave
        return ['HELLO', slave.slave_id]

    def do_BYE(self, slave):
        logger.warning('slave shutdown: %d', slave.slave_id)
        del self.slaves[slave.address]
        return None

    def do_IDLE(self, slave):
        if slave.reply[0] not in ('HELLO', 'SLEEP', 'DONE'):
            logger.error(
                'slave %d: Protocol error (IDLE after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif slave.terminated:
            return ['BYE']
        elif self.paused:
            return ['SLEEP']
        else:
            while True:
                events = self.build_queue.poll(0)
                if events:
                    package, version = self.build_queue.recv_json()
                    if (package, version) in self.active_builds():
                        continue
                    return ['BUILD', package, version]
                else:
                    return ['SLEEP']

    def do_BUILT(self, slave):
        if slave.reply[0] != 'BUILD':
            logger.error(
                'slave %d: Protocol error (BUILD after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif slave.reply[1] != slave.build.package:
            logger.error(
                'slave %d: Protocol error (BUILT %s instead of %s)',
                slave.slave_id, slave.build.package, slave.reply[1])
            return ['BYE']
        else:
            if slave.reply[2] != slave.build.version:
                logger.warning(
                    'slave %d: Build version mismatch: %s != %s',
                    slave.slave_id, slave.reply[2],
                    slave.build.version)
            self.build_armv6l_hack(slave.build)
            self.db.log_build(slave.build)
            if slave.build.status:
                self.fs.expect(slave.build.files[slave.build.next_file])
                return ['SEND', slave.build.next_file]
            else:
                return ['DONE']

    def do_SENT(self, slave, *args):
        if slave.reply[0] != 'SEND':
            logger.error(
                'slave %d: Protocol error (SENT after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif not slave.transfer:
            logger.error(
                'slave %d: Internal error; no transfer to verify',
                slave.slave_id)
            return
        elif slave.transfer.verify(slave):
            logger.info(
                'slave %d: Verified transfer of %s',
                slave.slave_id, slave.reply[1])
            if slave.build.transfers_done:
                self.build_armv6l_hack(slave.build)
                self.index_queue.send_string(slave.build.package)
                return ['DONE']
            else:
                return ['SEND', slave.build.next_file]
        else:
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
