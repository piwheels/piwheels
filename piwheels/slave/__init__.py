#!/usr/bin/env python

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
Defines the :class:`PiWheelsSlave` class. An instance of this is the
entry-point for the :program:`piw-slave` script.

.. autoclass:: PiWheelsSlave
    :members:

.. autofunction:: duration
"""

import os
import sys
import signal
import logging
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from time import sleep
from random import randint

import dateutil.parser

from .. import __version__, terminal, transport, protocols, info, platform
from ..systemd import get_systemd
from .builder import Builder, Wheel


UTC = timezone.utc


class MasterTimeout(IOError):
    "Exception raised when the master fails to respond before a timeout."


class TerminateTimeout(IOError):
    "Exception raised when a build fails to terminate in a reasonable time."


class PiWheelsSlave:
    """
    This is the main class for the :program:`piw-slave` script. It connects
    (over 0MQ sockets) to a master (see :program:`piw-master`) then loops
    around the slave protocol (see the :doc:`slaves` chapter). It retrieves
    source packages directly from `PyPI`_, attempts to build a wheel in a
    sandbox directory and, if successful, transmits the results to the master.

    .. _PyPI: https://pypi.python.org/
    """
    def __init__(self):
        self.logger = logging.getLogger('slave')
        self.config = None
        self.slave_id = None
        self.builder = None
        self.pypi_url = None
        self.systemd = None

    def __call__(self, args=None):
        sys.excepthook = terminal.error_handler
        parser = terminal.configure_parser("""
