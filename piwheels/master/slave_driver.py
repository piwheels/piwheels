import logging
from datetime import datetime
from pathlib import Path

import zmq
from zmq.utils import jsonapi

from .states import SlaveState, FileState
from .tasks import Task, DatabaseMixin, TaskQuit


class SlaveDriver(DatabaseMixin, Task):
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
        self.output_path = Path(config['output_path'])
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
        self.index_queue = self.ctx.socket(zmq.PUSH)
        self.index_queue.hwm = 10
        self.index_queue.bind(config['index_queue'])

    def close(self):
        self.build_queue.close()
        self.slave_queue.close()
        self.status_queue.close()
        SlaveState.status_queue = None
        super().close()

    def run(self):
        try:
            while True:
                self.handle_control()
                if not self.slave_queue.poll(1000):
                    continue
                try:
                    address, empty, msg = self.slave_queue.recv_multipart()
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
                    slave = SlaveState(*args)
                slave.request = [msg] + args

                handler = getattr(self, 'handle_%s' % msg, None)
                if handler is None:
                    logging.error(
                        'Slave %d: Protocol error (%s)',
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
        except TaskQuit:
            pass

    def handle_control(self, timeout=0):
        if self.control_queue.poll(timeout):
            msg, *args = self.control_queue.recv_string()
            if msg == 'QUIT':
                raise TaskQuit
            elif msg == 'PAUSE':
                self.paused = True
            elif msg == 'RESUME':
                self.paused = False

    def handle_HELLO(self, slave):
        logging.warning('Slave %d: Hello (timeout=%s, abi=%s, platform=%s)',
                        slave.slave_id, slave.timeout,
                        slave.native_abi, slave.native_platform)
        self.slaves[slave.address] = slave
        return ['HELLO', slave.slave_id]

    def handle_BYE(self, slave):
        logging.warning('Slave shutdown: %d', slave.slave_id)
        del self.slaves[slave.address]
        return None

    def handle_IDLE(self, slave):
        if slave.reply[0] not in ('HELLO', 'SLEEP', 'DONE'):
            logging.error(
                'Slave %d: Protocol error (IDLE after %s)',
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

    def handle_BUILT(self, slave):
        if slave.reply[0] != 'BUILD':
            logging.error(
                'Slave %d: Protocol error (BUILD after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif slave.reply[1] != slave.build.package:
            logging.error(
                'Slave %d: Protocol error (BUILT %s instead of %s)',
                slave.slave_id, slave.build.package, slave.reply[1])
            return ['BYE']
        else:
            if slave.reply[2] != slave.build.version:
                logging.warning(
                    'Slave %d: Build version mismatch: %s != %s',
                    slave.slave_id, slave.reply[2],
                    slave.build.version)
            self.db.log_build(slave.build)
            if slave.build.status:
                return ['SEND', slave.build.next_file]
            else:
                return ['DONE']

    def handle_SENT(self, slave, *args):
        if slave.reply[0] != 'SEND':
            logging.error(
                'Slave %d: Protocol error (SENT after %s)',
                slave.slave_id, slave.reply[0])
            return ['BYE']
        elif not slave.transfer:
            logging.error(
                'Slave %d: Internal error; no transfer to verify',
                slave.slave_id)
            return
        elif slave.transfer.verify(slave.build):
            logging.info(
                'Slave %d: Verified transfer of %s',
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

    def build_armv6l_hack(self, db, build):
        # NOTE: dirty hack; if the build contains any arch-specific wheels for
        # armv7l, link armv6l name to the armv7l file and stick some entries
        # in the database for them.
        for file in list(build.files.values()):
            if file.platform_tag == 'linux_armv7l':
                arm7_path = (
                    self.output_path / 'simple' / build.package /
                    file.filename)
                arm6_path = arm7_path.with_name(
                    arm7_path.name[:-16] + 'linux_armv6l.whl')
                new_file = FileState(arm6_path.name, file.filesize,
                                     file.filehash, file.package_version_tag,
                                     file.py_version_tag, file.abi_tag,
                                     'linux_armv6l')
                new_file.verified()
                build.files[new_file.filename] = new_file
                db.log_file(build, new_file)
                try:
                    arm6_path.symlink_to(arm7_path.name)
                except FileExistsError:
                    pass
