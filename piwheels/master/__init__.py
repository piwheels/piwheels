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
import stat
import signal
import socket
import logging
from datetime import datetime, timezone

from .. import (
    __version__,
    terminal,
    const,
    systemd,
    transport,
    protocols,
    info,
)
from ..systemd import get_systemd
from ..tasks import TaskQuit
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


UTC = timezone.utc


class PiWheelsMaster:
    """
    This is the main class for the :program:`piw-master` script. It spawns
    various worker threads, then spends its time communicating with any
    attached monitor applications (see :program:`piw-monitor`) and build slaves
    (see :program:`piw-slave`).
    """
    def __init__(self):
        self.logger = logging.getLogger('master')
        self.started = datetime.now(tz=UTC)
        self.control_queue = None
        self.int_status_queue = None
        self.ext_status_queue = None
        self.tasks = []
        self.slave_driver = None
        self.big_brother = None

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
            '-o', '--output-path', metavar='PATH', default=const.OUTPUT_PATH,
            help="The path under which the website should be written; must be "
            "writable by the current user")
        parser.add_argument(
            '--dev-mode', action='store_true',
            help="Run the master in development mode, which reduces some "
            "timeouts and tweaks some defaults")
        parser.add_argument(
            '--debug', action='append', metavar='TASK', default=[],
            help="Set logging to debug level for the named task; can be "
            "specified multiple times to debug many tasks")
        parser.add_argument(
            '--pypi-xmlrpc', metavar='URL', default=const.PYPI_XMLRPC,
            help="The URL of the PyPI XML-RPC service (default: %(default)s)")
        parser.add_argument(
            '--pypi-simple', metavar='URL', default=const.PYPI_SIMPLE,
            help="The URL of the PyPI simple API (default: %(default)s)")
        parser.add_argument(
            '--pypi-json', metavar='URL', default=const.PYPI_JSON,
            help="The URL of the PyPI JSON API (default: %(default)s)")
        parser.add_argument(
            '--status-queue', metavar='ADDR', default=const.STATUS_QUEUE,
            help="The address of the queue used to report status to monitors "
            "(default: %(default)s); this is usually an ipc address")
        parser.add_argument(
            '--control-queue', metavar='ADDR', default=const.CONTROL_QUEUE,
            help="The address of the queue a monitor can use to control the "
            "master (default: %(default)s); this is usually an ipc address")
        parser.add_argument(
            '--import-queue', metavar='ADDR', default=const.IMPORT_QUEUE,
            help="The address of the queue used by piw-import (default: "
            "(%(default)s); this should always be an ipc address")
        parser.add_argument(
            '--log-queue', metavar='ADDR', default=const.LOG_QUEUE,
            help="The address of the queue used by piw-logger (default: "
            "(%(default)s); this should always be an ipc address")
        parser.add_argument(
            '--slave-queue', metavar='ADDR', default=const.SLAVE_QUEUE,
            help="The address of the queue used to talk to the build slaves "
            "(default: %(default)s); this is usually a tcp address")
        parser.add_argument(
            '--file-queue', metavar='ADDR', default=const.FILE_QUEUE,
            help="The address of the queue used to transfer files from slaves "
            "(default: %(default)s); this is usually a tcp address")
        parser.add_argument(
            '--web-queue', metavar='ADDR', default=const.WEB_QUEUE,
            help="The address of the queue used to request web page updates "
            "(default: %(default)s)")
        parser.add_argument(
            '--builds-queue', metavar='ADDR', default=const.BUILDS_QUEUE,
            help="The address of the queue used to store pending builds "
            "(default: %(default)s)")
        parser.add_argument(
            '--db-queue', metavar='ADDR', default=const.DB_QUEUE,
            help="The address of the queue used to talk to the database "
            "server (default: %(default)s)")
        parser.add_argument(
            '--fs-queue', metavar='ADDR', default=const.FS_QUEUE,
            help="The address of the queue used to talk to the file-system "
            "server (default: %(default)s)")
        parser.add_argument(
            '--stats-queue', metavar='ADDR', default=const.STATS_QUEUE,
            help="The address of the queue used to send statistics to the "
            "collator task (default: %(default)s)")
        return parser

    def __call__(self, args=None):
        sys.excepthook = terminal.error_handler
        parser = self.configure_parser()
        config = parser.parse_args(args)
        config.output_path = os.path.expanduser(config.output_path)
        if config.debug or config.dev_mode:
            config.log_level = logging.DEBUG
        terminal.configure_logging(config.log_level, config.log_file,
                                   console_name=True)
        self.logger.setLevel(min(logging.INFO, config.log_level))

        self.logger.info('PiWheels Master version %s', __version__)
        if os.geteuid() == 0:
            self.logger.error('Master must not be run as root')
            return 1
        if config.dev_mode:
            self.logger.warning('Starting in development mode; DO NOT use '
                                'this in production!')
        ctx = transport.Context()
        self.control_queue = ctx.socket(
            transport.PULL, protocol=protocols.master_control,
            logger=self.logger)
        self.control_queue.hwm = 10
        self.control_queue.bind(config.control_queue)
        self.int_status_queue = ctx.socket(
            transport.PULL, protocol=reversed(protocols.monitor_stats),
            logger=self.logger)
        self.int_status_queue.hwm = 10
        self.int_status_queue.bind(const.INT_STATUS_QUEUE)
        self.ext_status_queue = ctx.socket(
            transport.PUB, protocol=protocols.monitor_stats,
            logger=self.logger)
        self.ext_status_queue.bind(config.status_queue)
        # Ensure that the control and external status queues can be written to
        # by the owning group (for remote monitors)
        fix_ipc_mode(config.control_queue)
        fix_ipc_mode(config.status_queue)

        # NOTE: Tasks are spawned in a specific order (you need to know the
        # task dependencies to determine this order; see docs/master_arch chart
        # for more information). If I was a bit more intelligent, the tasks
        # would simply declare their sockets and which bound/connected to
        # which addresses at which point the master could calculate the order
        # below. Oh well ...
        self.tasks = [
            task(config)
            for task in (
                Seraph,
                TheOracle,
                TheOracle,
                TheOracle,
                Lumberjack,
                TheScribe,
                TheSecretary,
                BigBrother,
                FileJuggler,
                MrChase,
                SlaveDriver,
                TheArchitect,
                CloudGazer,
            )
        ]
        self.logger.info('starting tasks')
        for task in self.tasks:
            if isinstance(task, SlaveDriver):
                self.slave_driver = task
            elif isinstance(task, BigBrother):
                self.big_brother = task
            task.start()
            task.ready.wait(10)
        self.logger.info('started all tasks')
        assert all(task.ready.wait(0) for task in self.tasks)
        self.logger.info('all tasks ready')
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
                while True:
                    task.join(1)
                    if not task.is_alive():
                        break
                    # Continue draining the incoming status queue to prevent
                    # any tasks from blocking while trying to update status
                    self.int_status_queue.drain()
                systemd.extend_timeout(10)
            self.logger.info('stopped all tasks')
            self.control_queue.close()
            self.int_status_queue.close()
            self.ext_status_queue.close()
            self.logger.info('closed all queues')
            ctx.close()

    def main_loop(self, systemd):
        """
        This is the main loop of the :program:`piw-master` script. It receives
        messages from the internal status queue and forwards them onto the
        external status queue (for any :program:`piw-monitor` scripts that are
        attached). It also retrieves any messages sent to the control queue and
        dispatches them to a handler.
        """
        poller = transport.Poller()
        poller.register(self.control_queue, transport.POLLIN)
        poller.register(self.int_status_queue, transport.POLLIN)
        try:
            while True:
                systemd.watchdog_ping()
                socks = poller.poll(5)
                if self.int_status_queue in socks:
                    self.broadcast_status()
                if self.control_queue in socks:
                    try:
                        msg, data = self.control_queue.recv_msg()
                    except IOError as exc:
                        self.logger.error(str(exc))
                    else:
                        handler = {
                            'HELLO': self.do_hello,
                            'QUIT':  self.do_quit,
                            'KILL':  lambda: self.do_kill(data),
                            'SKIP':  lambda: self.do_skip(data),
                            'SLEEP': lambda: self.do_sleep(data),
                            'WAKE':  lambda: self.do_wake(data),
                        }[msg]
                        handler()
        finally:
            poller.unregister(self.int_status_queue)
            poller.unregister(self.control_queue)

    def broadcast_status(self):
        """
        Publish messages from the internal status queue to the external
        status queue, in case any monitors are attached.
        """
        msg, data = self.int_status_queue.recv_msg()
        self.ext_status_queue.send_msg(msg, data)

    def do_quit(self):
        """
        Handler for the QUIT message; this terminates the master.
        """
        # pylint: disable=no-self-use
        self.logger.warning('shutting down on QUIT message')
        raise TaskQuit

    def do_kill(self, slave_id):
        """
        Handler for the KILL message; this tells the specified build slave (or
        all slaves and the master if *slave_id* is ``None``) to terminate.
        """
        if slave_id is None:
            self.logger.warning('killing all slaves')
        else:
            self.logger.warning('killing slave %d', slave_id)
        self.slave_driver.kill_slave(slave_id)

    def do_skip(self, slave_id):
        """
        Handler for the SKIP message; this tells the specified build slave to
        skip its current build next time it contacts the master.
        """
        if slave_id is None:
            self.logger.warning('skipping all slaves')
        else:
            self.logger.warning('skipping slave %d', slave_id)
        self.slave_driver.skip_slave(slave_id)

    def do_sleep(self, slave_id):
        """
        Handler for the SLEEP message; this tells the specified build slave (or
        all slaves and the master if *slave_id* is ``None``) to pause their
        operations.
        """
        if slave_id is None:
            self.logger.warning('sleeping all slaves and master')
            for task in self.tasks:
                task.pause()
        else:
            self.logger.warning('sleeping slave %d', slave_id)
        self.slave_driver.sleep_slave(slave_id)

    def do_wake(self, slave_id):
        """
        Handler for the WAKE message; this tells the specified build slave (or
        all slaves and the master if *slave_id* is ``None``) to resume their
        operations.
        """
        if slave_id is None:
            self.logger.warning('waking all slaves and master')
            for task in self.tasks:
                task.resume()
        else:
            self.logger.warning('waking slave %d', slave_id)
        self.slave_driver.wake_slave(slave_id)

    def do_hello(self):
        """
        Handler for the HELLO message; this indicates a new monitor has been
        attached and would like the master's HELLO message and all the build
        slave's HELLO messages replayed to it.
        """
        self.logger.warning('sending status to new monitor')
        os_name, os_version = info.get_os_name_version()
        self.ext_status_queue.send_msg('HELLO', (
            self.started, socket.gethostname(), os_name, os_version,
            info.get_board_revision(), info.get_board_serial()))
        self.big_brother.replay_stats()
        self.slave_driver.list_slaves()


def sig_term(signo, stack_frame):
    """
    Handler for the SIGTERM signal; raises :exc:`SystemExit` which will cause
    the :meth:`PiWheelsMaster.main_loop` method to terminate.
    """
    # pylint: disable=unused-argument
    raise SystemExit(0)


def fix_ipc_mode(address):
    if address.startswith('ipc://'):
        path = address[len('ipc://'):]
        # Add group write privileges
        os.chmod(path, os.stat(path).st_mode | stat.S_IWGRP)


main = PiWheelsMaster()  # pylint: disable=invalid-name

if __name__ == '__main__':
    main()
