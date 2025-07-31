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
Contains the functions that implement the :program:`piw-audit` script.

.. autofunction:: main
"""

import os
import sys
import logging
import argparse
from pathlib import Path

from . import report_extra, report_missing
from .. import __version__, terminal, const
from ..master.db import Database
from ..build_logs import get_log_file_path, log_path_to_build_id


def main(args=None):
    """
    This is the main function for the :program:`piw-audit-logs` script. It
    doesn't communicate with the master service and only reads build ids from
    the database. It audits the logs directory for missing or extraneous log
    files, and can delete extraneous log files if the `--delete-extra` option
    is specified.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[OSError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'audit'
    parser = terminal.configure_parser("""\
The piw-audit-logs script is intended to check the logs directory for
extraneous log files, and optionally delete them. It can also check for
missing log files.
""")
    parser.add_argument(
        '-d', '--dsn', default=const.DSN,
        help="The database to use; this database must be configured with "
        "piw-initdb and the user should *not* be a PostgreSQL superuser "
        "(default: %(default)s)")
    parser.add_argument(
        '-o', '--output-path', metavar='PATH', default=const.OUTPUT_PATH,
        help="The path under which the website has been written; must be "
        "readable by the current user")
    parser.add_argument(
        '--extra-file', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the path of a file to which all extraneous "
        "filenames (files which shouldn't exist, but do) will be written")
    parser.add_argument(
        '-m', '--missing', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the program will check for missing log files (log "
        "files which should exist, but don't)")
    parser.add_argument(
        '--missing-file', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the path of a file to which all missing "
        "filenames (files which should exist, but don't) will be written")
    parser.add_argument(
        '--delete-extra', action='store_true',
        help="If specified, any extraneous log files will be deleted")
    config = parser.parse_args(args)
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Audit logs version %s", __version__)
    config.output_path = Path(os.path.expanduser(config.output_path))
    audit_logs(config)

def audit_logs(config):
    """
    Check the logs directory for missing or extraneous log files. If the
    --delete-extra option is specified, any extraneous log files will be
    deleted.
    """
    logs_dir = config.output_path / 'logs'
    logging.info('checking logs in %s', logs_dir)
    db = Database(config.dsn)
    
    build_ids = db.get_all_build_ids()
    logging.info(f"Found {len(build_ids):,} build IDs in the database")

    # look for extraneous logs
    for log_path in logs_dir.rglob("*.txt.gz"):
        build_id = log_path_to_build_id(config.output_path, log_path)
        if build_id in build_ids:
            build_ids.remove(build_id)
        else:
            report_extra(config, 'log', log_path)
            if config.delete_extra:
                log_path.unlink()

    # build_ids is now the set of build IDs without a log file

    if config.missing:
        # report missing logs
        for build_id in build_ids:
            log_path = get_log_file_path(build_id, config.output_path)
            report_missing(config, 'log', log_path)