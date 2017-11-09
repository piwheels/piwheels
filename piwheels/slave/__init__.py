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

"Defines the :class:`PiWheelsSlave` application."

import logging
from datetime import datetime
from time import sleep

import zmq
import dateutil.parser
from wheel import pep425tags

from .builder import PiWheelsBuilder
from ..terminal import TerminalApplication
from .. import __version__


def duration(s):
    """
    Convert *s*, a string representing a duration, into a
    :class:`datetime.timedelta`.
    """
    return (
        dateutil.parser.parse(s, default=datetime(1, 1, 1)) -
        datetime(1, 1, 1)
    )


class PiWheelsSlave(TerminalApplication):
    """
    This is the main class for the ``piw-slave`` script. It connects (over zmq
    sockets) to a master (see ``piw-master``) then loops around requesting
    package versions to build. It retrieves source directly from PyPI, attempts
    to build a wheel in a sandbox directory and, if successful, transmits the
    results to the master.
    """
    def __init__(self):
        super().__init__(__version__)
        self.parser.add_argument(
            '-m', '--master', metavar='HOST',
            help='The IP address or hostname of the master server; overrides '
            'the [slave]/master entry in the configuration file')
        self.parser.add_argument(
            '-t', '--timeout', metavar='TIME', type=duration,
            help='The time to wait before assuming a build has failed; '
            'overrides the [slave]/timeout entry in the configuration file')
        self.logger = logging.getLogger('slave')
        self.config = None
        self.slave_id = None
        self.builder = None

    def load_configuration(self, args, default=None):
        if default is None:
            default = {
                'slave': {
                    'master': 'localhost',
                    'timeout': '3h',
                },
            }
        config = super().load_configuration(args, default=default)
        config = dict(config['slave'])
        if args.master is not None:
            config['master'] = args.master
        if args.timeout is not None:
            config['timeout'] = args.timeout
        # Convert duration to a simple seconds count
        config['timeout'] = duration(config['timeout']).total_seconds()
        return config

    def main(self, args, config):
        logging.info('PiWheels Slave version %s', __version__)
        self.config = config
        ctx = zmq.Context.instance()
        queue = ctx.socket(zmq.REQ)
        queue.hwm = 1
        queue.ipv6 = True
        queue.connect('tcp://{master}:5555'.format(
            master=self.config['master']))
        try:
            request = (
                ['HELLO', config['timeout']] +
                list(pep425tags.get_supported()[0])
            )
            while request is not None:
                queue.send_pyobj(request)
                reply, *args = queue.recv_pyobj()
                request = self.handle_reply(reply, *args)
        finally:
            queue.send_pyobj(['BYE'])
            queue.close()
            ctx.term()

    # A general note about the design of the slave: the build slave is
    # deliberately designed to be "brittle". In other words to fall over and
    # die loudly in the event anything happens to go wrong (other than utterly
    # expected failures like wheels occasionally failing to build and file
    # transfers occasionally needing a retry). Hence all the apparently silly
    # asserts littering the methods below.
    #
    # This is in stark constrast to the master which is expected to stay up and
    # carry on running even if a build slave goes bat-shit crazy and starts
    # sending nonsense (in which case it should calmly ignore it and/or attempt
    # to kill said slave with a "BYE" message).

    def handle_reply(self, reply, *args):
        """
        Dispatch a message from the master to an appropriate handler method.
        """
        try:
            handler = getattr(self, 'do_%s' % reply.lower())
        except AttributeError:
            assert False, 'Invalid message from master'
        else:
            return handler(*args)

    def do_hello(self, slave_id):
        """
        In response to our initial HELLO (detailing our various PEP425 tags),
        the master is expected to send HELLO back with an integer identifier.
        We use the identifier in all future log messages for the ease of the
        administrator.

        We reply with IDLE to indicate we're ready to accept a build job.
        """
        assert self.slave_id is None, 'Duplicate hello'
        self.slave_id = int(slave_id)
        self.logger = logging.getLogger('slave-%d' % self.slave_id)
        self.logger.info('Connected to master at %s', self.config['master'])
        return ['IDLE']

    def do_sleep(self):
        """
        If, in response to an IDLE message we receive SLEEP this indicates the
        master has nothing for us to do currently. Sleep for a little while
        then try IDLE again.
        """
        assert self.slave_id is not None, 'Sleep before hello'
        self.logger.info('No available jobs; sleeping')
        sleep(10)
        return ['IDLE']

    def do_build(self, package, version):
        """
        Alternatively, in response to IDLE, the master may send BUILD <package>
        <version>. We should then attempt to build the specified wheel and send
        back a BUILT message with a full report of the outcome.
        """
        assert self.slave_id is not None, 'Build before hello'
        assert not self.builder, 'Last build still exists'
        self.logger.warning('Building package %s version %s',
                            package, version)
        self.builder = PiWheelsBuilder(package, version)
        if self.builder.build(self.config['timeout']):
            self.logger.info('Build succeeded')
        else:
            self.logger.warning('Build failed')
        return [
            'BUILT',
            self.builder.package,
            self.builder.version,
            self.builder.status,
            self.builder.duration,
            self.builder.output,
            {
                pkg.filename: (
                    pkg.filesize,
                    pkg.filehash,
                    pkg.package_tag,
                    pkg.package_version_tag,
                    pkg.py_version_tag,
                    pkg.abi_tag,
                    pkg.platform_tag,
                )
                for pkg in self.builder.files
            },
        ]

    def do_send(self, filename):
        """
        If a build succeeds and generates files (detailed in a BUILT message),
        the master will reply with SEND <filename> indicating we should
        transfer the specified file (this is done on a separate socket with a
        different protocol; see :meth:`transfer` for more details). Once the
        transfers concludes, reply to the master with SENT.
        """
        assert self.slave_id is not None, 'Send before hello'
        assert self.builder, 'Send before build / after failed build'
        assert self.builder.status, 'Send after failed build'
        pkg = [f for f in self.builder.files if f.filename == filename][0]
        self.logger.info('Sending %s to master', pkg.filename)
        self.transfer(pkg)
        return ['SENT']

    def do_done(self):
        """
        After all files have been sent (and successfully verified), the master
        will reply with DONE indicating we can remove all associated build
        artifacts. We respond with IDLE.
        """
        assert self.slave_id is not None, 'Okay before hello'
        assert self.builder, 'Okay before build'
        self.logger.info('Removing temporary build directories')
        self.builder.clean()
        self.builder = None
        return ['IDLE']

    def do_bye(self):
        """
        The master may respond with BYE at any time indicating we should
        immediately terminate (first cleaning up any extant build). We return
        ``None`` to tell the main loop to quit.
        """
        self.logger.warning('Master requested termination')
        if self.builder is not None:
            self.logger.info('Removing temporary build directories')
            self.builder.clean()
        return None

    def transfer(self, package):
        """
        Transfer *package* to *master* over the separate file transfer queue.
        See the ``docs/file_protocol`` chart for a rough overview of the file
        transfer protocol.

        :param str master:
            The IP address of the master node.

        :param pathlib.Path package:
            The path of the package to transfer.
        """
        ctx = zmq.Context.instance()
        with package.open() as f:
            queue = ctx.socket(zmq.DEALER)
            queue.ipv6 = True
            queue.hwm = 10
            queue.connect('tcp://{master}:5556'.format(
                master=self.config['master']))
            try:
                timeout = 0
                while True:
                    if not queue.poll(timeout):
                        # Initially, send HELLO immediately; in subsequent
                        # loops if we hear nothing from the server for 5
                        # seconds then it's dropped a *lot* of packets; prod
                        # the master with HELLO again
                        queue.send_multipart(
                            [b'HELLO', str(self.slave_id).encode('ascii')]
                        )
                        timeout = 5000
                    req, *args = queue.recv_multipart()
                    if req == b'DONE':
                        return
                    elif req == b'FETCH':
                        offset, size = args
                        f.seek(int(offset))
                        queue.send_multipart(
                            [b'CHUNK', offset, f.read(int(size))]
                        )
            finally:
                queue.close()


main = PiWheelsSlave()  # pylint: disable=invalid-name
