import os
import logging
from time import sleep

import zmq

from .builder import PiWheelsBuilder
from ..terminal import TerminalApplication
from .. import __version__


class PiWheelsSlave(TerminalApplication):
    def __init__(self):
        super().__init__(__version__)
        self.parser.add_argument(
            '-m', '--master', default=os.environ.get('PW_MASTER', 'localhost'),
            help='The IP address or hostname of the master server; defaults to '
            ' the value of the PW_MASTER env-var (%(default)s)')

    def main(self, args):
        logging.info('PiWheels Slave version {}'.format(__version__))
        ctx = zmq.Context()
        master = args.master
        slave_id = None
        builder = None
        queue = ctx.socket(zmq.REQ)
        queue.ipv6 = True
        queue.connect('tcp://{master}:5555'.format(master=master))
        request = ['HELLO']
        while True:
            queue.send_json(request)
            reply, *args = queue.recv_json()

            if reply == 'HELLO':
                assert slave_id is None, 'Duplicate hello'
                assert len(args) == 1, 'Invalid HELLO message'
                slave_id = int(args[0])
                request = ['IDLE']

            elif reply == 'SLEEP':
                assert slave_id is not None, 'Sleep before hello'
                assert len(args) == 0, 'Invalid SLEEP message'
                logging.info('No available jobs; sleeping')
                sleep(10)
                request = ['IDLE']

            elif reply == 'BUILD':
                assert slave_id is not None, 'Build before hello'
                assert not builder, 'Last build still exists'
                assert len(args) == 2, 'Invalid BUILD message'
                package, version = args
                logging.info('Building package %s version %s', package, version)
                builder = PiWheelsBuilder(package, version)
                builder.build()
                request = [
                    'BUILT',
                    builder.package,
                    builder.version,
                    builder.status,
                    builder.output,
                    builder.filename,
                    builder.filesize,
                    builder.filehash,
                    builder.duration,
                    builder.package_version_tag,
                    builder.py_version_tag,
                    builder.abi_tag,
                    builder.platform_tag,
                ]

            elif reply == 'SEND':
                assert slave_id is not None, 'Send before hello'
                assert builder, 'Send before build / after failed build'
                assert builder.status, 'Send after failed build'
                assert len(args) == 0, 'Invalid SEND messsage'
                logging.info('Sending package to master')
                self.transfer(master, ctx, slave_id, builder)
                request = ['SENT']

            elif reply == 'DONE':
                assert slave_id is not None, 'Okay before hello'
                assert builder, 'Okay before build'
                assert len(args) == 0, 'Invalid DONE message'
                logging.info('Removing temporary build directories')
                builder.clean()
                builder = None
                request = ['IDLE']

            elif reply == 'BYE':
                logging.warning('Master requested termination')
                break

            else:
                assert False, 'Invalid message from master'

    def transfer(self, master, ctx, slave_id, builder):
        with builder.open() as f:
            queue = ctx.socket(zmq.DEALER)
            queue.ipv6 = True
            queue.connect('tcp://{master}:5556'.format(master=master))
            try:
                queue.send_multipart([b'HELLO', str(slave_id).encode('ascii')])
                while True:
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
