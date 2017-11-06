from datetime import datetime, timedelta

import zmq

from .tasks import PauseableTask
from .db import Database
from .file_juggler import FsClient


class BigBrother(PauseableTask):
    """
    This task periodically queries the database and output file-system for
    various statistics like the number of packages known to the system, the
    number built, the number of packages built in the last hour, the remaining
    file-system space, etc. These statistics are written to the internal
    "status" queue which :meth:`main` uses to pass statistics to any listening
    monitors.
    """
    name = 'master.big_brother'

    def __init__(self, config):
        super().__init__(config)
        status_queue = self.ctx.socket(zmq.PUSH)
        status_queue.hwm = 1
        status_queue.connect(config['int_status_queue'])
        index_queue = self.ctx.socket(zmq.PUSH)
        index_queue.hwm = 1
        index_queue.connect(config['index_queue'])
        self.register(status_queue, self.handle_status, zmq.POLLOUT)
        self.register(index_queue, self.handle_index, zmq.POLLOUT)
        self.fs = FsClient(config)
        self.db = Database(config['database'])
        self.timestamp = datetime.utcnow() - timedelta(seconds=30)
        self.status_info1 = None
        self.status_info2 = None

    def loop(self):
        # The big brother task is not reactive; it just pumps out stats
        # every 30 seconds (at most)
        if datetime.utcnow() - self.timestamp > timedelta(seconds=30):
            self.timestamp = datetime.utcnow()
            stat = self.fs.statvfs()
            rec = self.db.get_statistics()
            self.status_info1 = self.status_info2 = {
                    'packages_count':   rec.packages_count,
                    'packages_built':   rec.packages_built,
                    'versions_count':   rec.versions_count,
                    'versions_built':   rec.versions_built,
                    'builds_count':     rec.builds_count,
                    'builds_last_hour': rec.builds_count_last_hour,
                    'builds_success':   rec.builds_count_success,
                    'builds_time':      rec.builds_time,
                    'builds_size':      rec.builds_size,
                    'disk_free':        stat.f_frsize * stat.f_bavail,
                    'disk_size':        stat.f_frsize * stat.f_blocks,
                }

    def handle_index(self, q):
        if self.status_info1 is not None:
            q.send_pyobj(['HOME', self.status_info1])
            self.status_info1 = None

    def handle_status(self, q):
        if self.status_info2 is not None:
            q.send_pyobj([-1, self.timestamp, 'STATUS', self.status_info2])
            self.status_info2 = None
