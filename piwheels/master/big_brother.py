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

from datetime import datetime, timedelta, timezone

from .. import const, protocols, transport, tasks
from .the_oracle import DbClient
from .file_juggler import FsClient


UTC = timezone.utc


class BigBrother(tasks.PauseableTask):
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
            'packages_built':        0,
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
            'downloads_all':         0,
        }
        self.timestamp = datetime.now(tz=UTC) - timedelta(seconds=40)
        stats_queue = self.socket(
            transport.PULL, protocol=protocols.big_brother)
        stats_queue.hwm = 10
        stats_queue.bind(config.stats_queue)
        self.register(stats_queue, self.handle_stats)
        self.status_queue = self.socket(
            transport.PUSH, protocol=protocols.monitor_stats)
        self.status_queue.hwm = 10
        self.status_queue.connect(const.INT_STATUS_QUEUE)
        self.web_queue = self.socket(
            transport.PUSH, protocol=reversed(protocols.the_scribe))
        self.web_queue.hwm = 10
        self.web_queue.connect(config.web_queue)
        self.db = DbClient(config, self.logger)

    def close(self):
        self.db.close()
        super().close()

    def handle_stats(self, queue):
        try:
            msg, data = queue.recv_msg()
        except IOError as e:
            self.logger.error(str(e))
        else:
            if msg == 'STATFS':
                f_frsize, f_bavail, f_blocks = data
                self.stats['disk_free'] = f_frsize * f_bavail
                self.stats['disk_size'] = f_frsize * f_blocks
            elif msg == 'STATBQ':
                self.stats['builds_pending'] = sum(data.values())
            elif msg == 'HOME':
                # Forced rebuild from Mr. Chase
                self.timestamp = datetime.now(tz=UTC) - timedelta(seconds=40)

    def loop(self):
        # The big brother task is not reactive; it just pumps out stats
        # every 30 seconds (at most)
        if datetime.now(tz=UTC) - self.timestamp > timedelta(seconds=30):
            self.timestamp = datetime.now(tz=UTC)
            rec = self.db.get_statistics()
            # Rename a couple of columns
            rec['builds_last_hour'] = rec.pop('builds_count_last_hour')
            rec['builds_success'] = rec.pop('builds_count_success')
            self.stats.update(rec)
            self.web_queue.send_msg('HOME', self.stats)
            self.status_queue.send_msg('STATS', self.stats)
            self.web_queue.send_msg('SEARCH', self.db.get_search_index())
