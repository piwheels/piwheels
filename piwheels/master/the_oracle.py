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
Defines :class:`TheOracle` task and the :class:`DbClient` RPC class for talking
to it.

.. autoclass:: TheOracle
    :members:

.. autoclass:: DbClient
    :members:
"""

import inspect
from textwrap import dedent
from datetime import datetime, timezone

from .. import const, protocols, transport, tasks
from .db import Database, RewritePendingRow


UTC = timezone.utc


class TheOracle(tasks.NonStopTask):
    """
    This task provides an RPC-like interface to the database; it handles
    requests such as registering a new package, version, or build, and
    answering queries about the hashes of files. The primary clients of this
    class are :class:`~.slave_driver.SlaveDriver`,
    :class:`~.the_scribe.TheScribe`, and :class:`~.cloud_gazer.CloudGazer`.

    Note that because database requests are notoriously variable in runtime the
    client RPC class (:class:`DbClient`) doesn't *directly* talk to
    :class:`TheOracle`. Rather, multiple instances of :class:`TheOracle` are
    spawned and :class:`~.seraph.Seraph` sits in front of these acting as a
    simple load-sharing router for the RPC clients.
    """
    name = 'master.the_oracle'
    instance = 0

    def __init__(self, config):
        TheOracle.instance += 1
        self.name = '%s_%d' % (TheOracle.name, TheOracle.instance)
        super().__init__(config)
        self.db = Database(config.dsn)
        self.handlers = {
            method.message: (getattr(self.db, name), method.data_to_args)
            for name, method in inspect.getmembers(Database)
            if hasattr(method, 'message')
        }
        db_queue = self.socket(
            transport.REQ, protocol=protocols.the_oracle)
        db_queue.hwm = 10
        db_queue.connect(const.ORACLE_QUEUE)
        self.register(db_queue, self.handle_db_request)
        db_queue.send(b'READY')

    def close(self):
        self.db.close()
        super().close()

    def handle_db_request(self, queue):
        """
        Handle incoming requests from :class:`DbClient` instances.
        """
        try:
            addr, msg, data = queue.recv_addr_msg()
        except IOError as exc:
            self.logger.error(str(exc))
            # REQ sockets *must* send a reply even when stuff goes wrong
            # otherwise the send/recv cycle that REQ/REP depends upon breaks.
            # Here we've got a badly formed request and we can't even get the
            # reply address, so we just make one up (empty). This message
            # won't go anywhere (bogus address) but that doesn't matter as we
            # just want to get the socket back to receiving state
            addr, msg, data = b'', '', str(exc)
        try:
            handler, data_to_args = self.handlers[msg]
            result = handler(*data_to_args(data))
        except Exception as exc:
            self.logger.error('Error handling db request: %s', msg)
            msg, data = 'ERROR', str(exc)
        else:
            msg, data = 'OK', result
        queue.send_addr_msg(addr, msg, data)  # see note above


class DbClient:
    """
    RPC client class for talking to :class:`TheOracle`.
    """
    def __init__(self, config, logger=None):
        self.ctx = transport.Context()
        self.db_queue = self.ctx.socket(
            transport.REQ, protocol=reversed(protocols.the_oracle),
            logger=logger)
        self.db_queue.hwm = 10
        self.db_queue.connect(config.db_queue)

    def close(self):
        self.db_queue.close()

    def _execute(self, msg, data=protocols.NoData):
        # If sending blocks this either means we're shutting down, or
        # something's gone horribly wrong (either way, raising EAGAIN is fine)
        self.db_queue.send_msg(msg, data, flags=transport.NOBLOCK)
        status, result = self.db_queue.recv_msg()
        if status == 'OK':
            return result
        else:
            raise IOError(result)

    def log_build(self, build):
        build_id = self._execute('LOGBUILD', build.as_message())
        build.logged(build_id)

    def save_rewrites_pending(self, queue):
        self._execute('SAVERWP', queue)

    def load_rewrites_pending(self):
        return [
            RewritePendingRow(*row)
            for row in self._execute('LOADRWP')
        ]


def _generate_db_client():
    # A bit of black magic to duplicate all the @rpc handlers on Database onto
    # DbClient. Some handlers are pre-written above because they do more than
    # a straight-forward translation of args into a message
    for name, method in inspect.getmembers(Database):
        if hasattr(method, 'message') and not hasattr(DbClient, name):
            def handler(self, *args, _method=method, **kwargs):
                sig = inspect.signature(_method)
                bound = sig.bind(self, *args, **kwargs)
                bound.apply_defaults()
                return self._execute(
                    _method.message,
                    _method.args_to_data(tuple(bound.arguments.values())))
            handler.__name__ = name
            handler.__qualname__ = f'DbClient.{name}'
            setattr(DbClient, name, handler)
_generate_db_client()
del _generate_db_client
