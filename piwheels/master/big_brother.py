from datetime import datetime

import zmq

from .tasks import PauseableTask
from .file_juggler import FsClient
from .the_oracle import DbClient


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

    def __init__(self, **config):
        super().__init__(**config)
        self.status_queue = self.ctx.socket(zmq.PUSH)
        self.status_queue.hwm = 1
        self.status_queue.connect(config['int_status_queue'])
        self.index_queue = self.ctx.socket(zmq.PUSH)
        self.index_queue.hwm = 10
        self.index_queue.connect(config['index_queue'])
        self.fs = FsClient(**config)
        self.db = DbClient(**config)

    def close(self):
        super().close()
        self.db.close()
        self.fs.close()
        self.index_queue.close()
        self.status_queue.close()

    def loop(self):
        # The big brother task is not reactive; it just pumps out stats
        # continually
        stat = self.fs.statvfs()
        rec = self.db.get_statistics()
        status_info = {
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
        self.index_queue.send_pyobj(['HOME', status_info])
        self.status_queue.send_pyobj([
            -1,
            datetime.utcnow(),
            'STATUS',
            status_info
        ])
