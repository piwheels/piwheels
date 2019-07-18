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

import os
from collections import deque
from datetime import datetime, timedelta, timezone

from .. import const, protocols, transport, tasks, info
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
        self.history = deque(maxlen=100)
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
            'mem_free':              0,
            'mem_size':              0,
            'temperature':           0.0,
            'load_average':          0.0,
        }
        self.last_info_run = self.last_stats_run = self.last_search_run = (
            datetime.now(tz=UTC) - timedelta(minutes=10))
        stats_queue = self.socket(
            transport.PULL, protocol=protocols.big_brother)
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
                disk_size, disk_free = data
                self.stats['disk_free'] = disk_free
                self.stats['disk_size'] = disk_size
            elif msg == 'STATBQ':
                self.stats['builds_pending'] = data
            elif msg == 'HOME':
                # Forced rebuild from Mr. Chase
                self.last_search_run = datetime.now(tz=UTC) - timedelta(minutes=10)

    def loop(self):
        # Leave 10 seconds between each run of mem/temp stats
        if datetime.now(tz=UTC) - self.last_info_run > timedelta(seconds=10):
            mem_size, mem_free = info.get_mem_stats()
            self.stats['mem_size'] = mem_size
            self.stats['mem_free'] = mem_free
            self.stats['temperature'] = info.get_cpu_temp()
            self.stats['load_average'] = os.getloadavg()[0]
            self.history.append(self.stats.copy())
            self.status_queue.send_msg('STATS', self.stats)
            self.last_info_run = datetime.now(tz=UTC)
        # Leave 30 seconds between each run of the db stats
        if datetime.now(tz=UTC) - self.last_stats_run > timedelta(seconds=30):
            rec = self.db.get_statistics()
            self.stats.update(rec)
            self.web_queue.send_msg('HOME', self.stats)
            self.last_stats_run = datetime.now(tz=UTC)
        # Leave 5 minutes between each run of the (expensive) search index
        if datetime.now(tz=UTC) - self.last_search_run > timedelta(minutes=5):
            self.web_queue.send_msg('SEARCH', self.db.get_search_index())
            self.last_search_run = datetime.now(tz=UTC)
