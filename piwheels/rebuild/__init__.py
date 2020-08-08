#!/usr/bin/env python

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
Contains the functions that implement the :program:`piw-rebuild` script.

.. autofunction:: main

.. autofunction:: do_rebuild
"""

import sys
import logging
from datetime import timedelta
from pathlib import Path

from .. import __version__, terminal, const, transport, protocols
from ..slave import duration


def part(s):
    try:
        return {
            'home':    'HOME',
            'search':  'SEARCH',
            'project': 'PROJECT',
            'index':   'BOTH',
        }[s]
    except KeyError:
        raise ValueError('invalid website part %s' % s)


def main(args=None):
    """
    This is the main function for the :program:`piw-rebuild` script. It mostly
    parses the command line args into messages for :class:`~.mr_chase.MrChase`.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[RuntimeError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'import'
    parser = terminal.configure_parser("""\
The piw-rebuild script is used to inject rebuild requests for various web pages
into the piwheels system. This script must be run on the same node as the
piw-master script.
""")
    parser.add_argument(
        '-y', '--yes', action='store_true',
        help="Run non-interactively; never prompt during operation")
    parser.add_argument(
        'part', type=part,
        help="The part of the website to rebuild; can be one of 'home', "
        "'search', 'index', or 'project'. For 'index' or 'project' a package "
        "name may additionally be specified")
    parser.add_argument(
        'package', nargs='?',
        help="When 'index' or 'project' is given, this specifies for which "
        "package pages will be rebuilt. If omitted, pages will be rebuilt "
        "for ALL packages")
    parser.add_argument(
        '--import-queue', metavar='ADDR', default=const.IMPORT_QUEUE,
        help="The address of the queue used by piw-rebuild (default: "
        "(%(default)s); this should always be an ipc address")
    config = parser.parse_args(args)
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Rebuilder version %s", __version__)

    if not config.yes:
        if config.part in ('PROJECT', 'BOTH') and config.package is None:
            s = 'This will rebuild pages for ALL packages; proceed?'
            if not terminal.yes_no_prompt(s):
                logging.warning('User aborted rebuild')
                return 2
            logging.warning('Go make coffee...')
    logging.info('Connecting to master at %s', config.import_queue)
    do_rebuild(config)
    return 0


def do_rebuild(config):
    """
    Handles constructing and sending the "REBUILD" message to
    :class:`..master.mr_chase.MrChase`.

    :param config:
        The configuration obtained from parsing the command line.
    """
    ctx = transport.Context()
    queue = ctx.socket(transport.REQ, protocol=reversed(protocols.mr_chase))
    queue.hwm = 10
    queue.connect(config.import_queue)
    try:
        if config.part in ('HOME', 'SEARCH'):
            queue.send_msg('REBUILD', [config.part])
        else:
            queue.send_msg('REBUILD', [config.part, config.package])
        msg, data = queue.recv_msg()
        if msg == 'ERROR':
            raise RuntimeError(data)
        if msg != 'DONE':
            raise RuntimeError('Unexpected response from master')
        logging.info('Queued rebuild request for page(s) successfully')
    finally:
        queue.close()
        ctx.close()
