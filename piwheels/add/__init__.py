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
Contains the functions that implement the :program:`piw-add` script.

.. autofunction:: main

.. autofunction:: do_add
"""

from datetime import datetime, timezone
import sys
import logging

import requests

from .. import __version__, terminal, const, transport, protocols
from ..format import canonicalize_name


UTC = timezone.utc


def main(args=None):
    """
    This is the main function for the :program:`piw-add` script. It uses
    :class:`~.mr_chase.MrChase` to add mew packages and versions to the system.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[RuntimeError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'import'
    parser = terminal.configure_parser("""\
The piw-add script is used to manually add new packages and versions to the
system. This script must be run on the same node as the piw-master script.
""")
    parser.add_argument(
        'package', default=None, help="The name of the package to add")
    parser.add_argument(
        'version', nargs='?', default=None,
        help="The version of the package to add; if omitted, adds the package "
        "only")
    parser.add_argument(
        '-y', '--yes', action='store_true',
        help="Run non-interactively; never prompt during operation")
    parser.add_argument(
        '-s', '--skip', action='store', default='', metavar='REASON',
        help="Mark the package or version with a skip reason to prevent build "
        "attempts")
    parser.add_argument(
        '--unskip', action='store_true',
        help="Remove a skip reason for the package or version to enable build "
        "attempts")
    parser.add_argument(
        '-d', '--description', nargs='?', default=None,
        help="The package description")
    parser.add_argument(
        '-a', '--aliases', nargs='*', default=[],
        help="Any package aliases to use")
    parser.add_argument(
        '-r', '--released', nargs='?',
        default=datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        help="The version's release date (can only be provided for a new "
        "version, cannot be updated)")
    parser.add_argument(
        '--yank', action='store_true',
        help="Mark the version as yanked (can only be applied to a new "
        "version - use piw-remove to yank a known version")
    parser.add_argument(
        '--unyank', action='store_true',
        help="Mark a known version as not yanked")
    parser.add_argument(
        '--import-queue', metavar='ADDR', default=const.IMPORT_QUEUE,
        help="The address of the queue used by piw-add (default: "
        "(%(default)s); this should always be an ipc address")
    config = parser.parse_args(args)
    package = canonicalize_name(config.package)
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Adder version %s", __version__)

    if not config.yes:
        if config.version is None:
            logging.warning("Preparing to add/update %s", config.package)
        else:
            logging.warning("Preparing to add/update %s %s",
                            config.package, config.version)
        if not terminal.yes_no_prompt('Proceed?'):
            logging.warning('User aborted addition')
            return 2
    logging.info('Connecting to master at %s', config.import_queue)
    config.released = datetime.strptime(
        config.released, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
    if config.version is None and config.description is None:
        config.description = _get_package_description(package)
    for alias in config.aliases:
        if canonicalize_name(alias) != package:
            raise RuntimeError("Alias {} does not match canon: {}".format(
                alias, package))
    do_add(config)
    return 0


def do_add(config):
    """
    Handles constructing and sending the ADDPKG/ADDVER message to
    :class:`..master.mr_chase.MrChase`.

    :param config:
        The configuration obtained from parsing the command line.
    """
    ctx = transport.Context()
    queue = ctx.socket(transport.REQ, protocol=reversed(protocols.mr_chase))
    queue.hwm = 10
    queue.connect(config.import_queue)

    try:
        if config.version is None:
            queue.send_msg('ADDPKG', [
                config.package, config.description, config.skip, config.unskip,
                config.aliases,
            ])
        else:
            queue.send_msg('ADDVER', [
                config.package, config.version, config.skip, config.unskip,
                config.released, config.yank, config.unyank, config.aliases,
            ])
        msg, data = queue.recv_msg()
        if msg == 'ERROR':
            if data == 'NOPKG':
                raise RuntimeError(
                    'Package {} does not exist - add it with piw-add '
                    'first'.format(config.package))
            elif data == 'SKIPPKG':
                raise RuntimeError(
                    'Cannot skip a known package with piw-add - use '
                    'piw-remove instead')
            elif data == 'SKIPVER':
                raise RuntimeError(
                    'Cannot skip a known version with piw-add - use '
                    'piw-remove instead')
            elif data == 'YANKVER':
                raise RuntimeError(
                    'Cannot yank a known version with piw-add - use '
                    'piw-remove instead')
            raise RuntimeError(data)

        if msg == 'DONE':
            if data == 'NEWPKG':
                logging.warning('Added package successfully')
            elif data == 'UPDPKG':
                logging.warning('Updated package successfully')
            elif data == 'NEWVER':
                logging.warning('Added version successfully')
            elif data == 'UPDVER':
                logging.warning('Updated version successfully')
        else:
            raise RuntimeError('Unexpected response from master')
    finally:
        queue.close()
        ctx.close()


def _get_package_description(pkg):
    "Return the package description from PyPI"
    url = 'https://pypi.org/pypi/{}/json'.format(pkg)
    r = requests.get(url)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        logging.error('Error retrieving package description, status code: %s',
                      r.status_code)
        return ''
    description = r.json()['info']['summary']
    if description is None:
        return ''
    elif len(description) > 200:
        return description[:199] + '…'
    return description
