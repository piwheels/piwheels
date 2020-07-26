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

from datetime import timedelta

from psycopg2.extensions import QueryCanceledError

from .. import protocols, tasks, transport
from .db import Database


class TheArchitect(tasks.PauseableTask):
    """
    This task queries the backend database to determine which versions of
    packages have yet to be built (and aren't marked to be skipped). It pushes
    the results to :class:`~.slave_driver.SlaveDriver` to sort out.
    """
    name = 'master.the_architect'

    def __init__(self, config):
        super().__init__(config)
        self.db = Database(config.dsn)
        self.builds_queue = self.socket(
            transport.PUSH, protocol=protocols.the_architect)
        self.builds_queue.hwm = 10
        self.builds_queue.connect(config.builds_queue)
        self.every(timedelta(minutes=1), self.update_build_queue)
        self.can_cancel = False

    def close(self):
        self.db.close()
        super().close()

    def quit(self):
        """
        Overridden to cancel any existing long-running query.
        """
        if self.can_cancel:
            self.db._conn.connection.cancel()
        super().quit()

    def update_build_queue(self):
        """
        The architect simply runs the build queue query repeatedly, with a
        break of a minute between each execution.

        All entries found within this limit are sorted into per-ABI queues and
        pushed to :class:`~.slave_driver.SlaveDriver` which queues and
        dispatches jobs to build ABI-matched slaves as they become available.
        """
        self.can_cancel = True
        try:
            self.builds_queue.send_msg(
                'QUEUE', self.db.get_build_queue(100000))
        except QueryCanceledError:
            self.logger.warning('Cancelled query during shutdown')
        finally:
            self.can_cancel = False
