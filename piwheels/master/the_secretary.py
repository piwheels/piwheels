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
Defines the :class:`TheSecretary` task; see class for more details.

.. autoclass:: TheSecretary
    :members:
"""

from datetime import datetime, timedelta
from collections import deque, namedtuple

import zmq

from .. import const
from .tasks import PauseableTask


IndexTask = namedtuple('IndexTask', ('package', 'timestamp'))


class TheSecretary(PauseableTask):
    """
    This task buffers requests for the scribe, for the purpose of consolidating
    multiple consecutive (duplicate) requests.

    Requests to write the project page for a package (which is a relatively
    expensive operation in terms of database accesses) can come in thick and
    fast, particularly when a new version is being registered with lots of
    files. There's little point in writing the project page 5 times in as many
    seconds, or writing the project page, then the index and project page
    immediately afterward. This class is used to buffer requests for up to a
    minute, allowing us to eliminate many of the duplicate requests.
    """
    name = 'master.the_secretary'

    def __init__(self, config):
        super().__init__(config)
        self.buffer = deque()
        self.commands = {}
        web_queue = self.ctx.socket(zmq.PULL)
        web_queue.hwm = 100
        web_queue.bind(config.web_queue)
        self.register(web_queue, self.handle_input)
        self.output = self.ctx.socket(zmq.PUSH)
        self.output.hwm = 100
        self.output.bind(const.SCRIBE_QUEUE)

    def close(self):
        self.output.close()
        super().close()

    def loop(self):
        now = datetime.utcnow()
        while self.buffer:
            first = self.buffer[0]
            if now - first.timestamp > timedelta(minutes=1):
                self.buffer.popleft()
                message = self.commands.pop(first.package)
                self.output.send_pyobj([message, first.package])
            else:
                break

    def handle_input(self, queue):
        msg, *args = queue.recv_pyobj()
        if msg in ['HOME', 'SEARCH']:
            # HOME and SEARCH messages pass-thru immediately without alteration
            # or buffering as they're sufficiently rare
            self.output.send_pyobj([msg] + args)
        elif msg in ['PKGPROJ', 'PKGBOTH']:
            package = args[0]
            if package in self.commands:
                if msg == 'PKGBOTH':
                    # "Upgrade" PKGPROJ messages to PKGBOTH but leave the
                    # timestamp alone
                    self.commands[package] = msg
            else:
                self.buffer.append(IndexTask(package, datetime.utcnow()))
                self.commands[package] = msg
        else:
            self.logger.error('invalid web_queue message: %s', msg)
