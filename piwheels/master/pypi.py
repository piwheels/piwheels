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
        return '%s://%s/%s' % (scheme, host, handler)


class PyPIEvents:
    """
    When treated as an iterator, this class yields (package, version,
    timestamp, action) tuples indicating new packages or package versions
    registered on PyPI where action is one of 'create', 'source', or 'remove'.
    A small attempt is made to avoid duplicate reports, but we don't attempt to
    avoid reporting stuff already in the database (it's simpler to just start
    from the beginning of PyPI's log and work through it).

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

    def __init__(self, pypi_xmlrpc='https://pypi.org/pypi',
                 serial=0, retries=3, cache_size=1000):
        self.retries = retries
        self.next_read = datetime.now(tz=UTC)
        self.serial = serial
        # Keep a list of the last cache_size (package, version) tuples so we
        # can make a vague attempt at reducing duplicate reports
        self.cache = OrderedDict()
        self.cache_size = cache_size
        self.transport = PiWheelsTransport()
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
                        try:
                            self.cache.move_to_end((package, version))
                        except KeyError:
                            self.cache[(package, version)] = (timestamp, action)
                            yield (package, version, timestamp, action)
                        else:
                            (last_timestamp, last_action
                                ) = self.cache[(package, version)]
                            if (last_action, action) == ('create', 'source'):
                                self.cache[(package, version)] = (
                                    last_timestamp, action)
                                yield (package, version, last_timestamp, action)
                        while len(self.cache) > self.cache_size:
                            self.cache.popitem(last=False)
                    elif self.create_re.search(action) is not None:
                        yield (package, None, timestamp, 'create')
                    elif self.remove_re.search(action) is not None:
                        # If version is None here, indicating package deletion
                        # we could search and remove all corresponding versions
                        # from the cache but, frankly, it's not worth it
                        if version is not None:
                            self.cache.pop((package, version), None)
                        yield (package, version, timestamp, 'remove')
                    self.serial = serial
            else:
                # If the read is empty we've reached the end of the event log
                # or an error has occurred; make sure we don't bother PyPI for
                # another 10 seconds
                self.next_read = datetime.now(tz=UTC) + timedelta(seconds=10)


def get_project_description(package):
    "Look up the project description for *package* using PyPI's legacy JSON API"
    url = 'https://pypi.org/pypi/{}/json'.format(package)
    try:
        r = requests.get(url)
    except RequestException as e:
        logger.error('failed to retrieve project summary for %s: %s',
                     package, repr(e))
        return
    if r.status_code < 300:
        try:
            j = r.json()
        except JSONDecodeError as e:
            logger.error('failed to retrieve project summary for %s: %s',
                         package, repr(e))
            return
        try:
            description = j['info']['summary']
        except KeyError as e:
            logger.error('failed to retrieve project summary for %s: %s',
                         package, repr(e))
            return
        return description[:200] if description else None
    logger.error('failed to retrieve project summary for %s: status code %s',
                 package, r.status_code)
