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
Defines the :class:`BigBrother` task; see class for more details.

.. autoclass:: BigBrother
    :members:
"""

from datetime import datetime, timedelta

import zmq

from .. import const
from .tasks import PauseableTask
from .the_oracle import DbClient
from .file_juggler import FsClient


class BigBrother(PauseableTask):
    """
    This task periodically queries the database and output file-system for
    various statistics like the number of packages known to the system, the
    number built, the number of packages built in the last hour, the remaining
    file-system space, etc. These statistics are written to the internal
    "status" queue which :meth:`~.PiWheelsMaster.main_loop` uses to pass
    statistics to any listening monitors.
    """
    name = 'master.big_brother'

    def __init__(self, config):
        super().__init__(config)
        self.stats = {
            'packages_count':        0,
            'packages_built':        0,
            'versions_count':        0,
            'builds_count':          0,
            'builds_last_hour':      0,
            'builds_success':        0,
            'builds_time':           timedelta(0),
            'builds_size':           0,
            'builds_pending':        0,
            'files_count':           0,
            'disk_free':             0,
            'disk_size':             1,
            'downloads_last_month':  0,
        }
        self.timestamp = datetime.utcnow() - timedelta(seconds=40)
        stats_queue = self.ctx.socket(zmq.PULL)
        stats_queue.hwm = 10
        stats_queue.bind(config.stats_queue)
        self.register(stats_queue, self.handle_stats)
        self.status_queue = self.ctx.socket(zmq.PUSH)
        self.status_queue.hwm = 10
        self.status_queue.connect(const.INT_STATUS_QUEUE)
        self.web_queue = self.ctx.socket(zmq.PUSH)
        self.web_queue.hwm = 10
        self.web_queue.connect(config.web_queue)
        self.db = DbClient(config)

    def close(self):
        self.db.close()
        self.web_queue.close()
        self.status_queue.close()
        super().close()

    def handle_stats(self, queue):
        msg, *args = queue.recv_pyobj()
        if msg == 'STATFS':
            self.stats['disk_free'] = args[0].f_frsize * args[0].f_bavail
            self.stats['disk_size'] = args[0].f_frsize * args[0].f_blocks
        elif msg == 'STATBQ':
            self.stats['builds_pending'] = sum(args[0].values())
        else:
            self.logger.error('invalid big_brother message: %s', msg)

    def loop(self):
        # The big brother task is not reactive; it just pumps out stats
        # every 30 seconds (at most)
        if datetime.utcnow() - self.timestamp > timedelta(seconds=30):
            self.timestamp = datetime.utcnow()
            rec = self.db.get_statistics()
            self.stats['packages_count'] = rec.packages_count
            self.stats['packages_built'] = rec.packages_built
            self.stats['versions_count'] = rec.versions_count
            self.stats['builds_count'] = rec.builds_count
            self.stats['builds_last_hour'] = rec.builds_count_last_hour
            self.stats['builds_success'] = rec.builds_count_success
            self.stats['builds_time'] = rec.builds_time
            self.stats['builds_size'] = rec.builds_size
            self.stats['files_count'] = rec.files_count
            self.stats['downloads_last_month'] = rec.downloads_last_month
            self.web_queue.send_pyobj(['HOME', self.stats])
            self.status_queue.send_pyobj([-1, self.timestamp, 'STATUS', self.stats])
            rec = self.db.get_downloads_recent()
            search_index = [
                (name, count)
                for name, count in rec.items()
            ]
            self.web_queue.send_pyobj(['SEARCH', search_index])
