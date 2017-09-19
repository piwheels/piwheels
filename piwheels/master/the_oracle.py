import errno
import logging
from datetime import timedelta
from collections import namedtuple

import zmq
import zmq.error

from .tasks import Task, TaskQuit
from .states import BuildState, FileState
from .db import Database


logger = logging.getLogger('master.the_oracle')


class TheOracle(Task):
    """
    This task provides an RPC-like interface to the database; it handles
    requests such as registering a new package, version, or build, and answering
    queries about the hashes of files. The primary clients of this class are
    :class:`SlaveDriver`, :class:`IndexScribe`, and :class:`CloudGazer`.
    """
    def __init__(self, **config):
        super().__init__(**config)
        self.db = Database(config['database'])
        self.db_queue = self.ctx.socket(zmq.REP)
        self.db_queue.hwm = 10
        self.db_queue.bind(config['db_queue'])

    def close(self):
        super().close()
        self.db_queue.close(linger=1000)
        self.db.close()
        logger.info('closed')

    def run(self):
        logger.info('starting')
        poller = zmq.Poller()
        try:
            poller.register(self.control_queue, zmq.POLLIN)
            poller.register(self.db_queue, zmq.POLLIN)
            while True:
                socks = dict(poller.poll(1000))
                if self.db_queue in socks:
                    self.handle_db_request()
                if self.control_queue in socks:
                    self.handle_control()
        except TaskQuit:
            pass

    def handle_db_request(self):
        msg, *args = self.db_queue.recv_pyobj()
        try:
            handler = getattr(self, 'do_%s' % msg)
            result = handler(*args)
        except Exception as e:
            logger.error('Error handling db request: %s', msg)
            # REP *must* send a reply even when stuff goes wrong
            # otherwise the send/recv cycle that REQ/REP depends
            # upon breaks
            self.db_queue.send_pyobj(['ERR', str(e)])
        else:
            self.db_queue.send_pyobj(['OK', result])

    def do_ALLPKGS(self):
        return self.db.get_all_packages()

    def do_ALLVERS(self):
        return self.db.get_all_package_versions()

    def do_NEWPKG(self, package):
        self.db.add_new_package(package)

    def do_NEWVER(self, package, version):
        self.db.add_new_package_version(package, version)

    def do_LOGBUILD(self, slave_id, package, version, status, duration, output,
                    files):
        build = BuildState(slave_id, package, version, status, duration, output,
                           files={
                               filename: FileState(filename, *filestate)
                               for filename, filestate in files.items()
                           })
        self.db.log_build(build)
        return build.build_id

    def do_PKGFILES(self, package):
        files = self.db.get_package_files(package)
        return list(files)

    def do_GETPYPI(self):
        return self.db.get_pypi_serial()

    def do_SETPYPI(self, serial):
        self.db.set_pypi_serial(serial)

    def do_GETSTATS(self):
        rec = self.db.get_statistics()
        return [
            (k, v if not isinstance(v, timedelta) else v.total_seconds())
            for k, v in zip(rec.keys(), rec.values())
        ]


class DbClient:
    StatsType = None

    def __init__(self, **config):
        self.ctx = zmq.Context.instance()
        self.db_queue = self.ctx.socket(zmq.REQ)
        self.db_queue.hwm = 1
        self.db_queue.connect(config['db_queue'])

    def close(self):
        self.db_queue.close()

    def _execute(self, msg):
        # If sending blocks this either means we're shutting down, or
        # something's gone horribly wrong (either way, raising EAGAIN is fine)
        self.db_queue.send_pyobj(msg, flags=zmq.NOBLOCK)
        status, result = self.db_queue.recv_pyobj()
        if status == 'OK':
            if result is not None:
                return result
        else:
            raise IOError(result)

    def get_all_packages(self):
        return self._execute(['ALLPKGS'])

    def get_all_package_versions(self):
        # Repackage [p, v] as (p, v)
        return [(p, v) for p, v in self._execute(['ALLVERS'])]

    def add_new_package(self, package):
        self._execute(['NEWPKG', package])

    def add_new_package_version(self, package, version):
        self._execute(['NEWVER', package, version])

    def log_build(self, build):
        build_id = self._execute([
            'LOGBUILD', build.slave_id, build.package, build.version,
            build.status, build.duration, build.output, {
                f.filename: [
                    f.filename, f.filesize, f.filehash, f.package_version_tag,
                    f.py_version_tag, f.abi_tag, f.platform_tag
                ]
                for f in build.files.values()
            }])
        build.logged(build_id)

    def get_package_files(self, package):
        return self._execute(['PKGFILES', package])

    def get_pypi_serial(self):
        return self._execute(['GETPYPI'])

    def set_pypi_serial(self, serial):
        self._execute(['SETPYPI', serial])

    def get_statistics(self):
        rec = self._execute(['GETSTATS'])
        if self.StatsType is None:
            self.StatsType = namedtuple('Statistics', tuple(k for k, v in rec))
        return self.StatsType(**rec)
