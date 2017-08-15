import os
import logging
import tempfile
from time import sleep
from datetime import datetime, timedelta
from threading import Thread
from pathlib import Path

import sqlalchemy as sa
import zmq
from zmq.utils import jsonapi
from pkg_resources import resource_string, resource_stream

from .db import PiWheelsDatabase
from .html import tag
from .states import FileState, SlaveState, TransferState
from ..terminal import TerminalApplication
from .. import __version__


class PiWheelsMaster(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, __doc__)
        self.parser.add_argument('-p', '--pypi-root', metavar='URL',
                                 default='https://pypi.python.org/pypi',
                                 help='The root URL of the PyPI repository '
                                 '(default: %(default)s)')
        self.parser.add_argument('-d', '--dsn', metavar='URL',
                                 default='postgres:///piwheels',
                                 help='The SQLAlchemy DSN used to connect to '
                                 'the piwheels database (default: %(default)s)')
        self.parser.add_argument('-o', '--output', metavar='PATH',
                                 default=Path(os.path.expanduser('~/www')),
                                 help='The path to write wheels into '
                                 '(default: %(default)s)')

    def setup_paths(self, args):
        output_path = Path(args.output)
        try:
            output_path.mkdir()
        except FileExistsError:
            pass
        try:
            (output_path / 'simple').mkdir()
        except FileExistsError:
            pass
        for filename in ('raspberry-pi-logo.svg', 'python-logo.svg'):
            with (output_path / filename).open('wb') as f:
                source = resource_stream(__name__, filename)
                f.write(source.read())
                source.close()
        TransferState.output_path = output_path

    def main(self, args):
        """
        The "main" task is responsible for constructing (and starting) the
        threads for all the sub-tasks. It also creates the queues used to
        interact with any monitors ("piw-control" and "piw-status"). Finally, it
        also creates and controls the internal "quit" queue, used to indicate to
        the sub-tasks when termination has been requested.
        """
        logging.info('PiWheels Master version {}'.format(__version__))
        self.slaves = {}
        self.transfers = {}
        self.paused = False
        self.db_engine = sa.create_engine(args.dsn)
        self.pypi_root = args.pypi_root
        self.homepage_template = resource_string(__name__, 'index.template.html').decode('utf-8')
        self.setup_paths(args)
        ctx = zmq.Context.instance()
        quit_queue = ctx.socket(zmq.PUB)
        quit_queue.hwm = 1
        quit_queue.bind('inproc://quit')
        ctrl_queue = ctx.socket(zmq.PULL)
        ctrl_queue.hwm = 1
        ctrl_queue.bind('ipc:///tmp/piw-control')
        int_status_queue = ctx.socket(zmq.PULL)
        int_status_queue.hwm = 10
        int_status_queue.bind('inproc://status')
        ext_status_queue = ctx.socket(zmq.PUB)
        ext_status_queue.hwm = 10
        ext_status_queue.bind('ipc:///tmp/piw-status')
        packages_thread = Thread(target=self.web_scraper, daemon=True)
        builds_thread = Thread(target=self.queue_stuffer, daemon=True)
        status_thread = Thread(target=self.big_brother, daemon=True)
        slave_thread = Thread(target=self.slave_driver, daemon=True)
        files_thread = Thread(target=self.build_catcher, daemon=True)
        index_thread = Thread(target=self.index_scribbler, daemon=True)
        packages_thread.start()
        builds_thread.start()
        files_thread.start()
        status_thread.start()
        slave_thread.start()
        index_thread.start()
        try:
            poller = zmq.Poller()
            poller.register(ctrl_queue, zmq.POLLIN)
            poller.register(int_status_queue, zmq.POLLIN)
            while True:
                socks = dict(poller.poll())
                if int_status_queue in socks:
                    ext_status_queue.send(int_status_queue.recv())
                if ctrl_queue in socks:
                    msg, *args = ctrl_queue.recv_json()
                    if msg == 'QUIT':
                        logging.warning('Shutting down on QUIT message')
                        break
                    elif msg == 'KILL':
                        logging.warning('Killing slave %d', args[0])
                        for slave in self.slaves.values():
                            if slave.slave_id == args[0]:
                                slave.kill()
                    elif msg == 'PAUSE':
                        logging.warning('Pausing operations')
                        self.paused = True
                    elif msg == 'RESUME':
                        logging.warning('Resuming operations')
                        self.paused = False
        except KeyboardInterrupt:
            logging.warning('Shutting down on Ctrl+C')
        finally:
            # Give all slaves 30 seconds to quit; this may seem rather arbitrary
            # but it's entirely possible there're dead slaves hanging around in
            # the slaves dict and there's no way (in our ridiculously simple
            # protocol) to terminate a slave in the middle of a build so an
            # arbitrary timeout is about the best we can do
            logging.warning('Waiting up to 30 seconds for slave shutdown')
            for slave in self.slaves.values():
                slave.kill()
            for i in range(30):
                if not self.slaves:
                    break
                sleep(1)
            quit_queue.send_string('QUIT')
            index_thread.join()
            slave_thread.join()
            status_thread.join()
            files_thread.join()
            builds_thread.join()
            packages_thread.join()
            quit_queue.close()
            ext_status_queue.close()
            int_status_queue.close()
            ctrl_queue.close()
            ctx.term()

    def web_scraper(self):
        """
        This task scrapes PyPI for the list of available packages, and the
        versions of those packages. This information is written into the backend
        database for :meth:`queue_stuffer` to use.
        """
        ctx = zmq.Context.instance()
        quit_queue = ctx.socket(zmq.SUB)
        quit_queue.connect('inproc://quit')
        quit_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        try:
            with PiWheelsDatabase(self.db_engine, self.pypi_root) as db:
                while not quit_queue.poll(1000):
                    db.update_package_list()
                    for package in db.get_all_packages():
                        db.update_package_version_list(package)
                        if quit_queue.poll(0):
                            break
                        while self.paused:
                            sleep(1)
        finally:
            quit_queue.close()

    def queue_stuffer(self):
        """
        This task queries the backend database to determine which versions of
        packages have yet to be built (and aren't marked to be skipped). It
        places a tuple of (package, version) for each such build into the
        internal "builds" queue for :meth:`slave_driver` to read.
        """
        ctx = zmq.Context.instance()
        quit_queue = ctx.socket(zmq.SUB)
        quit_queue.connect('inproc://quit')
        quit_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        build_queue = ctx.socket(zmq.PUSH)
        build_queue.hwm = 50
        build_queue.bind('inproc://builds')
        try:
            with PiWheelsDatabase(self.db_engine, self.pypi_root) as db:
                while not quit_queue.poll(0):
                    for package, version in db.get_build_queue():
                        while not quit_queue.poll(0):
                            if build_queue.poll(1000, zmq.POLLOUT):
                                build_queue.send_json((package, version))
                                break
                        if quit_queue.poll(0):
                            break
        finally:
            build_queue.close()
            quit_queue.close()

    def big_brother(self):
        """
        This task periodically queries the database and output file-system for
        various statistics like the number of packages known to the system,
        the number built, the number of packages built in the last hour, the
        remaining file-system space, etc. These statistics are written to the
        internal "status" queue which :meth:`main` uses to pass statistics to
        any listening monitors.
        """
        ctx = zmq.Context.instance()
        status_queue = ctx.socket(zmq.PUSH)
        status_queue.hwm = 1
        status_queue.connect('inproc://status')
        quit_queue = ctx.socket(zmq.SUB)
        quit_queue.connect('inproc://quit')
        quit_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        try:
            with PiWheelsDatabase(self.db_engine, self.pypi_root) as db:
                while not quit_queue.poll(10000):
                    stat = os.statvfs(str(TransferState.output_path))
                    rec = db.get_statistics()
                    status_info = {
                            'packages_count':   rec.packages_count,
                            'packages_built':   rec.packages_built,
                            'versions_count':   rec.versions_count,
                            'versions_built':   rec.versions_built,
                            'builds_count':     rec.builds_count,
                            'builds_last_hour': rec.builds_count_last_hour,
                            'builds_success':   rec.builds_count_success,
                            'builds_time':      rec.builds_time.total_seconds(),
                            'builds_size':      rec.builds_size,
                            'disk_free':        stat.f_frsize * stat.f_bavail,
                            'disk_size':        stat.f_frsize * stat.f_blocks,
                        }
                    self.write_homepage(status_info)
                    status_queue.send_json([
                        -1,
                        datetime.utcnow().timestamp(),
                        'STATUS',
                        status_info
                    ])
        finally:
            status_queue.close()
            quit_queue.close()

    def slave_driver(self):
        """
        This task handles interaction with the build slaves using the slave
        protocol. Interaction is driven by the slaves (i.e. the master doesn't
        *push* jobs, rather the slaves *request* a job and the master replies
        with the next (package, version) tuple from the internal "builds"
        queue).

        The task also incidentally interacts with several other queues: the
        internal "status" queue is sent details of every reply sent to a build
        slave (the :meth:`main` task passes this information on to any listening
        monitors). Also, the internal "indexes" queue is informed of any
        packages that need web page indexes re-building (as a result of a
        successful build).
        """
        ctx = zmq.Context.instance()
        status_queue = ctx.socket(zmq.PUSH)
        status_queue.hwm = 10
        status_queue.connect('inproc://status')
        SlaveState.status_queue = status_queue
        quit_queue = ctx.socket(zmq.SUB)
        quit_queue.connect('inproc://quit')
        quit_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        slave_queue = ctx.socket(zmq.ROUTER)
        slave_queue.ipv6 = True
        slave_queue.bind('tcp://*:5555')
        build_queue = ctx.socket(zmq.PULL)
        build_queue.hwm = 10
        build_queue.connect('inproc://builds')
        index_queue = ctx.socket(zmq.PUSH)
        index_queue.hwm = 10
        index_queue.bind('inproc://indexes')
        try:
            with PiWheelsDatabase(self.db_engine, self.pypi_root) as db:
                while not quit_queue.poll(0):
                    if not slave_queue.poll(1000):
                        continue
                    try:
                        address, empty, msg = slave_queue.recv_multipart()
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
                        slave = SlaveState()
                        self.slaves[address] = slave
                    slave.request = [msg] + args

                    if msg == 'HELLO':
                        logging.warning('New slave: %d', slave.slave_id)
                        reply = ['HELLO', slave.slave_id]

                    elif msg == 'BYE':
                        logging.warning('Slave shutdown: %d', slave.slave_id)
                        del self.slaves[address]
                        continue

                    elif msg == 'IDLE':
                        if slave.reply[0] not in ('HELLO', 'SLEEP', 'DONE'):
                            logging.error(
                                'Protocol error (IDLE after %s), dropping %d',
                                slave.reply[0], slave.slave_id)
                            reply = ['BYE']
                        elif slave.terminated:
                            reply = ['BYE']
                        elif self.paused:
                            reply = ['SLEEP']
                        else:
                            events = build_queue.poll(0)
                            if events:
                                package, version = build_queue.recv_json()
                                reply = ['BUILD', package, version]
                            else:
                                reply = ['SLEEP']

                    elif msg == 'BUILT':
                        if slave.reply[0] != 'BUILD':
                            logging.error(
                                'Protocol error (BUILD after %s), dropping %d',
                                slave.reply[0], slave.slave_id)
                            reply = ['BYE']
                        elif slave.reply[1] != slave.build.package:
                            logging.error(
                                'Protocol error (BUILT %s instead of %s), dropping %d',
                                slave.build.package, slave.reply[1],
                                slave.slave_id)
                            reply = ['BYE']
                        else:
                            if slave.reply[2] != slave.build.version:
                                logging.warning(
                                    'Build version mismatch: %s != %s',
                                    slave.reply[2], slave.build.version)
                            db.log_build(slave.build)
                            if slave.build.status:
                                reply = ['SEND', slave.build.next_file]
                            else:
                                reply = ['DONE']

                    elif msg == 'SENT':
                        if slave.reply[0] != 'SEND':
                            logging.error(
                                'Protocol error (SENT after %s), dropping %d',
                                slave.reply[0], slave.slave_id)
                            reply = ['BYE']
                        elif not slave.transfer:
                            logging.error(
                                'Internal error; no transfer to verify')
                            continue
                        elif slave.transfer.verify(slave.build):
                            logging.info(
                                'Verified transfer of %s', slave.reply[1])
                            if slave.build.transfers_done:
                                reply = ['DONE']
                                self.build_armv6l_hack(db, slave.build)
                                index_queue.send_string(slave.build.package)
                            else:
                                reply = ['SEND', slave.build.next_file]
                        else:
                            reply = ['SEND', slave.build.next_file]

                    else:
                        logging.error(
                            'Protocol error (%s), dropping %d',
                            msg, slave.slave_id)

                    slave.reply = reply
                    slave_queue.send_multipart([
                        address,
                        empty,
                        jsonapi.dumps(reply)
                    ])
        finally:
            build_queue.close()
            slave_queue.close()
            status_queue.close()
            SlaveState.status_queue = None
            quit_queue.close()

    def build_catcher(self):
        """
        This task handles file transfers from the build slaves. The specifics of
        the file transfer protocol are best understood from the implementation
        of the :class:`FileState` class.

        However, to detail how a file transfer begins: when a build slave has
        successfully completed a build it informs the master via the
        :meth:`slave_driver` task. That task replies with a "SEND" instruction
        to the slave (including a filename). The slave then initiates the
        transfer with a "HELLO" message to this task. Once transfers are
        complete the slave sends a "SENT" message to the :meth:`slave_driver`
        task which verifies the transfer and either retries it (when
        verification fails) or sends back "DONE" indicating the slave can wipe
        the source file.
        """
        ctx = zmq.Context.instance()
        quit_queue = ctx.socket(zmq.SUB)
        quit_queue.connect('inproc://quit')
        quit_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        file_queue = ctx.socket(zmq.ROUTER)
        file_queue.ipv6 = True
        file_queue.hwm = TransferState.pipeline_size * 50
        file_queue.bind('tcp://*:5556')
        try:
            while not quit_queue.poll(0):
                if not file_queue.poll(1000):
                    continue
                address, msg, *args = file_queue.recv_multipart()

                try:
                    transfer = self.transfers[address]

                except KeyError:
                    if msg == b'CHUNK':
                        logging.debug('Ignoring redundant CHUNK from prior transfer')
                        continue
                    elif msg != b'HELLO':
                        logging.error('Invalid start transfer from slave: %s', msg)
                        continue
                    try:
                        slave_id = int(args[0])
                        # XXX Yucky; in fact the whole "transfer state generated
                        # by the slave thread then passed to the transfer
                        # thread" is crap. Would be slightly nicer to ... ?
                        slave = [
                            slave for slave in self.slaves.values()
                            if slave.slave_id == slave_id
                        ][0]
                    except ValueError:
                        logging.error('Invalid slave_id during start transfer: %s', args[0])
                        continue
                    except IndexError:
                        logging.error('Unknown slave_id during start transfer: %d', slave_id)
                        continue
                    transfer = slave.transfer
                    if transfer is None:
                        logging.error('No active transfer for slave: %d', slave_id)
                    self.transfers[address] = transfer

                else:
                    if msg == b'CHUNK':
                        transfer.chunk(int(args[0].decode('ascii')), args[1])
                        if transfer.done:
                            file_queue.send_multipart([address, b'DONE'])
                            del self.transfers[address]
                            continue

                    elif msg == b'HELLO':
                        # This only happens if we've dropped a *lot* of packets,
                        # and the slave's timed out waiting for another FETCH.
                        # In this case reset the amount of "credit" on the
                        # transfer so it can start fetching again
                        # XXX Should check slave ID reported in HELLO matches
                        # the slave retrieved from the cache
                        transfer.reset_credit()

                    else:
                        logging.error('Invalid chunk header from slave: %s', msg)
                        # XXX Delete the transfer object?
                        # XXX Remove transfer from slave?

                fetch_range = transfer.fetch()
                while fetch_range:
                    file_queue.send_multipart([
                        address, b'FETCH',
                        str(fetch_range.start).encode('ascii'),
                        str(len(fetch_range)).encode('ascii')
                    ])
                    fetch_range = transfer.fetch()
        finally:
            file_queue.close()
            quit_queue.close()

    def build_armv6l_hack(self, db, build):
        # NOTE: dirty hack; if the build contains any arch-specific wheels for
        # armv7l, link armv6l name to the armv7l file and stick some entries
        # in the database for them.
        for file in list(build.files.values()):
            if file.platform_tag == 'linux_armv7l':
                arm7_path = (
                    TransferState.output_path / 'simple' / build.package /
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

    def index_scribbler(self):
        """
        This task is responsible for writing web-page ``index.html`` files. It
        reads the names of packages off the internal "indexes" queue and
        rebuilds the ``index.html`` for that package and, optionally, the
        overall ``index.html`` if the package is one that wasn't previously
        present.

        .. note::

            It is important to note that package names are never pushed into the
            internal "indexes" queue until all file-transfers associated with
            the build are complete. Furthermore, while the entire index for a
            package is re-built, hashes are *never* re-calculated from the disk
            files (they are always read from the database).
        """
        ctx = zmq.Context.instance()
        quit_queue = ctx.socket(zmq.SUB)
        quit_queue.connect('inproc://quit')
        quit_queue.setsockopt_string(zmq.SUBSCRIBE, 'QUIT')
        index_queue = ctx.socket(zmq.PULL)
        index_queue.hwm = 10
        index_queue.connect('inproc://indexes')
        try:
            # Build the initial index from the set of directories that exist
            # under the output path (this is much faster than querying the
            # database for the same info)
            packages = {
                str(d.relative_to(TransferState.output_path / 'simple'))
                for d in (TransferState.output_path / 'simple').iterdir()
                if d.is_dir()
            }

            with PiWheelsDatabase(self.db_engine, self.pypi_root) as db:
                while not quit_queue.poll(0):
                    if not index_queue.poll(1000):
                        continue
                    package = index_queue.recv_string()
                    if package not in packages:
                        packages.add(package)
                        self.write_root_index(packages)
                    self.write_package_index(package, db.get_package_files(package))
        finally:
            index_queue.close()
            quit_queue.close()

    def write_homepage(self, status_info):
        with tempfile.NamedTemporaryFile(
                mode='w', dir=str(TransferState.output_path),
                delete=False) as index:
            try:
                index.file.write(self.homepage_template.format(
                    packages_built=status_info['packages_built'],
                    versions_built=status_info['versions_built'],
                    builds_time=timedelta(seconds=status_info['builds_time']),
                    builds_size=status_info['builds_size'] // 1048576
                ))
            except:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o664)
                os.replace(index.name, str(TransferState.output_path /
                                           'index.html'))

    def write_root_index(self, packages):
        with tempfile.NamedTemporaryFile(
                mode='w', dir=str(TransferState.output_path / 'simple'),
                delete=False) as index:
            try:
                index.file.write('<!DOCTYPE html>\n')
                index.file.write(
                    tag.html(
                        tag.head(
                            tag.title('Pi Wheels Simple Index'),
                            tag.meta(name='api-version', value=2),
                        ),
                        tag.body(
                            (tag.a(package, href=package), tag.br())
                            for package in packages
                        )
                    )
                )
            except:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o644)
                os.replace(index.name, str(TransferState.output_path /
                                           'simple' / 'index.html'))

    def write_package_index(self, package, files):
        with tempfile.NamedTemporaryFile(
                mode='w', dir=str(TransferState.output_path /
                                  'simple' / package),
                delete=False) as index:
            try:
                index.file.write('<!DOCTYPE html>\n')
                index.file.write(
                    tag.html(
                        tag.head(
                            tag.title('Links for {}'.format(package))
                        ),
                        tag.body(
                            tag.h1('Links for {}'.format(package)),
                            (
                                (tag.a(rec.filename,
                                       href='{rec.filename}#sha256={rec.filehash}'.format(rec=rec),
                                       rel='internal'), tag.br())
                                for rec in files
                            )
                        )
                    )
                )
            except:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o644)
                os.replace(index.name, str(TransferState.output_path /
                                           'simple' / package / 'index.html'))


main = PiWheelsMaster()
