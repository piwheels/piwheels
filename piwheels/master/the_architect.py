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
Defines :class:`TheArchitect` task; see class for more details.

.. autoclass:: TheArchitect
    :members:
"""

from datetime import datetime, timedelta

from .. import protocols, tasks, transport
from .db import Database


class TheArchitect(tasks.Task):
    """
    This task queries the backend database to determine which versions of
    packages have yet to be built (and aren't marked to be skipped). It pushes
    the results to :class:`~.slave_driver.SlaveDriver` to sort out.
    """
    name = 'master.the_architect'

    def __init__(self, config):
        super().__init__(config)
        self.db = Database(config.dsn)
        self.last_run = datetime(1970, 1, 1)
        self.builds_queue = self.ctx.socket(
            transport.PUSH, protocol=protocols.the_architect)
        self.builds_queue.hwm = 10
        self.builds_queue.connect(config.builds_queue)

    def close(self):
        self.db.close()
        self.builds_queue.close()
        super().close()

    def loop(self):
        """
        The architect simply runs the build queue query repeatedly, with a
        break of 60 seconds between each execution. The query is limited (in
        :class:`~.db.Database`) to 1000 entries per build ABI.

        All entries found within this limit are sorted into per-ABI queues and
        pushed to :class:`~.slave_driver.SlaveDriver` which queues and
        dispatches jobs to build ABI-matched slaves as they become available.
        """
        # Leave 60 seconds between each run of the (expensive) builds
        # pending query
        if datetime.utcnow() - self.last_run > timedelta(seconds=60):
            self.builds_queue.send_msg('QUEUE', self.db.get_build_queue())
            self.last_run = datetime.utcnow()
