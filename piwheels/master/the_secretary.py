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

from datetime import datetime, timedelta, timezone
from collections import deque, namedtuple

from .. import const, protocols, tasks, transport
from .the_oracle import DbClient


UTC = timezone.utc
IndexTask = namedtuple('IndexTask', ('package', 'timestamp'))


class TheSecretary(tasks.PausingTask):
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
        self.paused = False
        self.buffer = deque()
        self.commands = {}
        if config.dev_mode:
            self.timeout = timedelta(seconds=3)
        else:
            self.timeout = timedelta(minutes=1)
        web_queue = self.socket(
            transport.REP, protocol=protocols.the_scribe)
        web_queue.bind(config.web_queue)
        self.register(web_queue, self.handle_input)
        self.output = self.socket(
            transport.REQ, protocol=reversed(protocols.the_scribe))
        self.output.connect(const.SCRIBE_QUEUE)
        self.every(timedelta(seconds=1), self.handle_output)
        self.db = DbClient(config, self.logger)

    def close(self):
        # Store the internal buffer in the database ...
        self.logger.info('storing queued jobs')
        self.db.save_rewrites_pending([
            (package, added_at, self.commands[package])
            for package, added_at in self.buffer
        ])
        self.db.close()
        super().close()

    def once(self):
        # ... and re-load it when we next start up
        self.logger.info('loading queued jobs')
        queue = self.db.load_rewrites_pending()
        for item in queue:
            self.buffer.append(IndexTask(item.package, item.added_at))
            self.commands[item.package] = item.command

    def handle_input(self, queue):
        """
        Handle incoming write requests with buffering and de-dupe.

        Some incoming requests (currently "HOME", "SEARCH", "DELPKG", and
        "DELVER") are passed directly through to :class:`TheScribe` as these
        are either sufficiently rare ("HOME", "SEARCH") that no benefit is
        gained by buffering them or sufficiently urgent ("DELPKG", "DELVER")
        that they must be acted on immediately.

        For other requests ("PROJECT" and "BOTH"), requests can come thick
        and fast in the case of multiple file registrations picked up by
        :class:`CloudGazer`. In this case, requests are buffered for a minute
        and de-duplicated; e.g. if several requests are made to re-write the
        project page for package "foo" within that period, they will be
        combined into a single request. After the minute of buffering, the
        request is passed down to :class:`TheScribe`.
        """
        try:
            msg, data = queue.recv_msg()
        except IOError as e:
            self.logger.error(str(e))
        else:
            if msg in ('HOME', 'SEARCH', 'DELPKG', 'DELVER'):
                self.output.send_msg(msg, data)
                if msg in ('DELPKG', 'DELVER'):
                    # Expunge any pending updates of the package from the
                    # buffer as we're going to do them immediately
                    if msg == 'DELPKG':
                        package, version = data, None
                    else:
                        package, version = data
                    try:
                        del self.commands[package]
                    except KeyError:
                        pass
                    else:
                        for index, entry in enumerate(self.buffer):
                            if entry.package == package:
                                del self.buffer[index]
                                break
                self.output.recv_msg()
            elif msg in ('PROJECT', 'BOTH'):
                package = data
                if package in self.commands:
                    if msg == 'BOTH':
                        # "Upgrade" PROJECT messages to BOTH but leave the
                        # timestamp alone
                        self.commands[package] = msg
                else:
                    self.buffer.append(IndexTask(package, datetime.now(tz=UTC)))
                    self.commands[package] = msg
            queue.send_msg('DONE')

    def handle_output(self):
        """
        Passes buffered requests downstream.

        This sub-task runs periodically to pluck things from the internal
        buffer that have reached the minute delay, and passes them downstream
        to :class:`TheScribe`. The process stops when we run out of things that
        have expired.
        """
        now = datetime.now(tz=UTC)
        while (
                not self.paused and
                self.buffer and
                (now - self.buffer[0].timestamp > self.timeout)
        ):
            package = self.buffer.popleft().package
            message = self.commands.pop(package)
            self.output.send_msg(message, package)
            self.output.recv_msg()
