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

.. autofunction:: print_builder

.. autofunction:: abi

.. autofunction:: do_import

.. autofunction:: do_send
"""

import sys
import logging
from datetime import timedelta
from pathlib import Path

import zmq

from .. import __version__, terminal, const
from ..slave import duration
from ..slave.builder import PiWheelsPackage, PiWheelsBuilder


def main(args=None):
    """
    This is the main function for the :program:`piw-import` script. It uses
    some bits of the :program:`piw-slave` script to deconstruct the filenames
    passed to it in order to build all the requried information that
    :class:`~.mr_chase.MrChase` needs.
    """
    logging.getLogger().name = 'import'
    parser = terminal.configure_parser("""\
The piw-import script is used to inject the specified file(s) manually into
the piwheels database and file-system. This script must be run on the same
node as the piw-master script.
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
    try:
        config = parser.parse_args(args)
        terminal.configure_logging(config.log_level, config.log_file)

        logging.info("PiWheels Importer version %s", __version__)

        # NOTE: If any of the files are unreadable, this'll fail (it attempts
        # to calculate the hash of the file which requires reading it)
        packages = [
            PiWheelsPackage(Path(filename))
            for filename in config.files
        ]
        builder = PiWheelsBuilder(
            config.package if config.package is not None else
            packages[0].metadata['name'],
            config.version if config.version is not None else
            packages[0].metadata['version'])
        builder.duration = config.duration
        if config.output is not None:
            builder.output = config.output.read()
        else:
            builder.output = 'Imported manually via piw-import'
        builder.status = True
        builder.files = packages
        if not config.yes:
            print_builder(config, builder)
            if not terminal.yes_no_prompt('Proceed?'):
                logging.warning('User aborted import')
                return 2
        logging.info('Connecting to master at %s', config.import_queue)
        do_import(config, builder)
        if config.delete:
            for package in builder.files:
                package.wheel_file.unlink()
    except RuntimeError as err:
        logging.error(err)
        return 1
    except:  # pylint: disable=bare-except
        return terminal.error_handler(*sys.exc_info())
    else:
        return 0


def print_builder(config, builder):
    """
    Dumps a human-readable description of the *builder* to the log / console.

    :param config:
        The configuration generated from the command line argument parser.

    :param PiWheelsBuilder builder:
        The builder to print the description of.
    """
    logging.warning('Preparing to import build')
    logging.warning('Package:  %s', builder.package)
    logging.warning('Version:  %s', builder.version)
    logging.warning('ABI:      %s', abi(config, builder, 'default'))
    logging.warning('Status:   successful')
    logging.warning('Duration: %s',
                    timedelta(seconds=builder.duration))
    logging.warning('Output:   %d line(s)',
                    len(builder.output.splitlines()))
    logging.warning('Files:    %d', len(builder.files))
    for package in builder.files:
        logging.warning('')
        logging.warning('Filename: %s', package.filename)
        logging.warning('  Size:         %d bytes', package.filesize)
        logging.warning('  Hash:         %s', package.filehash)
        logging.warning('  Package tag:  %s', package.package_tag)
        logging.warning('  Version tag:  %s',
                        package.package_version_tag)
        logging.warning('  ABI tag:      %s', package.abi_tag)
        logging.warning('  Python tag:   %s', package.py_version_tag)
        logging.warning('  Platform tag: %s', package.platform_tag)
        if package.build_tag is not None:
            logging.warning('  Build tag:    %s', package.build_tag)


def do_import(config, builder):
    """
    Handles constructing and sending the initial "IMPORT" message to
    :class:`..master.mr_chase.MrChase`. If "SEND" is then received, uses
    :func:`do_send` to handle transmitting files.

    :param config:
        The configuration obtained from parsing the command line.

    :param PiWheelsBuilder builder:
        The object representing the state of the build.
    """
    ctx = zmq.Context.instance()
    queue = ctx.socket(zmq.REQ)
    queue.hwm = 10
    queue.connect(config.import_queue)
    try:
        queue.send_pyobj(['IMPORT', abi(config, builder)] + builder.as_message)
        msg, *args = queue.recv_pyobj()
        if msg == 'ERROR':
            raise RuntimeError(*args)
        logging.info('Registered build successfully')
        while msg == 'SEND':
            do_send(builder, args[0])
            queue.send_pyobj(['SENT'])
            msg, *args = queue.recv_pyobj()
        if msg != 'DONE':
            raise RuntimeError('Unexpected response from master')
    finally:
        queue.close()
        ctx.destroy(linger=1000)
        ctx.term()


def abi(config, builder, default=None):
    """
    Calculate the ABI from the given *config* and the first file contained by
    the *builder* state. If the configuration contains no ABI override, and
    the ABI of the first file is 'none', return *default*.
    """
    if config.abi is not None:
        return config.abi
    elif builder.files[0].abi_tag != 'none':
        return builder.files[0].abi_tag
    else:
        return default


def do_send(builder, filename):
    """
    Handles sending files when requested by :func:`do_import`.
    """
    logging.info('Sending %s to master', filename)
    pkg = [f for f in builder.files if f.filename == filename][0]
    ctx = zmq.Context.instance()
    queue = ctx.socket(zmq.DEALER)
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
