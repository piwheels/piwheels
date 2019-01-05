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
Defines the :class:`PiWheelsMaster` class. An instance of this is the
entry-point for the :program:`piw-master` script.

.. autoclass:: PiWheelsMaster
    :members:

.. autofunction:: sig_term
"""

import os
import sys
import signal
import logging

import zmq

from .. import __version__, terminal, const, systemd, transport, protocols
from ..systemd import get_systemd
from .tasks import TaskQuit
from .big_brother import BigBrother
from .the_architect import TheArchitect
from .the_oracle import TheOracle
from .seraph import Seraph
from .slave_driver import SlaveDriver
from .file_juggler import FileJuggler
from .the_secretary import TheSecretary
from .the_scribe import TheScribe
from .cloud_gazer import CloudGazer
from .mr_chase import MrChase
from .lumberjack import Lumberjack


class PiWheelsMaster:
    """
    This is the main class for the :program:`piw-master` script. It spawns
    various worker threads, then spends its time communicating with any
    attached monitor applications (see :program:`piw-monitor`) and build slaves
    (see :program:`piw-slave`).
    """
    def __init__(self):
        self.logger = logging.getLogger('master')
        self.control_queue = None
        self.int_status_queue = None
        self.ext_status_queue = None
        self.tasks = []

    @staticmethod
    def configure_parser():
        """
        Construct the command line parser for :program:`piw-master` with its
        many options (this method only exists to simplify the main method).
        """
        parser = terminal.configure_parser("""
