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
Defines the :class:`MrChase` task; see class for more details.

.. autoclass:: MrChase
    :members:
"""

import pickle

import zmq

from .. import const
from .states import BuildState, FileState
from .tasks import PauseableTask
from .the_oracle import DbClient
from .file_juggler import FsClient
from .slave_driver import build_armv6l_hack


class MrChase(PauseableTask):
    """
    This task handles smuggling packages into the database manually. It is the
    task that the :program:`piw-import` script talks to in order to import
    packages.

    Internally, the task is essentially an abbreviated
    :class:`~slave_driver.SlaveDriver` (in as much as it has to perform similar
    database and file-system interactions) but without having to handle talking
    to lots of build slaves.
    """
    name = 'master.mr_chase'

    def __init__(self, config):
        super().__init__(config)
        self.paused = False
        import_queue = self.ctx.socket(zmq.ROUTER)
        import_queue.bind(config.import_queue)
        self.register(import_queue, self.handle_import)
        self.status_queue = self.ctx.socket(zmq.PUSH)
        self.status_queue.hwm = 10
        self.status_queue.connect(const.INT_STATUS_QUEUE)
        self.index_queue = self.ctx.socket(zmq.PUSH)
        self.index_queue.hwm = 10
        self.index_queue.connect(config.index_queue)
        self.db = DbClient(config)
        self.fs = FsClient(config)
        self.states = {}

    def handle_import(self, queue):
        """
        Handle requests from :program:`piw-import` instances.

        See the :doc:`import` chapter for an overview of the protocol for
        messages between the importer and :class:`MrChase`.
        """
        # pylint: disable=too-many-locals
        try:
            address, empty, msg = queue.recv_multipart()
            msg, *args = pickle.loads(msg)
            self.logger.debug('RX: %s %r', msg, args)
            try:
                state = self.states[address]
            except KeyError:
                if msg == 'IMPORT':
                    (
                        abi_tag,
                        package,
                        version,
                        status,
                        duration,
                        output,
                        files,
                    ) = args
                    state = BuildState(
                        0, package, version, abi_tag, status, duration,
                        output, files={
                            filename: FileState(filename, *filestate)
                            for filename, filestate in files.items()
                        }
                    )
                    self.states[address] = state
                else:
                    self.logger.error(
                        'invalid first message from importer: %s', msg)
                    return
        except ValueError:
            self.logger.error('invalid message structure from importer')

        try:
            handler = {
                'IMPORT': self.do_import,
                'SENT': self.do_sent,
            }[msg]
        except KeyError:
            self.logger.error('invalid message from importer: %s', msg)
        else:
            reply = handler(state)
            if reply is not None:
                queue.send_multipart([address, empty, pickle.dumps(reply)])
                self.logger.debug('TX: %r', reply)

    def do_import(self, state):
        """
        Handler for the importer's initial "IMPORT" message. This method checks
        the information in the state passes some simple tests, then ensures
        that the requested package and version exist in the database (creating
        them if necessary).
        """
        # pylint: disable=too-many-return-statements
        if not state.status:
            self.logger.error('attempting to add failed build')
            return ['ERROR', 'importing a failed build is not supported']
        if not state.files:
            self.logger.error('attempting to add empty build')
            return ['ERROR', 'no files listed for import']
        for file in state.files.values():
            if file.platform_tag == 'linux_armv6l':
                self.logger.error('attempting to add armv6l wheel')
                return ['ERROR', 'armv6l wheels will be automatically linked']
        build_armv6l_hack(state)
        build_abis = self.db.get_build_abis()
        if state.abi_tag is None:
            # XXX Ought to use ORDER BY in SQL for this (in case Python's
            # collation doesn't match Postgres') but this means adding more to
            # the database API and I'm too lazy right now
            state.abi_tag = min(build_abis)
        if state.abi_tag not in build_abis:
            self.logger.error('invalid ABI: %s', state.abi_tag)
            return ['ERROR', 'invalid ABI: %s' % state.abi_tag]
        if not self.db.test_package_version(state.package, state.version):
            return ['ERROR', 'unknown package version %s-%s' % (
                state.package, state.version)]
        try:
            self.db.log_build(state)
        except IOError as err:
            return ['ERROR', str(err)]
        if state.status and not state.transfers_done:
            self.fs.expect(0, state.files[state.next_file])
            self.logger.info('send %s', state.next_file)
            return ['SEND', state.next_file]
        else:
            # XXX We'll never reach this branch at the moment, but in future we
            # might well support failed builds (as another method of skipping
            # builds)
            self.index_queue.send_pyobj(['PKG', state.package])
            return ['DONE']

    def do_sent(self, state):
        """
        Handler for the importer's "SENT" message indicating that it's finished
        sending the requested file to :class:`FileJuggler`. The file is
        verified (as in :class:`SlaveDriver`) and, if this is successful, a
        mesasge is sent to :class:`IndexScribe` to regenerate the package's
        index.

        If further files remain to be transferred, another "SEND" message is
        returned to the build slave. Otherwise, "DONE" is sent to free all
        build resources.

        If a transfer fails to verify, another "SEND" message with the same
        filename is returned to the build slave.
        """
        if self.fs.verify(0, state.package):
            self.index_queue.send_pyobj(['PKG', state.package])
            self.logger.info('verified transfer of %s', state.next_file)
            state.files[state.next_file].verified()
            if state.transfers_done:
                return ['DONE']
            else:
                self.fs.expect(0, state.files[state.next_file])
                self.logger.info('send %s', state.next_file)
                return ['SEND', state.next_file]
        else:
            self.logger.info('send %s', state.next_file)
            return ['SEND', state.next_file]
