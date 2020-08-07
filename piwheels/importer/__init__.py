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
Contains the functions that implement the :program:`piw-import` script.

.. autofunction:: main

.. autofunction:: print_state

.. autofunction:: do_import

.. autofunction:: do_send
"""

import sys
import logging
from datetime import timedelta
from pathlib import Path

from .. import __version__, terminal, const, transport, protocols
from ..format import format_size
from ..states import FileState, BuildState
from ..slave import duration
from ..slave.builder import Wheel


def main(args=None):
    """
    This is the main function for the :program:`piw-import` script. It uses
    some bits of the :program:`piw-slave` script to deconstruct the filenames
    passed to it in order to build all the requried information that
    :class:`~.mr_chase.MrChase` needs.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[RuntimeError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'import'
    parser = terminal.configure_parser("""\
The piw-import script is used to inject the specified file(s) manually into
the piwheels database and file-system. This script must be run on the same
node as the piw-master script. If multiple files are specified, they are
registered as produced by a *single* build.
""")
    parser.add_argument(
        '--package', default=None,
        help="The name of the package to import; if omitted this will be "
        "derived from the file(s) specified")
    parser.add_argument(
        '--package-version', default=None, dest='version',
        help="The version of the package to import; if omitted this will be "
        "derived from the file(s) specified")
    parser.add_argument(
        '--abi', default=None,
        help="The ABI of the package to import; if omitted this will be "
        "derived from the file(s) specified")
    parser.add_argument(
        '--duration', default='0s', type=duration,
        help="The time taken to build the package (default: %(default)s)")
    parser.add_argument(
        '--output', metavar='FILE', default=None, type=terminal.FileType('r'),
        help="The filename containing the build output to insert into the "
        "database; if this is omitted an appropriate message will be "
        "inserted instead")
    parser.add_argument(
        '-y', '--yes', action='store_true',
        help="Run non-interactively; never prompt during operation")
    parser.add_argument(
        '-d', '--delete', action='store_true',
        help="Remove the specified file(s) after a successful import; if the "
        "import fails, no files will be removed")
    parser.add_argument(
        'files', nargs='+',
        help="The file(s) to inject into piwheels; you may specify multiple "
        "files in which case they will all be treated as part of the same "
        "build")
    parser.add_argument(
        '--import-queue', metavar='ADDR', default=const.IMPORT_QUEUE,
        help="The address of the queue used by piw-import (default: "
        "(%(default)s); this should always be an ipc address")
    config = parser.parse_args(args)
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Importer version %s", __version__)

    # NOTE: If any of the files are unreadable, this'll fail (it attempts
    # to calculate the hash of the file which requires reading it)
    packages = [
        Wheel(Path(filename))
        for filename in config.files
    ]
    state = BuildState(
        slave_id=0,  # ignored
        package=config.package if config.package is not None else
            packages[0].metadata['Name'],
        version=config.version if config.version is not None else
            packages[0].metadata['Version'],
        abi_tag=config.abi if config.abi is not None else
            packages[0].abi_tag if packages[0].abi_tag != 'none' else
            None,
        status=True,
        duration=config.duration,
        output=config.output.read() if config.output is not None else
            'Imported manually via piw-import',
        files={pkg.filename: FileState(*pkg.as_message()) for pkg in packages}
    )
    if state.abi_tag is None:
        raise RuntimeError("couldn't determine builder ABI; re-run with --abi")
    if not config.yes:
        print_state(state)
        if not terminal.yes_no_prompt('Proceed?'):
            logging.warning('User aborted import')
            return 2
    logging.info('Connecting to master at %s', config.import_queue)
    do_import(config, packages, state)
    if config.delete:
        for package in packages:
            package.wheel_file.unlink()
    return 0


def print_state(state):
    """
    Dumps a human-readable description of the *state* to the log / console.

    :param BuildState state:
        The build state to print the description of.
    """
    logging.warning('Preparing to import build')
    logging.warning('Package:  %s', state.package)
    logging.warning('Version:  %s', state.version)
    logging.warning('ABI:      %s', state.abi_tag)
    logging.warning('Status:   successful')
    logging.warning('Duration: %s', state.duration)
    logging.warning('Output:   %d line(s)', len(state.output.splitlines()))
    logging.warning('Files:    %d', len(state.files))
    for wheel in state.files.values():
        logging.warning('')
        logging.warning('Filename: %s', wheel.filename)
        logging.warning('  Size:         %s', format_size(wheel.filesize))
        logging.warning('  Hash:         %s', wheel.filehash)
        logging.warning('  Package tag:  %s', wheel.package_tag)
        logging.warning('  Version tag:  %s', wheel.package_version_tag)
        logging.warning('  ABI tag:      %s', wheel.abi_tag)
        logging.warning('  Python tag:   %s', wheel.py_version_tag)
        logging.warning('  Platform tag: %s', wheel.platform_tag)


def do_import(config, packages, state):
    """
    Handles constructing and sending the initial "IMPORT" message to
    :class:`..master.mr_chase.MrChase`. If "SEND" is then received, uses
    :func:`do_send` to handle transmitting files.

    :param config:
        The configuration obtained from parsing the command line.

    :param list packages:
        A sequence of :class:`Wheel` objects corresponding to files in the
        *state*.

    :param BuildState state:
        The object representing the state of the build.
    """
    ctx = transport.Context()
    queue = ctx.socket(transport.REQ, protocol=reversed(protocols.mr_chase))
    queue.hwm = 10
    queue.connect(config.import_queue)
    try:
        queue.send_msg('IMPORT', state.as_message())
        msg, data = queue.recv_msg()
        if msg == 'ERROR':
            raise RuntimeError(data)
        logging.info('Registered build successfully')
        while msg == 'SEND':
            do_send(packages, data)
            queue.send_msg('SENT')
            msg, data = queue.recv_msg()
        if msg != 'DONE':
            raise RuntimeError('Unexpected response from master')
    finally:
        queue.close()
        ctx.close()


def do_send(packages, filename):
    """
    Handles sending files when requested by :func:`do_import`.
    """
    logging.info('Sending %s to master on localhost', filename)
    pkg = [p for p in packages if p.filename == filename][0]
    ctx = transport.Context()
    queue = ctx.socket(
        transport.DEALER, protocol=reversed(protocols.file_juggler_files))
    queue.ipv6 = True
    queue.hwm = 10
    # NOTE: The following assumes that we're running on the master; this
    # *should* be the case (it's risky to run the importer on a tcp queue)
    # but there's no guarantee of this.
    queue.connect('tcp://localhost:5556')
    try:
        pkg.transfer(queue, 0)
    finally:
        queue.close()
