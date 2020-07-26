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

"Defines :class:`PyPI`, the low level interface to PyPI's event log."

import re
import socket
import logging
import http.client
import xmlrpc.client
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
from pathlib import PosixPath

import requests
from requests.exceptions import RequestException
from simplejson.errors import JSONDecodeError


from .. import __version__


UTC = timezone.utc

logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger('master.pypi')


class PiWheelsTransport(xmlrpc.client.SafeTransport):
    """
    Drop in Transport for xmlrpc.client that uses a custom User-Agent string
    (so PyPI can identify our requests more easily in case we're being
    naughty!) and which uses requests for good TLS support and timeouts.
    """
    user_agent = 'piwheels/%s' % __version__

    def __init__(self, use_https=True, cert=None, verify=None, timeout=10,
                 *args, **kwargs):
        self.cert = cert
        self.verify = verify
        self.use_https = use_https
        self.timeout = timeout
        super().__init__(*args, **kwargs)

    def request(self, host, handler, request_body, verbose):
        headers = {
            'User-Agent': self.user_agent,
            'Content-Type': 'text/xml',
        }
        url = self._build_url(host, handler)
        resp = requests.post(url, data=request_body, headers=headers,
                             stream=True, cert=self.cert, verify=self.verify,
                             timeout=self.timeout)
        try:
            resp.raise_for_status()
        except RequestException as exc:
            raise xmlrpc.client.ProtocolError(url, resp.status_code,
                                              str(exc), resp.headers)
        else:
            self.verbose = verbose
            return self.parse_response(resp.raw)

    def _build_url(self, host, handler):
        scheme = 'https' if self.use_https else 'http'
        return '%s://%s/%s' % (scheme, host, handler.lstrip('/'))


class PyPIEvents:
    """
    When treated as an iterator, this class yields (package, version, timestamp,
    action) tuples indicating new packages or package versions registered on
    PyPI where action is one of 'create', 'source', 'remove', 'yank' or
    'unyank'. A small attempt is made to avoid duplicate reports, but we don't
    attempt to avoid reporting stuff already in the database (it's simpler to
    just start from the beginning of PyPI's log and work through it).

    The iterator only retrieves a small batch of entries at a time as PyPI
    (very sensibly) limits the number of entries in a single query (to 50,000
    at the time of writing), so the instance will need repeated querying to
    retrieve all rows (this works in our favour though as it means there's an
    obvious place to poll for control events between batches).

    :param str pypi_root:
        The web address at which to find the PyPI XML-RPC server.

    :param int serial:
        The serial number of the event from which to start reading.

    :param int retries:
        The number of retries the class may attempt if the HTTP connection
        fails.

    :param int cache_size:
        The size of the internal cache used to attempt to avoid duplicate
        reports.
    """
    # pylint: disable=too-few-public-methods
    add_file_re = re.compile(r'^add ([^ ]+) file')
    create_re = re.compile(r'^create$')
    remove_re = re.compile(r'^remove(?: (?:package|release))?')
    yank_re = re.compile(r'^yank release$')
    unyank_re = re.compile(r'^unyank release$')

    def __init__(self, *, pypi_xmlrpc='https://pypi.org/pypi',
                 pypi_json='https://pypi.org/pypi',
                 serial=0, retries=3, cache_size=1000):
        self.retries = retries
        self.next_read = datetime.now(tz=UTC)
        self.serial = serial
        # Keep a list of the last cache_size (package, version) tuples so we
        # can make a vague attempt at reducing duplicate reports
        self.cache = OrderedDict()
        self.cache_size = cache_size
        self.transport = PiWheelsTransport()
        self.pypi_json = urlsplit(pypi_json)
        self.client = xmlrpc.client.ServerProxy(pypi_xmlrpc, self.transport)

    def _get_events(self):
        # On rare occasions we get some form of HTTP improper state, or DNS
        # lookups fail. In this case just return an empty list and try again
        # later. If we get a protocol error with error 5xx it's a server-side
        # problem, so we again return an empty list and try later
        try:
            return self.client.changelog_since_serial(self.serial)
        except (OSError, http.client.ImproperConnectionState):
            return []
        except xmlrpc.client.ProtocolError as exc:
            if exc.errcode >= 500:
                return []
            else:
                raise

    def _get_description(self, package):
        """
        Look up the project description for *package* using PyPI's legacy JSON
        API
        """
        path = PosixPath(self.pypi_json.path) / package / 'json'
        url = urlunsplit(self.pypi_json._replace(path=str(path)))
        resp = requests.get(url)
        if resp.status_code >= 500:
            # Server side error; probably a temporary service failure. Because
            # the package description isn't critical just ignore it and return
            # None for now and assume we'll pick it up at a later point
            return None
        elif resp.status_code == 404:
            # We may be requesting a description for a package that is
            # subsequently deleted; return None
            return None
        resp.raise_for_status()
        data = resp.json()
        try:
            description = data['info']['summary']
        except KeyError as exc:
            logger.error('%s missing when getting description for %s',
                         exc, package)
        else:
            if len(description) > 200:
                return description[:199] + '…'
            else:
                return description

    def _check_new_version(self, package, version, timestamp, action):
        try:
            self.cache.move_to_end((package, version))
        except KeyError:
            self.cache[(package, version)] = (timestamp, action)
            description = self._get_description(package)
            yield (package, version, timestamp, action, description)
        else:
            # This (package, version) combo was already cached; unless it's
            # a change from binary-only to source, don't bother emitting it
            (last_timestamp, last_action) = self.cache[(package, version)]
            if (last_action, action) == ('create', 'source'):
                self.cache[(package, version)] = (last_timestamp, action)
                # _get_description is relatively expensive (it's another
                # whole network transaction usually involving a fair chunk of
                # JSON) so only do it if we're not suppressing a repeated item
                description = self._get_description(package)
                yield (package, version, last_timestamp, action, description)
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)

    def __iter__(self):
        # The next_read flag is used to delay reads to PyPI once we get to the
        # end of the event log entries
        if datetime.now(tz=UTC) > self.next_read:
            events = self._get_events()
            if events:
                for (package, version, timestamp, action, serial) in events:
                    timestamp = datetime.fromtimestamp(timestamp, tz=UTC)
                    match = self.add_file_re.search(action)
                    if match is not None:
                        action = (
                            'source' if match.group(1) == 'source' else
                            'create')
                        yield from self._check_new_version(
                            package, version, timestamp, action)
                    elif self.create_re.search(action) is not None:
                        description = self._get_description(package)
                        yield (package, None, timestamp, 'create', description)
                    elif self.remove_re.search(action) is not None:
                        # If version is None here, indicating package deletion
                        # we could search and remove all corresponding versions
                        # from the cache but, frankly, it's not worth it
                        if version is not None:
                            self.cache.pop((package, version), None)
                        yield (package, version, timestamp, 'remove', None)
                    elif self.yank_re.search(action) is not None:
                        yield (package, version, timestamp, 'yank', None)
                    elif self.unyank_re.search(action) is not None:
                        yield (package, version, timestamp, 'unyank', None)
                    self.serial = serial
            else:
                # If the read is empty we've reached the end of the event log
                # or an error has occurred; make sure we don't bother PyPI for
                # another 10 seconds
                self.next_read = datetime.now(tz=UTC) + timedelta(seconds=10)
