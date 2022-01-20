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
Contains the functions that implement the :program:`piw-remove` script.

.. autofunction:: main

.. autofunction:: do_remove
"""

import sys
import logging

from .. import __version__, terminal, const, transport, protocols


def main(args=None):
    """
    This is the main function for the :program:`piw-remove` script. It uses
    :class:`~.mr_chase.MrChase` to remove built packages from the system.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[RuntimeError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'import'
    parser = terminal.configure_parser("""\
The piw-remove script is used to manually remove built packages from the
system. This script must be run on the same node as the piw-master script.
""")
    parser.add_argument(
        'package', default=None, help="The name of the package to remove")
    parser.add_argument(
        'version', nargs='?', default=None,
        help="The version of the package to remove; if omitted, removes the "
        "entire package")
    parser.add_argument(
        '-y', '--yes', action='store_true',
        help="Run non-interactively; never prompt during operation")
    parser.add_argument(
        '-b', '--builds', action='store_true',
        help="Remove builds and files for this package / version, but don't "
        "delete from the database (requeue unless --skip also given)")
    parser.add_argument(
        '-s', '--skip', action='store', default='', metavar='REASON',
        help="Mark the package / version as skipped to prevent future build "
        "attempts (remove and skip if --builds also given)")
    parser.add_argument(
        '--yank', action='store_true', help="Mark a version as yanked")
    parser.add_argument(
        '--import-queue', metavar='ADDR', default=const.IMPORT_QUEUE,
        help="The address of the queue used by piw-remove (default: "
        "%(default)s); this should always be an ipc address")
    config = parser.parse_args(args)
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Remover version %s", __version__)

    if not config.yes:
        if config.version is None:
            logging.warning("Preparing to remove/alter %s", config.package)
        else:
            logging.warning("Preparing to remove/alter %s %s",
                            config.package, config.version)
        if not terminal.yes_no_prompt('Proceed?'):
            logging.warning('User aborted removal')
            return 2
    logging.info('Connecting to master at %s', config.import_queue)
    do_remove(config)
    return 0


def do_remove(config):
    """
    Handles constructing and sending the REMPKG/REMVER message to
    :class:`~.mr_chase.MrChase`.

    :param config:
        The configuration obtained from parsing the command line.
    """
    ctx = transport.Context()
    queue = ctx.socket(transport.REQ, protocol=reversed(protocols.mr_chase))
    queue.hwm = 10
    queue.connect(config.import_queue)
    try:
        if config.version is None:
            queue.send_msg('REMPKG', [
                config.package, config.builds, config.skip
            ])
        else:
            queue.send_msg('REMVER', [
                config.package, config.version, config.builds, config.skip,
                config.yank
            ])
        msg, data = queue.recv_msg()

        if msg == 'ERROR':
            if data == 'NOPKG':
                raise RuntimeError('Package {} does not exist'.format(
                    config.package))
            elif data == 'NOVER':
                raise RuntimeError('Version {} {} does not exist'.format(
                    config.package, config.version))
            else:
                assert False, 'invalid data from master'

        elif msg == 'DONE':
            if data == 'DELPKG':
                logging.info('Removed package successfully')
            elif data == 'DELVER':
                logging.info('Removed version successfully')
            elif data == 'DELPKGBLD':
                logging.info('Removed builds for package successfully')
            elif data == 'DELVERBLD':
                logging.info('Removed builds for version successfully')
            elif data == 'SKIPPKG':
                logging.info('Skipped package successfully')
            elif data == 'SKIPVER':
                logging.info('Skipped version successfully')
            elif data == 'YANKVER':
                logging.info('Yanked version successfully')
            else:
                assert False, 'invalid operation from master'
        else:
            assert False, 'invalid response from master'
    finally:
        queue.close()
        ctx.close()
