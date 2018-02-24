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
        status_queue = self.ctx.socket(zmq.PUSH)
        status_queue.hwm = 1
        status_queue.connect(const.INT_STATUS_QUEUE)
        index_queue = self.ctx.socket(zmq.PUSH)
        index_queue.hwm = 1
        index_queue.connect(config.index_queue)
        self.register(status_queue, self.handle_status, zmq.POLLOUT)
        self.register(index_queue, self.handle_index, zmq.POLLOUT)
        self.fs = FsClient(config)
        self.db = DbClient(config)
        self.timestamp = datetime.utcnow() - timedelta(seconds=60)
        self.status_info1 = None
        self.status_info2 = None
        self.search_index = None

    def loop(self):
        # The big brother task is not reactive; it just pumps out stats
        # every minute (at most)
        if datetime.utcnow() - self.timestamp > timedelta(seconds=60):
            self.timestamp = datetime.utcnow()
            stat = self.fs.statvfs()
            rec = self.db.get_statistics()
            self.status_info1 = self.status_info2 = {
                'packages_count':        rec.packages_count,
                'packages_built':        rec.packages_built,
                'versions_count':        rec.versions_count,
                'versions_tried':        rec.versions_tried,
                'builds_count':          rec.builds_count,
                'builds_last_hour':      rec.builds_count_last_hour,
                'builds_success':        rec.builds_count_success,
                'builds_time':           rec.builds_time,
                'builds_size':           rec.builds_size,
                'files_count':           rec.files_count,
                'disk_free':             stat.f_frsize * stat.f_bavail,
                'disk_size':             stat.f_frsize * stat.f_blocks,
                'downloads_last_month':  rec.downloads_last_month,
            }
            rec = self.db.get_downloads_recent()
            self.search_index = [
                (name, count)
                for name, count in rec.items()
            ]

    def handle_index(self, queue):
        """
        Handler for the index_queue. Whenever a slot becomes available, and an
        updated status_info1 package is available, send a message to update the
        home page.
        """
        if self.status_info1 is not None:
            queue.send_pyobj(['HOME', self.status_info1])
            self.status_info1 = None
        elif self.search_index is not None:
            queue.send_pyobj(['SEARCH', self.search_index])
            self.search_index = None

    def handle_status(self, queue):
        """
        Handler for the internal status queue. Whenever a slot becomes
        available, and an updated status_info2 package is available, send a
        message with the latest status (ultimately this winds up going to any
        attached monitors via the external status queue).
        """
        if self.status_info2 is not None:
            queue.send_pyobj([-1, self.timestamp, 'STATUS', self.status_info2])
            self.status_info2 = None
