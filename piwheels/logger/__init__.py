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
import re
import sys
import gzip
import simplejson as json
import logging
import datetime as dt
import ipaddress
from pathlib import PosixPath
from datetime import timezone
from fnmatch import fnmatchcase

from lars.apache import ApacheSource, COMMON, COMMON_VHOST, COMBINED

from .. import __version__, terminal, const, protocols, transport


# Workaround: lars bug; User-Agent instead of User-agent
COMBINED = '%h %l %u %t "%r" %>s %b "%{Referer}i" "%{User-Agent}i"'
UTC = timezone.utc

get_package_name = lambda path: str(path).split('/')[2]
get_access_ip = lambda rh: str(rh)
get_access_time = lambda dt: dt.replace(tzinfo=UTC)
get_arch = lambda ud: ud.get('cpu')
get_distro_name = lambda ud: ud.get('distro', {}).get('name')
get_distro_version = lambda ud: ud.get('distro', {}).get('version')
get_os_name = lambda ud: ud.get('system', {}).get('name')
get_os_version = lambda ud: ud.get('system', {}).get('release')
get_py_name = lambda ud: ud.get('implementation', {'name': 'CPython'}).get('name')
get_py_version = lambda ud: ud.get('implementation', {'version': ud.get('python')}).get('version')
get_installer_name = lambda ud: ud.get('installer', {}).get('name')
get_installer_version = lambda ud: ud.get('installer', {}).get('version')
get_setuptools_version = lambda ud: ud.get('setuptools_version')
clean_page_name = lambda path: str(path).replace('/', '').replace('.html', '')
get_page_name = lambda path: 'home' if str(path) in ('/', '/index.html') else clean_page_name(path)
get_user_agent = lambda ua: ua.split('/')[0].lower()

log_type_patterns = (
    ('pip/*', '/simple/', None),
    (None,    '/project/', None),
    ('pip/*', '/simple/*.whl', 'LOGDOWNLOAD'),
    ('pip/*', '/simple/*', 'LOGSEARCH'),
    (None,    '/project/*/json/', 'LOGJSON'),
    (None,    '/project/*/json/index.json', 'LOGJSON'),
    (None,    '/project/*', 'LOGPROJECT'),
    (None,    '/', 'LOGPAGE'),
    (None,    '/*.html', 'LOGPAGE'),
)


def main(args=None):
    """
    This is the main function for the :program:`piw-logger` script. It is
    designed to be run as a `piped log script`_ under Apache, piping access
    logs to the :class:`~.lumberjack.Lumberjack` task which stores them in the
    database. However it can also be used to load pre-existing logs in to.

    .. _piped log script: https://httpd.apache.org/docs/2.4/logs.html#piped
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[RuntimeError] = (
        terminal.error_handler.exc_message, 1)
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
    config = parser.parse_args(args)
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Logger version %s", __version__)
    config.format = {
        'common': COMMON,
        'common_vhost': COMMON_VHOST,
        'combined': COMBINED,
    }.get(config.format, config.format)
    ctx = transport.Context()
    queue = ctx.socket(transport.PUSH, protocol=reversed(protocols.lumberjack))
    queue.connect(config.log_queue)
    try:
        for filename in config.files:
            log_file = log_open(filename)
            try:
                with ApacheSource(log_file, config.format) as src:
                    for row in src:
                        log_type = get_log_type(row)
                        if log_type:
                            if not config.drop or queue.poll(0.01, transport.POLLOUT):
                                data = log_transform(row, log_type)
                                queue.send_msg(log_type, data)
                            else:
                                logging.warning('dropping log entry')
            finally:
                log_file.close()
    finally:
        queue.close()
        ctx.close()
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


def get_log_type(row):
    """
    Returns a log type depending on the contents of the row. For rows not
    containing a loggable record, None is returned so the entry can be
    discarded. Other than None, return values must be valid log messages to be
    handled by the oracle.

    :param row:
        A tuple containing the fields of the log entry, as returned by
        :class:`lars.apache.ApacheSource`.
    """
    if row.status != 200 or row.req_User_Agent is None:
        return
    path = row.request.url.path_str
    for ua_mask, fn_mask, log_type in log_type_patterns:
        if ua_mask is None or fnmatchcase(row.req_User_Agent, ua_mask):
            if fnmatchcase(path, fn_mask):
                return log_type

def log_transform(row, log_type, decoder=json.JSONDecoder()):
    """
    Extracts the relevant information from the specified *row*.

    :param row:
        A tuple containing the fields of the log entry, as returned by
        :class:`lars.apache.ApacheSource`.

    :param log_type:
        A string representing the log type, e.g. 'LOGDOWNLOAD', as handled by
        the oracle.

    :param decoder:
        The decoder to use for the serialised data in the log entry. Defaults to
        :class:`simplejson.JSONDecoder` instance.
    """
    path = PosixPath(row.request.url.path_str)
    if row.req_User_Agent.startswith('pip/'):
        try:
            json_start = row.req_User_Agent.index('{')
        except ValueError:
            user_data = {}
        else:
            try:
                user_data = decoder.decode(row.req_User_Agent[json_start:])
            except ValueError:
                user_data = {}
        # Convert lars types into standard types (avoids some issues with
        # some database backends)
        if log_type == 'LOGDOWNLOAD':
            return [
                path.name,
                get_access_ip(row.remote_host),
                get_access_time(row.time),
                get_arch(user_data),
                get_distro_name(user_data),
                get_distro_version(user_data),
                get_os_name(user_data),
                get_os_version(user_data),
                get_py_name(user_data),
                get_py_version(user_data),
                get_installer_name(user_data),
                get_installer_version(user_data),
                get_setuptools_version(user_data),
            ]
        if log_type == 'LOGSEARCH':
            return [
                get_package_name(path),
                get_access_ip(row.remote_host),
                get_access_time(row.time),
                get_arch(user_data),
                get_distro_name(user_data),
                get_distro_version(user_data),
                get_os_name(user_data),
                get_os_version(user_data),
                get_py_name(user_data),
                get_py_version(user_data),
                get_installer_name(user_data),
                get_installer_version(user_data),
                get_setuptools_version(user_data),
            ]
    if log_type == 'LOGPROJECT':
        return [
            get_package_name(path),
            get_access_ip(row.remote_host),
            get_access_time(row.time),
            row.req_User_Agent,
        ]
    if log_type == 'LOGJSON':
        return [
            get_package_name(path),
            get_access_ip(row.remote_host),
            get_access_time(row.time),
            get_user_agent(row.req_User_Agent),
        ]
    if log_type == 'LOGPAGE':
        return [
            get_page_name(path),
            get_access_ip(row.remote_host),
            get_access_time(row.time),
            row.req_User_Agent,
        ]
