import os
import logging
from datetime import datetime, timedelta
from time import sleep

import zmq
from wheel import pep425tags

from .builder import PiWheelsBuilder
from ..terminal import TerminalApplication
from .. import __version__


def timeout(arg):
    d = datetime.strptime(arg, '%H:%M:%S')
    return timedelta(hours=d.hour, minutes=d.minute, seconds=d.second)


class PiWheelsSlave(TerminalApplication):
    def __init__(self):
        super().__init__(__version__)
        self.parser.add_argument(
            '-m', '--master', metavar='HOST',
            default=os.environ.get('PW_MASTER', 'localhost'),
            help='The IP address or hostname of the master server; defaults to '
            'the value of the PW_MASTER env-var (%(default)s)')
        self.parser.add_argument(
            '-t', '--timeout', metavar='TIME', type=timeout,
            default=os.environ.get('PW_TIMEOUT', '03:00:00'),
            help='The time to wait before assuming a build has failed; '
            'defaults to the value of the PW_TIMEOUT env-var (%(default)s)')

    def main(self, args):
        logging.info('PiWheels Slave version {}'.format(__version__))
        ctx = zmq.Context.instance()
        master = args.master
        timeout = args.timeout.total_seconds()
        slave_id = None
        builder = None
        queue = ctx.socket(zmq.REQ)
        queue.hwm = 1
        queue.ipv6 = True
        queue.connect('tcp://{master}:5555'.format(master=master))
        try:
            request = ['HELLO', timeout] + list(pep425tags.get_supported()[0])
            while True:
                queue.send_json(request)
                reply, *args = queue.recv_json()

                if reply == 'HELLO':
                    assert slave_id is None, 'Duplicate hello'
                    assert len(args) == 1, 'Invalid HELLO message'
                    slave_id = int(args[0])
                    logging.info('Slave %d: Advertising new slave to master at %s',
                                 slave_id, master)
                    request = ['IDLE']

                elif reply == 'SLEEP':
                    assert slave_id is not None, 'Sleep before hello'
                    assert len(args) == 0, 'Invalid SLEEP message'
                    logging.info('Slave %d: No available jobs; sleeping',
                                 slave_id)
                    sleep(10)
                    request = ['IDLE']

                elif reply == 'BUILD':
                    assert slave_id is not None, 'Build before hello'
                    assert not builder, 'Last build still exists'
                    assert len(args) == 2, 'Invalid BUILD message'
                    package, version = args
                    logging.warning('Slave %d: Building package %s version %s',
                                    slave_id, package, version)
                    builder = PiWheelsBuilder(package, version)
                    if builder.build(timeout):
                        logging.info('Slave %d: Build succeeded', slave_id)
                    else:
                        logging.warning('Slave %d: Build failed', slave_id)
                    request = [
                        'BUILT',
                        builder.package,
                        builder.version,
                        builder.status,
                        builder.duration,
                        builder.output,
                        {
                            pkg.filename: (
                                pkg.filesize,
                                pkg.filehash,
                                pkg.package_version_tag,
                                pkg.py_version_tag,
                                pkg.abi_tag,
                                pkg.platform_tag,
                            )
                            for pkg in builder.files
                        },

                    ]

                elif reply == 'SEND':
                    assert slave_id is not None, 'Send before hello'
                    assert builder, 'Send before build / after failed build'
                    assert builder.status, 'Send after failed build'
                    assert len(args) == 1, 'Invalid SEND messsage'
                    pkg = [f for f in builder.files if f.filename == args[0]][0]
                    logging.info('Slave %d: Sending %s to master',
                                 slave_id, pkg.filename)
                    self.transfer(master, slave_id, pkg)
                    request = ['SENT']

                elif reply == 'DONE':
                    assert slave_id is not None, 'Okay before hello'
                    assert builder, 'Okay before build'
                    assert len(args) == 0, 'Invalid DONE message'
                    logging.info('Slave %d: Removing temporary build directories',
                                 slave_id)
                    builder.clean()
                    builder = None
                    request = ['IDLE']

                elif reply == 'BYE':
                    logging.warning('Slave %d: Master requested termination',
                                    slave_id)
                    break

                else:
                    assert False, 'Invalid message from master'
        finally:
            queue.send_json(['BYE'])
            queue.close()
            ctx.term()

    def transfer(self, master, slave_id, package):
        ctx = zmq.Context.instance()
        with package.open() as f:
            queue = ctx.socket(zmq.DEALER)
            queue.ipv6 = True
            queue.hwm = 10
            queue.connect('tcp://{master}:5556'.format(master=master))
            try:
                timeout = 0
                while True:
                    if not queue.poll(timeout):
                        # Initially, send HELLO immediately; in subsequent loops
                        # if we hear nothing from the server for 5 seconds then
                        # it's dropped a *lot* of packets; prod the master with
                        # HELLO again
                        queue.send_multipart([b'HELLO', str(slave_id).encode('ascii')])
                        timeout = 5000
                    req, *args = queue.recv_multipart()
                    if req == b'DONE':
                        return
                    elif req == b'FETCH':
                        offset, size = args
                        f.seek(int(args[0]))
                        queue.send_multipart([b'CHUNK', args[0], f.read(int(args[1]))])
            finally:
                queue.close()

main = PiWheelsSlave()
