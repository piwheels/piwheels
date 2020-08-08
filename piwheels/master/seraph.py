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
Defines the :class:`Seraph` task; see class for more details.

.. autoclass:: Seraph
    :members:
"""

from .. import const, tasks, transport


class Seraph(tasks.NonStopTask):
    """
    This task is a simple load-sharing router for
    :class:`~.the_oracle.TheOracle` tasks.
    """
    name = 'master.seraph'

    def __init__(self, config):
        super().__init__(config)
        self.front_queue = self.socket(transport.ROUTER)
        self.front_queue.bind(config.db_queue)
        self.back_queue = self.socket(transport.ROUTER)
        self.back_queue.bind(const.ORACLE_QUEUE)
        self.workers = []
        self.register(self.front_queue, self.handle_front)
        self.register(self.back_queue, self.handle_back)

    def handle_front(self, queue):
        """
        If any workers are currently available, receive
        :class:`~.the_oracle.DbClient` requests from the front queue and send
        it on to the worker including the client's address frame.
        """
        if self.workers:
            client, _, request = queue.recv_multipart()
            worker = self.workers.pop(0)
            self.back_queue.send_multipart([worker, _, client, _, request])

    def handle_back(self, queue):
        """
        Receive a response from an instance of :class:`~.the_oracle.TheOracle`
        on the back queue. Strip off the worker's address frame and add it back
        to the available queue then send the response back to the client that
        made the original request.
        """
        worker, _, *msg = queue.recv_multipart()
        self.workers.append(worker)
        if msg != [b'READY']:
            self.front_queue.send_multipart(msg)
