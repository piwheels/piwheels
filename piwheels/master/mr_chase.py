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

from .. import const, protocols, transport, tasks
from ..states import BuildState, FileState
from .the_oracle import DbClient
from .file_juggler import FsClient
from .slave_driver import build_armv6l_hack


class MrChase(tasks.PauseableTask):
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
        import_queue = self.socket(
            transport.ROUTER, protocol=protocols.mr_chase)
        import_queue.bind(config.import_queue)
        self.register(import_queue, self.handle_import)
        self.status_queue = self.socket(
            transport.PUSH, protocol=protocols.monitor_stats)
        self.status_queue.hwm = 10
        self.status_queue.connect(const.INT_STATUS_QUEUE)
        self.web_queue = self.socket(
            transport.REQ, protocol=reversed(protocols.the_scribe))
        self.web_queue.connect(config.web_queue)
        self.stats_queue = self.socket(
            transport.PUSH, protocol=reversed(protocols.big_brother))
        self.stats_queue.connect(config.stats_queue)
        self.db = DbClient(config, self.logger)
        self.fs = FsClient(config, self.logger)
        self.states = {}

    def close(self):
        self.fs.close()
        self.db.close()
        super().close()

    def handle_import(self, queue):
        """
        Handle requests from :program:`piw-import` instances.

        See the :doc:`importer` and :doc:`remove` chapters for an overview of
        the protocol for messages between the importer and :class:`MrChase`.
        """
        # pylint: disable=too-many-locals
        try:
            address, msg, data = queue.recv_addr_msg()
        except IOError as e:
            # XXX How do we ditch states of errored / unresponsive clients?
            self.logger.error(str(e))
            return

        try:
            state = self.states[address]
        except KeyError:
            if msg == 'IMPORT':
                state = BuildState.from_message(data)
                # XXX Slave ID is always 0 ... what happens if two simultaneous
                # imports are attempted, particularly re the file-expect
                # mechanism?
                state._slave_id = 0
                self.states[address] = state
            elif msg in ('REMOVE', 'REBUILD'):
                # No need to store state for these tools
                state = data
            elif msg == 'SENT':
                self.logger.error('SENT before IMPORT')
                queue.send_addr_msg(address, 'ERROR', 'protocol violation')
                return

        handler = {
            'IMPORT': self.do_import,
            'REMOVE': self.do_remove,
            'REBUILD': self.do_rebuild,
            'SENT': self.do_sent,
        }[msg]
        msg, data = handler(state)

        if msg in ('DONE', 'ERROR'):
            self.states.pop(address, None)
        queue.send_addr_msg(address, msg, data)

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
            return 'ERROR', 'importing a failed build is not supported'
        if not state.files:
            self.logger.error('attempting to add empty build')
            return 'ERROR', 'no files listed for import'
        build_armv6l_hack(state)
        build_abis = self.db.get_build_abis()
        if state.abi_tag not in build_abis:
            self.logger.error('invalid ABI: %s', state.abi_tag)
            return 'ERROR', 'invalid ABI: %s' % state.abi_tag
        if not self.db.test_package_version(state.package, state.version):
            self.logger.error('unknown package version %s-%s',
                              state.package, state.version)
            return 'ERROR', 'unknown package version %s-%s' % (
                state.package, state.version)
        try:
            self.db.log_build(state)
        except IOError as err:
            self.logger.error('failed to log build: %s', err)
            return 'ERROR', str(err)
        self.logger.info('registered build for %s %s',
                         state.package, state.version)
        if state.status and not state.transfers_done:
            self.fs.expect(0, state.files[state.next_file])
            self.logger.info('send %s', state.next_file)
            return 'SEND', state.next_file
        else:
            # XXX We'll never reach this branch at the moment, but in future we
            # might well support failed builds (as another method of skipping
            # builds)
            self.web_queue.send_msg('PROJECT', state.package)
            self.web_queue.recv_msg()
            return 'DONE', protocols.NoData

    def do_sent(self, state):
        """
        Handler for the importer's "SENT" message indicating that it's finished
        sending the requested file to :class:`FileJuggler`. The file is
        verified (as in :class:`SlaveDriver`) and, if this is successful, a
        mesasge is sent to :class:`TheScribe` to regenerate the package's
        index.

        If further files remain to be transferred, another "SEND" message is
        returned to the build slave. Otherwise, "DONE" is sent to free all
        build resources.

        If a transfer fails to verify, another "SEND" message with the same
        filename is returned to the build slave.
        """
        if self.fs.verify(0, state.package):
            self.logger.info('verified transfer of %s', state.next_file)
            state.files[state.next_file].verified()
            if state.transfers_done:
                self.web_queue.send_msg('BOTH', state.package)
                self.web_queue.recv_msg()
                return 'DONE', protocols.NoData
            else:
                self.fs.expect(0, state.files[state.next_file])
                self.logger.info('send %s', state.next_file)
                return 'SEND', state.next_file
        else:
            self.logger.info('re-send %s', state.next_file)
            return 'SEND', state.next_file

    def do_remove(self, state):
        """
        Handler for the remover's "REMOVE" message, indicating a request to
        remove a specific version of a package from the system.
        """
        package, version, reason = state
        if not self.db.test_package_version(package, version):
            self.logger.error('unknown package version %s-%s',
                              package, version)
            return 'ERROR', 'unknown package version %s-%s' % (
                package, version)
        self.logger.info('removing %s %s', package, version)
        if reason:
            self.db.skip_package_version(package, version, reason)
        self.web_queue.send_msg('DELVER', [package, version])
        self.web_queue.recv_msg()
        # XXX Technically we ought to send DELVER to slave-driver's skip-queue
        # here but let's not complicate the spider's web of connections!
        if reason:
            self.db.delete_build(package, version)
        else:
            self.db.delete_version(package, version)
        return 'DONE', protocols.NoData

    def do_rebuild(self, state):
        """
        Handler for the rebuilder's "REBUILD" message, indicating a request
        to rebuild part of the website.
        """
        part, *state = state
        if part in ('HOME', 'SEARCH'):
            self.logger.info('requesting rebuild of homepage and search')
            self.stats_queue.send_msg('HOME')
        else:  # ('PROJECT', 'BOTH'):
            package, = state
            if package is None:
                self.logger.warning('requesting rebuild of *all* pages')
                for package in self.db.get_all_packages():
                    self.web_queue.send_msg(part, package)
                    self.web_queue.recv_msg()
            elif self.db.test_package(package):
                self.logger.info('requesting rebuild of pages for %s', package)
                self.web_queue.send_msg(part, package)
                self.web_queue.recv_msg()
            else:
                return 'ERROR', 'unknown package %s' % package
        return 'DONE', protocols.NoData
