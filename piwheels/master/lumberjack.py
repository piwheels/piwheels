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
Defines the :class:`Lumberjack` task; see class for more details.

.. autoclass:: Lumberjack
    :members:
"""

from datetime import timedelta

from .. import protocols, transport, tasks
from ..states import (
    DownloadState, SearchState, ProjectState, JSONState, PageState)
from .the_oracle import DbClient


class Lumberjack(tasks.PauseableTask):
    """
    This task handles incoming log entries from the httpd server, and updates
    the database with them. The external :program:`piw-logger` script handles
    parsing the raw log entries into the format expected by this task, so this
    is an extremely basic class.
    """
    name = 'master.lumberjack'

    def __init__(self, config):
        super().__init__(config)
        log_queue = self.socket(
            transport.PULL, protocol=protocols.lumberjack)
        log_queue.bind(config.log_queue)
        self.register(log_queue, self.handle_log)
        self.db = DbClient(config, self.logger)
        self.access_handlers = {
            'LOGDOWNLOAD': (DownloadState, self.db.log_download, 'downloads'),
            'LOGSEARCH':   (SearchState,   self.db.log_search,   'searches'),
            'LOGPROJECT':  (ProjectState,  self.db.log_project,  'project hits'),
            'LOGJSON':     (JSONState,     self.db.log_json,     'JSON hits'),
            'LOGPAGE':     (PageState,     self.db.log_page,     'page hits'),
        }
        self.counters = {msg: 0 for msg in self.access_handlers}
        self.every(timedelta(minutes=1), self.log_counters)

    def close(self):
        self.db.close()
        super().close()

    def log_counters(self):
        """
        Periodically prints the aggregated hit counters and resets them.
        """
        for msg, count in self.counters.items():
            if count:
                self.logger.info('logged %d %s in the last minute',
                                 count, self.access_handlers[msg][2])
        self.counters = {msg: 0 for msg in self.access_handlers}

    def handle_log(self, queue):
        """
        Handle requests from :program:`piw-logger` instances.

        See the :doc:`development` chapter for an overview of the protocol for
        messages between the logger and the :class:`Lumberjack`.
        """
        try:
            msg, data = queue.recv_msg()
        except IOError as e:
            self.logger.error(str(e))
        else:
            state_cls, handler, label = self.access_handlers[msg]
            handler(state_cls.from_message(data))
            self.counters[msg] += 1
