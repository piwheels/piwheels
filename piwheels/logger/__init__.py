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
Contains the functions that implement the :program:`piw-logger` script.

.. autofunction:: main
"""

import io
import sys
import gzip
import json
import logging
import datetime as dt
import ipaddress
from pathlib import PosixPath

import zmq
from lars.apache import ApacheSource, COMMON, COMMON_VHOST, COMBINED

from .. import __version__, terminal, const, protocols, transport


# Workaround: lars bug; User-Agent instead of User-agent
COMBINED = '%h %l %u %t "%r" %>s %b "%{Referer}i" "%{User-Agent}i"'


def main(args=None):
    """
    This is the main function for the :program:`piw-logger` script. It is
    designed to be run as a `piped log script`_ under Apache, piping access
    logs to the :class:`~.lumberjack.Lumberjack` task which stores them in the
    database. However it can also be used to load pre-existing logs in to.

    .. _piped log script: https://httpd.apache.org/docs/2.4/logs.html#piped
    """
    logging.getLogger().name = 'logger'
    parser = terminal.configure_parser("""\
The piw-logger script is intended for use as an Apache "piped log script"
but can also be used to feed pre-existing Apache logs to the master by
feeding logs to the script's stdin. This script must be run on the same node
as the piw-master script.
""")
    parser.add_argument(
        '--format', default='combined',
        help="The Apache log format that log lines will be expected to be in "
        "(default: %(default)s); the short-cuts common, combined and "
        "common_vhost can be used in addition to Apache LogFormat strings")
    parser.add_argument(
        'files', nargs='*', default=['-'],
        help="The log file(s) to load into the master; if omitted or - then "
        "stdin will be read which is the default for piped log usage")
    parser.add_argument(
        '--log-queue', metavar='ADDR', default=const.LOG_QUEUE,
        help="The address of the queue used by piw-logger (default: "
        "(%(default)s); this should always be an ipc address")
    parser.add_argument(
        '--drop', action='store_true',
        help="Drop log records if unable to send them to the master after a "
        "short timeout; this should generally be specified when piw-logger "
        "is used as a piped log script")
    try:
        config = parser.parse_args(args)
        terminal.configure_logging(config.log_level, config.log_file)

        logging.info("PiWheels Logger version %s", __version__)
        config.format = {
            'common': COMMON,
            'common_vhost': COMMON_VHOST,
            'combined': COMBINED,
        }.get(config.format, config.format)
        ctx = transport.Context.instance()
        queue = ctx.socket(zmq.PUSH, protocol=protocols.lumberjack)
        queue.connect(config.log_queue)
        try:
            for filename in config.files:
                log_file = log_open(filename)
                try:
                    with ApacheSource(log_file, config.format) as src:
                        for row in src:
                            if log_filter(row):
                                if not config.drop or queue.poll(1000, zmq.POLLOUT):
                                    queue.send_msg('LOG', log_transform(row))
                                else:
                                    logging.warning('dropping log entry')
                finally:
                    log_file.close()
        finally:
            queue.close()
            ctx.destroy(linger=1000)
            ctx.term()
    except RuntimeError as err:
        logging.error(err)
        return 1
    except:  # pylint: disable=bare-except
        return terminal.error_handler(*sys.exc_info())
    else:
        return 0


def log_open(filename):
    """
    Open the log-file specified by *filename*. If this is ``"-"`` then stdin
    will be returned. If the filename ends with ``".gz"`` the file will be
    extracted automatically. Otherwise, the file is opened regularly.

    :param str filename:
        The filename to open as a read-only file.

    :returns:
        The file-like object to read.
    """
    if filename == '-':
        logging.info('Processing log entries from stdin')
        return sys.stdin
    elif filename.endswith('.gz'):
        logging.info('Processing gzipped log %s', filename)
        return io.TextIOWrapper(gzip.open(filename, 'rb'), encoding='ascii')
    else:
        logging.info('Processing log %s', filename)
        return io.open(filename, 'r', encoding='ascii')


def log_filter(row):
    """
    Filters which log entries to include. Current criteria are: successful
    downloads (status 200) only, user-agent must begin with ``"pip/"`` and
    the accessed path must have an extension of ``".whl"``.

    :param row:
        A tuple containing the fields of the log entry, as returned by
        :class:`lars.apache.ApacheSource`.
    """
    return (
        row.status == 200
        and row.req_User_Agent is not None
        and row.req_User_Agent.startswith('pip/')
        and row.request.url.path_str.endswith('.whl')
    )


def log_transform(row, decoder=json.JSONDecoder()):
    """
    Extracts the relevant information from the specified *row*.

    :param row:
        A tuple containing the fields of the log entry, as returned by
        :class:`lars.apache.ApacheSource`.
    """
    path = PosixPath(row.request.url.path_str)
    try:
        json_start = row.req_User_Agent.index('{')
    except ValueError:
        user_data = {}
    else:
        try:
            user_data = decoder.decode(row.req_User_Agent[json_start:])
        except ValueError:
            user_data = {}
    return [
        # Convert lars types into standard types (avoids some issues with
        # some database backends)
        path.name,
        str(row.remote_host),
        row.time.replace(),
        user_data.get('cpu'),
        user_data.get('distro', {}).get('name'),
        user_data.get('distro', {}).get('version'),
        user_data.get('system', {}).get('name'),
        user_data.get('system', {}).get('version'),
        user_data.get('implementation', {'name': 'CPython'}).get('name'),
        user_data.get('implementation', {'version': user_data.get('python')}).get('version'),
    ]