The piw-master script is intended to be run on the database and file-server
machine. It is recommended you do not run piw-slave on the same machine as the
piw-master script. The database specified in the configuration must exist and
have been configured with the piw-initdb script. It is recommended you run
piw-master as an ordinary unprivileged user, although obviously it will need
write access to the output directory.
""")
        parser.add_argument(
            '-d', '--dsn', default=const.DSN,
            help="The database to use; this database must be configured with "
            "piw-initdb and the user should *not* be a PostgreSQL superuser "
            "(default: %(default)s)")
        parser.add_argument(
            '--pypi-xmlrpc', metavar='URL', default=const.PYPI_XMLRPC,
            help="The URL of the PyPI XML-RPC service (default: %(default)s)")
        parser.add_argument(
            '--pypi-simple', metavar='URL', default=const.PYPI_SIMPLE,
            help="The URL of the PyPI simple API (default: %(default)s)")
        parser.add_argument(
            '-o', '--output-path', metavar='PATH', default=const.OUTPUT_PATH,
            help="The path under which the website should be written; must be "
            "writable by the current user")
        parser.add_argument(
            '--web-queue', metavar='ADDR', default=const.WEB_QUEUE,
            help="The address of the queue used to request web page updates "
            "(default: %(default)s)")
        parser.add_argument(
            '--status-queue', metavar='ADDR', default=const.STATUS_QUEUE,
            help="The address of the queue used to report status to monitors "
            "(default: %(default)s)")
        parser.add_argument(
            '--control-queue', metavar='ADDR', default=const.CONTROL_QUEUE,
            help="The address of the queue a monitor can use to control the "
            "master (default: %(default)s)")
        parser.add_argument(
            '--builds-queue', metavar='ADDR', default=const.BUILDS_QUEUE,
            help="The address of the queue used to store pending builds "
            "(default: %(default)s)")
        parser.add_argument(
            '--stats-queue', metavar='ADDR', default=const.STATS_QUEUE,
            help="The address of the queue used to send statistics to the "
            "collator task (default: %(default)s)")
        parser.add_argument(
            '--db-queue', metavar='ADDR', default=const.DB_QUEUE,
            help="The address of the queue used to talk to the database "
            "server (default: %(default)s)")
        parser.add_argument(
            '--fs-queue', metavar='ADDR', default=const.FS_QUEUE,
            help="The address of the queue used to talk to the file-system "
            "server (default: %(default)s)")
        parser.add_argument(
            '--slave-queue', metavar='ADDR', default=const.SLAVE_QUEUE,
            help="The address of the queue used to talk to the build slaves "
            "(default: %(default)s); this is usually a tcp address")
        parser.add_argument(
            '--file-queue', metavar='ADDR', default=const.FILE_QUEUE,
            help="The address of the queue used to transfer files from slaves "
            "(default: %(default)s); this is usually a tcp address")
        parser.add_argument(
            '--import-queue', metavar='ADDR', default=const.IMPORT_QUEUE,
            help="The address of the queue used by piw-import (default: "
            "(%(default)s); this should always be an ipc address")
        parser.add_argument(
            '--log-queue', metavar='ADDR', default=const.LOG_QUEUE,
            help="The address of the queue used by piw-log (default: "
            "(%(default)s)")
        return parser

    def __call__(self, args=None):
        sys.excepthook = terminal.error_handler
        parser = self.configure_parser()
        config = parser.parse_args(args)
        config.output_path = os.path.expanduser(config.output_path)
        terminal.configure_logging(config.log_level, config.log_file)
        # We want the logger name included in our console output
        terminal._CONSOLE.setFormatter(  # pylint: disable=protected-access
            logging.Formatter('%(name)s: %(message)s'))

        self.logger.info('PiWheels Master version %s', __version__)
        if os.geteuid() == 0:
            self.logger.error('Master must not be run as root')
            return 1
        ctx = transport.Context.instance()
        self.control_queue = ctx.socket(
            zmq.PULL, protocol=protocols.master_control)
        self.control_queue.hwm = 10
        self.control_queue.bind(config.control_queue)
        self.int_status_queue = ctx.socket(
            zmq.PULL, protocol=reversed(protocols.monitor_stats))
        self.int_status_queue.hwm = 10
        self.int_status_queue.bind(const.INT_STATUS_QUEUE)
        self.ext_status_queue = ctx.socket(
            zmq.PUB, protocol=protocols.monitor_stats)
        self.ext_status_queue.hwm = 10
        self.ext_status_queue.bind(config.status_queue)

        # NOTE: Tasks are spawned in a specific order (you need to know the
        # task dependencies to determine this order; see docs/master_arch chart
        # for more information)
        self.tasks = [
            task(config)
            for task in (
                Seraph,
                TheOracle,
                TheOracle,
                TheOracle,
                TheArchitect,
                Lumberjack,
                TheSecretary,
                TheScribe,
                BigBrother,
                FileJuggler,
                CloudGazer,
                SlaveDriver,
                MrChase,
            )
        ]
        self.logger.info('starting tasks')
        for task in self.tasks:
            task.start()
        self.logger.info('started all tasks')
        systemd = get_systemd()
        signal.signal(signal.SIGTERM, sig_term)
        try:
            systemd.ready()
            self.main_loop(systemd)
        except TaskQuit:
            pass
        except SystemExit:
            self.logger.warning('shutting down on SIGTERM')
        except KeyboardInterrupt:
            self.logger.warning('shutting down on Ctrl+C')
        finally:
            systemd.stopping()
            self.logger.info('stopping tasks')
            for task in reversed(self.tasks):
                task.quit()
                task.join()
                systemd.extend_timeout(10)
            self.logger.info('stopped all tasks')
            self.control_queue.close()
            self.int_status_queue.close()
            self.ext_status_queue.close()
            self.logger.info('closed all queues')
            ctx.destroy(linger=1000)
            ctx.term()

    def main_loop(self, systemd):
        """
        This is the main loop of the :program:`piw-master` script. It receives
        messages from the internal status queue and forwards them onto the
        external status queue (for any :program:`piw-monitor` scripts that are
        attached). It also retrieves any messages sent to the control queue and
        dispatches them to a handler.
        """
        poller = zmq.Poller()
        poller.register(self.control_queue, zmq.POLLIN)
        poller.register(self.int_status_queue, zmq.POLLIN)
        while True:
            systemd.watchdog_ping()
            socks = dict(poller.poll(60000))
            if self.int_status_queue in socks:
                self.ext_status_queue.send(self.int_status_queue.recv())
            if self.control_queue in socks:
                try:
                    msg, data = self.control_queue.recv_msg()
                except IOError as exc:
                    self.logger.error(str(exc))
                else:
                    handler = {
                        'QUIT': self.do_quit,
                        'KILL': lambda: self.do_kill(data),
                        'HELLO': self.do_hello,
                        'PAUSE': self.do_pause,
                        'RESUME': self.do_resume,
                    }[msg]
                    handler()

    def do_quit(self):
        """
        Handler for the QUIT message; this terminates the master.
        """
        # pylint: disable=no-self-use
        self.logger.warning('shutting down on QUIT message')
        raise TaskQuit

    def do_kill(self, slave_id):
        """
        Handler for the KILL message; this terminates the specified build slave
        by its master id.
        """
        self.logger.warning('killing slave %d', slave_id)
        for task in self.tasks:
            if isinstance(task, SlaveDriver):
                task.kill_slave(slave_id)

    def do_pause(self):
        """
        Handler for the PAUSE message; this requests all tasks pause their
        operations.
        """
        self.logger.warning('pausing operations')
        for task in self.tasks:
            task.pause()

    def do_resume(self):
        """
        Handler for the RESUME message; this requests all tasks resume their
        operations.
        """
        self.logger.warning('resuming operations')
        for task in self.tasks:
            task.resume()

    def do_hello(self):
        """
        Handler for the HELLO message; this indicates a new monitor has been
        attached and would like all the build slave's HELLO messages replayed
        to it.
        """
        self.logger.warning('sending status to new monitor')
        for task in self.tasks:
            if isinstance(task, SlaveDriver):
                task.list_slaves()


def sig_term(signo, stack_frame):
    """
    Handler for the SIGTERM signal; raises :exc:`SystemExit` which will cause
    the :meth:`PiWheelsMaster.main_loop` method to terminate.
    """
    # pylint: disable=unused-argument
    raise SystemExit(0)


main = PiWheelsMaster()  # pylint: disable=invalid-name

if __name__ == '__main__':
    main()
