import tempfile
from datetime import datetime
from pathlib import Path

import zmq
from pkg_resources import resource_string

from .tasks import PausableTask, DatabaseMixin, TaskQuit


class BigBrother(PausableTask, DatabaseMixin):
    """
    This task periodically queries the database and output file-system for
    various statistics like the number of packages known to the system, the
    number built, the number of packages built in the last hour, the remaining
    file-system space, etc. These statistics are written to the internal
    "status" queue which :meth:`main` uses to pass statistics to any listening
    monitors.
    """
    def __init__(self, *, status_queue='inproc://status',
                 output_path=Path('/var/www'), **kwargs):
        super().__init__(**kwargs)
        self.homepage_template = resource_string(__name__, 'index.template.html').decode('utf-8')
        self.output_path = output_path
        self.status_queue = ctx.socket(zmq.PUSH)
        self.status_queue.hwm = 1
        self.status_queue.connect(status_queue)

    def run(self):
        try:
            while True:
                stat = os.statvfs(str(self.output_path))
                rec = self.db.get_statistics()
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
                self.status_queue.send_json([
                    -1,
                    datetime.utcnow().timestamp(),
                    'STATUS',
                    status_info
                ])
                self.handle_control(int_control_queue, 10000)
        except TaskQuit:
            pass

    def write_homepage(self, status_info):
        with tempfile.NamedTemporaryFile(mode='w', dir=str(self.output_path),
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
                os.replace(index.name, str(self.output_path / 'index.html'))