The piw-slave script is intended to be run on a standalone machine to build
packages on behalf of the piw-master script. It is intended to be run as an
unprivileged user with a clean home-directory. Any build dependencies you wish
to use must already be installed. The script will run until it is explicitly
terminated, either by Ctrl+C, SIGTERM, or by the remote piw-master script.
""")
        parser.add_argument(
            '--debug', action='store_true', help="Set logging to debug level")
        parser.add_argument(
            '-m', '--master', env_var='PIW_MASTER', metavar='HOST',
            default='localhost',
            help="The IP address or hostname of the master server "
            "(default: %(default)s)")
        parser.add_argument(
            '-t', '--timeout', env_var='PIW_TIMEOUT', metavar='DURATION',
            default='3h', type=duration,
            help="The time to wait before assuming a build has failed "
            "(default: %(default)s)")
        parser.add_argument(
            '-d', '--dir', metavar='DIR', default=tempfile.gettempdir(),
            help="The temporary directory to use when building wheels "
            "(default: %(default)s)")
        parser.add_argument(
            '-L', '--label', metavar='STR', default=socket.gethostname(),
            help="The label to transmit to the master identifying this "
            "build slave (default: %(default)s)")
        self.config = parser.parse_args(args)
        if self.config.debug:
            self.config.log_level = logging.DEBUG
        terminal.configure_logging(self.config.log_level, self.config.log_file)

        self.logger.info('PiWheels Slave version %s', __version__)
        if os.geteuid() == 0:
            self.logger.fatal('Slave must not be run as root')
            return 1
        if datetime.now(tz=UTC) < datetime(2020, 6, 1, tzinfo=UTC):
            self.logger.fatal('System clock is far in the past')
            return 1
        self.systemd = get_systemd()
        signal.signal(signal.SIGTERM, sig_term)
        ctx = transport.Context()
        queue = None
        try:
            while True:
                queue = ctx.socket(
                    transport.REQ, protocol=reversed(protocols.slave_driver),
                    logger=self.logger)
                queue.hwm = 10
                queue.connect('tcp://{master}:5555'.format(
                    master=self.config.master))
                self.systemd.ready()
                try:
                    self.slave_id = None
                    self.main_loop(queue)
                except MasterTimeout:
                    self.systemd.reloading()
                    self.logger.warning('Resetting connection')
                    queue.close(linger=1)
                finally:
                    self.clean_up_build()
        except SystemExit:
            self.logger.warning('Shutting down on SIGTERM')
        finally:
            self.systemd.stopping()
            queue.send_msg('BYE')
            queue.close()
            ctx.close()

    # A general note about the design of the slave: the build slave is
    # deliberately designed to be "brittle". In other words to fall over and
    # die loudly in the event anything happens to go wrong (other than utterly
    # expected failures like wheels occasionally failing to build and file
    # transfers occasionally needing a retry). Hence all the apparently silly
    # asserts littering the functions below.

    # This is in stark constrast to the master which is expected to stay up and
    # carry on running even if a build slave goes bat-shit crazy and starts
    # sending nonsense (in which case it should calmly ignore it and/or attempt
    # to kill said slave with a "BYE" message).

    def main_loop(self, queue, master_timeout=timedelta(minutes=5)):
        """
        The main messaging loop. Sends the initial request, and dispatches
        replies via :meth:`handle_reply`. Implements a *timeout* for responses
        from the master and raises :exc:`MasterTimeout` if *timeout* seconds
        are exceeded.
        """
        os_name, os_version = info.get_os_name_version()
        msg, data = 'HELLO', [
            self.config.timeout, master_timeout,
            platform.get_impl_ver(), platform.get_abi_tag(),
            platform.get_platform(), self.config.label,
            os_name, os_version,
            info.get_board_revision(), info.get_board_serial(),
        ]
        while True:
            queue.send_msg(msg, data)
            start = datetime.now(tz=UTC)
            while True:
                self.systemd.watchdog_ping()
                if queue.poll(1):
                    msg, data = queue.recv_msg()
                    msg, data = self.handle_reply(msg, data)
                    break
                elif datetime.now(tz=UTC) - start > master_timeout:
                    self.logger.warning('Timed out waiting for master')
                    raise MasterTimeout()

    def clean_up_build(self, timeout=timedelta(minutes=1)):
        """
        Terminate any existing build and clean up its temporary storage. Raises
        an exception if termination does not occur in a reasonable time.
        """
        if self.builder is not None:
            try:
                if self.builder.is_alive():
                    self.logger.info('Terminating current build')
                    self.builder.stop()
                    self.builder.join(timeout.total_seconds())
                if self.builder.is_alive():
                    self.logger.fatal('Build failed to terminate')
                    raise TerminateTimeout()
                else:
                    self.logger.info('Removing temporary build directories')
                    self.builder.close()
            finally:
                # Always set self.builder to None to ensure we don't re-try
                self.builder = None

    def handle_reply(self, msg, data):
        """
        Dispatch a message from the master to an appropriate handler method.
        """
        handler = {
            'ACK': lambda: self.do_ack(*data),
            'SLEEP': lambda: self.do_sleep(data),
            'BUILD': lambda: self.do_build(*data),
            'CONT': self.do_cont,
            'SEND': lambda: self.do_send(data),
            'DONE': self.do_done,
            'DIE': self.do_die,
        }[msg]
        return handler()

    def get_status(self):
        """
        Returns the set of statistics periodically required by the master when
        reporting our status.
        """
        return (
            [datetime.now(tz=UTC)] +
            list(info.get_disk_stats(self.config.dir)) +
            list(info.get_mem_stats()) +
            list(info.get_swap_stats()) +
            [os.getloadavg()[0], info.get_cpu_temp()]
        )

    def do_ack(self, new_id, pypi_url):
        """
        In response to our initial "HELLO" (detailing our various :pep:`425`
        tags), the master is expected to send "ACK" back with an integer
        identifier and the URL of the PyPI repository to download from. We use
        the identifier in all future log messages for the ease of the
        administrator.

        We reply with "IDLE" to indicate we're ready to accept a build job.
        """
        assert self.slave_id is None, 'Duplicate ACK'
        self.slave_id = int(new_id)
        self.pypi_url = pypi_url
        self.logger = logging.getLogger('slave-%d' % self.slave_id)
        self.logger.info('Connected to master')
        return 'IDLE', self.get_status()

    def do_sleep(self, paused):
        """
        If, in response to an "IDLE" message we receive "SLEEP" this indicates
        the master has nothing for us to do currently. Sleep for a little while
        then try "IDLE" again.
        """
        assert self.slave_id is not None, 'SLEEP before ACK'
        if paused:
            self.logger.info("Sleeping: paused")
        else:
            self.logger.info("Sleeping: no available jobs")
        sleep(randint(5, 10))
        return 'IDLE', self.get_status()

    def do_build(self, package, version):
        """
        Alternatively, in response to "IDLE", the master may send "BUILD"
        *package* *version*. We should then attempt to build the specified
        wheel and send back a "BUSY" message with more status info.
        """
        assert self.slave_id is not None, 'BUILD before ACK'
        assert not self.builder, 'Last build still exists'
        self.logger.warning('Building package %s version %s', package, version)
        self.builder = Builder(package, version, self.config.timeout,
                               self.pypi_url, self.config.dir)
        self.builder.start()
        return 'BUSY', self.get_status()

    def do_cont(self):
        """
        Once we're busy building something the master will periodically ping
        us with "CONT" if it wishes us to continue building. We wait up to
        10 seconds for the build to finish and reply with "BUILT" (and a full
        status report on the build) if it finishes in that time, or "BUSY"
        and more status info otherwise.

        If the master wishes to terminate a build prior to completion, it'll
        send "DONE" instead of "CONT" and we move straight to clean-up.
        """
        assert self.slave_id is not None, 'CONT before ACK'
        assert self.builder, 'CONT before BUILD / after failed BUILD'
        self.builder.join(randint(5, 10))
        if not self.builder.is_alive():
            if self.builder.status:
                self.logger.info('Build succeeded')
            else:
                self.logger.warning('Build failed')
            return 'BUILT', self.builder.as_message()[2:]
        else:
            return 'BUSY', self.get_status()

    def do_send(self, filename):
        """
        If a build succeeds and generates files (detailed in a "BUILT"
        message), the master will reply with "SEND" *filename* indicating we
        should transfer the specified file (this is done on a separate socket
        with a different protocol; see :meth:`builder.Wheel.transfer` for more
        details). Once the transfers concludes, reply to the master with
        "SENT".
        """
        assert self.slave_id is not None, 'SEND before ACK'
        assert self.builder, 'SEND before BUILD / after failed BUILD'
        assert self.builder.status, 'SEND after failed BUILD'
        wheel = [f for f in self.builder.wheels if f.filename == filename][0]
        self.logger.info(
            'Sending %s to master on %s', wheel.filename, self.config.master)
        ctx = transport.Context()
        queue = ctx.socket(transport.DEALER, logger=self.logger)
        queue.hwm = 10
        queue.connect('tcp://{master}:5556'.format(master=self.config.master))
        try:
            wheel.transfer(queue, self.slave_id)
        finally:
            queue.close()
        return 'SENT', protocols.NoData

    def do_done(self):
        """
        The master can send "DONE" at any point during a built to terminate it
        prematurely. Alternately, this is also the standard reponse after a
        successful build has finished and all files have been sent (and
        successfully verified).

        In response we must clean-up all resources associated with the build
        (including terminating an on-going build) and return "IDLE" with the
        usual stats.
        """
        assert self.slave_id is not None, 'DONE before ACK'
        assert self.builder, 'DONE before BUILD'
        self.clean_up_build()
        return 'IDLE', self.get_status()

    def do_die(self):
        """
        The master may respond with "DIE" at any time indicating we should
        immediately terminate. We raise :exc:`SystemExit` to cause
        :meth:`main_loop` to exit. Clean-up of any extant build is handled by
        our caller.
        """
        self.logger.warning('Master requested termination')
        raise SystemExit(0)


def duration(s):
    """
    Convert *s*, a string representing a duration, into a
    :class:`datetime.timedelta`.
    """
    return (
        dateutil.parser.parse(s, default=datetime(1, 1, 1)) -
        datetime(1, 1, 1)
    )


def sig_term(signo, stack_frame):
    """
    Handler for the SIGTERM signal; raises :exc:`SystemExit` which will cause
    the :meth:`PiWheelsSlave.main_loop` method to terminate.
    """
    # pylint: disable=unused-argument
    raise SystemExit(0)


main = PiWheelsSlave()  # pylint: disable=invalid-name

if __name__ == '__main__':
    main()
