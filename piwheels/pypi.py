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
from bisect import bisect_left
from operator import itemgetter
from functools import lru_cache
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit
from pathlib import PosixPath

import requests
from urllib3.exceptions import TimeoutError
from requests.exceptions import RequestException
from simplejson.errors import JSONDecodeError

from . import __version__
from .format import canonicalize_name


UTC = timezone.utc

# see notes in PyPIBuffer
PYPI_EPOCH = 628000
PYPI_MARGIN = 2000

logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger('pypi')


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


class PyPIBuffer:
    """
    An iterator that provides an ordered buffer of PyPI events from the
    specified *serial* number.

    Early PyPI events are ... a bit of mess. Prior to serial #628000 (roughly),
    events have a habit of jumping backwards in time, and not just by a few
    seconds but by several days or even years in some cases. This leads to all
    sorts of fun including deletions before packages exist, and so on. Even
    after #628000, timestamps can go backwards but never by more than 3 minutes
    (that I've seen so far).

    To work around this this class does several things. Considering #628000 as
    the "epoch" of reliability:

    1. If the starting *serial* is before the epoch, actually read from event 0
       and just start yielding once *serial* is reached as events before the
       epoch after effectively unordered.

    2. Buffer all events as they are received, sorting the buffer by timestamp.

    3. Yield nothing until the epoch is reached (actually 5 minutes after the
       epochal event).

    4. Once the epoch is reached only yield events once the maximum timestamp
       in the buffer is > 5 minutes after the event being yielded.

    5. For whatever starting serial is selected, actually start reading N
       serials earlier where N is currently 2000 which is a number larger than
       the maximum number of events PyPI has generated in a 5 minute period
       in the last few years (see note below).

    5. To permit the system to remain reasonably responsive, end iteration
       after each network transaction.

    In 2013, there was an anomalous 5 minute period during which >16k events
    appear. However, this appears to be a result of "tidying up" around the
    reliability epoch. Thereafter, the number of events in a 5 minute period
    has never exceeded 1480 (and even that was relatively anomalous), hence the
    selection of 2000 as a safety margin.

    This algorithm does have the strange side-effect that, if iterating from
    the start of the PyPI history, the first several iterations will yield
    nothing (while the class is buffering up to the epoch), then suddenly ~600k
    rows will suddenly appear. Thereafter, ~50k rows will be yielded at a time.
    """

    def __init__(self, *, serial=0, pypi_xmlrpc='https://pypi.org/pypi'):
        self._transport = PiWheelsTransport()
        self._client = xmlrpc.client.ServerProxy(pypi_xmlrpc, self._transport)
        self.serial = serial

    @property
    def serial(self):
        """
        The next smallest serial to yield. Defaults to 0. Can be set after
        construction but doing so while actually start from a point some way
        before the requested serial to deal with re-ordering of events. In
        the case of pre-epoch events (see class documentation), the buffer will
        actually read from the start anyway.

        Note that the actual serial requested may not exist as PyPI can "skip"
        serials (presumably due to transaction rollbacks), so this property
        simply guarantees that the next returned serial will be greater than or
        equal to the one requested.
        """
        return self._serial

    @serial.setter
    def serial(self, value):
        self._serial = value
        self._buffer = []
        self._next_serial = max(0, (
            0 if value < PYPI_EPOCH else value) - PYPI_MARGIN)
        self._serial_timestamp = None

    def _get_events(self, serial):
        # On rare occasions we get some form of HTTP improper state, or DNS
        # lookups fail. In this case just return an empty list and try again
        # later. If we get a protocol error with error 5xx it's a server-side
        # problem, so we again return an empty list and try later
        try:
            return [
                tuple(event) for event in
                self._client.changelog_since_serial(serial)
            ]
        except (OSError, http.client.ImproperConnectionState, TimeoutError) as exc:
            return []
        except xmlrpc.client.Fault as exc:
            if exc.faultCode == -32500:
                return []  # HTTPTooManyRequests; back off and try again
            else:
                raise
        except xmlrpc.client.ProtocolError as exc:
            if exc.errcode >= 500:
                return []
            else:
                raise

    def __iter__(self):
        events = self._get_events(self._next_serial)
        if not events:
            return
        # Tuple layout is (package, version, timestamp, action, serial) and
        # output of _get_events is assumed to be sorted by serial
        last_serial = self._next_serial
        self._next_serial = events[-1][4]
        if self._serial_timestamp is None and self._serial <= self._next_serial:
            # Find the timestamp of the event we want in the serial-sorted
            # events, so we can easily find it in the timestamp-sorted
            # buffer
            self._serial_timestamp = events[
                bisect_left([event[4] for event in events], self._serial)][2]
        self._buffer.extend(events)
        if self._next_serial <= PYPI_EPOCH:
            # Don't yield anything until we're past the epoch
            return
        if self._serial_timestamp is None:
            # We haven't yet located the serial we're seeking in the buffered
            # events
            return
        self._buffer.sort(key=itemgetter(2, 4))
        finish_timestamp = self._buffer[-1][2] - (5 * 60)
        if self._serial_timestamp >= finish_timestamp:
            # The serial we're seeking occurred within 5 minutes of the final
            # timestamp in the buffer; wait for more events
            return
        times = [event[2] for event in self._buffer]
        start = bisect_left(times, self._serial_timestamp)
        finish = bisect_left(times, finish_timestamp)
        # start is guaranteed to be at the same timestamp as serial, but
        # timestamps only have per-second resolution so there's likely to be
        # several serials with the same timestamp; wind start forward until we
        # find at least the serial as we're seeking (the serial we're seeking
        # isn't guaranteed to exist)
        while (
                self._buffer[start][2] == self._serial_timestamp and
                self._buffer[start][-1] < self._serial):
            start += 1
        assert self._buffer[start][2] == self._serial_timestamp
        assert start < finish
        for row in self._buffer[start:finish]:
            yield row
        self._serial_timestamp = self._buffer[finish][2]
        self._serial = self._buffer[finish][4]
        del self._buffer[:finish]


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

    :param int cache_size:
        The size of the internal cache used to attempt to avoid duplicate
        reports.
    """
    # pylint: disable=too-few-public-methods
    add_file_re = re.compile(r'^add ([^ ]+) file')
    create_re = re.compile(r'^create$')
    remove_re = re.compile(r'^remove(?: (?:project|release))?$')
    yank_re = re.compile(r'^yank release$')
    unyank_re = re.compile(r'^unyank release$')

    def __init__(self, *, pypi_xmlrpc='https://pypi.org/pypi',
                 pypi_json='https://pypi.org/pypi',
                 serial=0, cache_size=1000):
        self._buffer = PyPIBuffer(serial=serial, pypi_xmlrpc=pypi_xmlrpc)
        self._next_read = datetime.now(tz=UTC)
        # Keep a list of the last cache_size (package, version) tuples so we
        # can make a vague attempt at reducing duplicate reports
        self._versions = OrderedDict()
        self._versions_size = cache_size
        self._pypi_json = pypi_json

    @property
    def serial(self):
        return self._buffer.serial

    @serial.setter
    def serial(self, value):
        self._buffer.serial = value

    def _get_description(self, package):
        """
        Look up the project description for *package* using PyPI's legacy JSON
        API
        """
        return pypi_package_description(package, pypi_url=self._pypi_json)

    def _check_new_version(self, package, version, timestamp, action):
        try:
            self._versions.move_to_end((package, version))
        except KeyError:
            self._versions[(package, version)] = (timestamp, action)
            yield (package, version, timestamp, action)
        else:
            # This (package, version) combo was already cached; unless it's
            # a change from binary-only to source, don't bother emitting it
            (last_timestamp, last_action) = self._versions[(package, version)]
            if (last_action, action) == ('create', 'source'):
                self._versions[(package, version)] = (last_timestamp, action)
                yield (package, version, last_timestamp, action)
        while len(self._versions) > self._versions_size:
            self._versions.popitem(last=False)

    def __iter__(self):
        # The next_read flag is used to delay reads to PyPI once we get to the
        # end of the event log entries
        if datetime.now(tz=UTC) > self._next_read:
            events = list(self._buffer)
            if events:
                for (package, version, timestamp, action, serial) in events:
                    timestamp = datetime.fromtimestamp(timestamp, tz=UTC)
                    match = self.add_file_re.search(action)
                    if match is not None:
                        action = (
                            'source' if match.group(1) == 'source' else
                            'create')
                        for package, version, timestamp, action in \
                            self._check_new_version(
                                package, version, timestamp, action):
                            description = self._get_description(package)
                            yield (package, version, timestamp, action, description)
                    elif self.create_re.search(action) is not None:
                        description = self._get_description(package)
                        yield (package, None, timestamp, 'create', description)
                    elif self.remove_re.search(action) is not None:
                        # If version is None here, indicating package deletion
                        # we could search and remove all corresponding versions
                        # from the cache but, frankly, it's not worth it
                        if version is not None:
                            self._versions.pop((package, version), None)
                        yield (package, version, timestamp, 'remove', None)
                    elif self.yank_re.search(action) is not None:
                        yield (package, version, timestamp, 'yank', None)
                    elif self.unyank_re.search(action) is not None:
                        yield (package, version, timestamp, 'unyank', None)
            else:
                # If the read is empty we've reached the end of the event log
                # or an error has occurred; make sure we don't bother PyPI for
                # another 10 seconds
                self._next_read = datetime.now(tz=UTC) + timedelta(seconds=10)


@lru_cache(maxsize=100)
def pypi_package_description(package, pypi_url='https://pypi.org/pypi'):
    """
    Look up the project description for *package* using PyPI's legacy JSON
    API, rooted at *pypi_url*.
    """
    pypi_url = urlsplit(pypi_url)
    path = PosixPath(pypi_url.path) / package / 'json'
    url = urlunsplit(pypi_url._replace(path=str(path)))
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.Timeout:
        # SSL connection or read timed out; this isn't critical so just
        # return None and assume we'll pick it up later
        return None
    except requests.ConnectionError:
        # Failed to establish connection; usually "Connection refused"
        # which means we're hammering PyPI too much; give up for now and
        # assume we'll pick it up later
        return None
    except requests.exceptions.TooManyRedirects:
        # Too many redirects; again just return None as above
        return None
    except requests.HTTPError as exc:
        if exc.response.status_code >= 500:
            # Server side error; probably a temporary service failure.
            # Because the package description isn't critical just ignore it
            # and return None for now and assume we'll pick it up at a
            # later point
            return None
        elif exc.response.status_code == 404:
            # We may be requesting a description for a package that was
            # subsequently deleted; return None
            return None
        elif exc.response.status_code == 408:
            # Another timeout type; again just return None as above
            return None
        else:
            raise
    data = resp.json()
    try:
        description = data['info']['summary']
    except KeyError as exc:
        logger.error('%s missing when getting description for %s',
                     exc, package)
        return None
    else:
        if description is None:
            return ''
        elif len(description) > 200:
            return description[:199] + '…'
        else:
            return description
