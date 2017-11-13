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

"Defines :class:`TheArchitect` task; see class for more details"

from collections import deque, defaultdict
from datetime import datetime, timedelta

import zmq

from .tasks import Task
from .db import Database


class TheArchitect(Task):
    """
    This task queries the backend database to determine which versions of
    packages have yet to be built (and aren't marked to be skipped). It places
    a tuple of (package, version) for each such build into the internal
    "builds" queue for :class:`SlaveDriver` to read.
    """
    name = 'master.the_architect'

    def __init__(self, config):
        super().__init__(config)
        self.db = Database(config.dsn)
        builds_queue = self.ctx.socket(zmq.REP)
        builds_queue.hwm = 1
        builds_queue.bind(config.builds_queue)
        self.query = None
        self.timestamp = datetime.utcnow() - timedelta(seconds=30)
        self.abi_queues = defaultdict(lambda: deque(maxlen=1000))
        self.register(builds_queue, self.handle_builds)

    def loop(self):
        """
        The architect simply runs the build queue query repeatedly. On each
        loop iteration, an entry from the result set is added to the relevant
        ABI queue. The queues are limited in length to prevent silly memory
        usage on the initial run (which will involve millions of entries). This
        does mean that a single loop over the query will potentially miss
        entries, but that's fine as it'll just be repeated again.
        """
        if self.query is None:
            # Leave a gap of 30 seconds between query re-runs; the builds queue
            # query is quite heavy and when we're at the end of a run it's
            # better to let new entries build up for a bit before we squirt
            # them into the queues rather than waste time restarting the query
            # again and again
            if datetime.utcnow() - self.timestamp > timedelta(seconds=30):
                self.query = self.db.get_build_queue()
        else:
            try:
                row = next(self.query)
                self.abi_queues[row.abi_tag].append((row.package, row.version))
            except StopIteration:
                self.query = None
                self.timestamp = datetime.utcnow()

    def handle_builds(self, queue):
        """
        Handler for the task's builds queue. Whenever a build slave asks
        :class:`SlaveDriver` for a new task, :class:`SlaveDriver` passes the
        slave's ABI to :class:`TheArchitect` via this queue. We simply pop the
        first entry (if any) off the relevant queue and send it back.
        """
        abi = queue.recv_pyobj()
        try:
            queue.send_pyobj(self.abi_queues[abi].popleft())
        except IndexError:
            queue.send_pyobj(None)
