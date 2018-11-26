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
from collections import deque
from datetime import datetime, timedelta

from .. import __version__


logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)


class PiWheelsTransport(xmlrpc.client.SafeTransport):
    # A Transport for the xmlrpc ServerProxy with a custom UA string (so
    # PyPI can identify our requests more easily in case we're being naughty!)
    user_agent = 'piwheels/%s' % __version__


class PyPIEvents:
    """
    When treated as an iterator, this class yields (package, version) tuples
    indicating new packages or package versions registered on PyPI (only
    versions with files are reported). A small attempt is made to avoid
    duplicate reports, but we don't attempt to avoid reporting stuff already in
    the database (it's simpler to just start from the beginning of PyPI's log
    and work through it).

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
    """
    # pylint: disable=too-few-public-methods

    def __init__(self, pypi_xmlrpc='https://pypi.org/pypi',
                 serial=0, retries=3):
        self.retries = retries
        self.next_read = datetime.utcnow()
        self.serial = serial
        # Keep a list of the last 100 (package, version) tuples so we can make
        # a vague attempt at reducing duplicate reports
        self.cache = deque(maxlen=100)
        self.transport = PiWheelsTransport()
        self.client = xmlrpc.client.ServerProxy(pypi_xmlrpc, self.transport)

    def _get_events(self):
        # On rare occasions we get some form of HTTP improper state, or DNS
        # lookups fail. In this case just return an empty list and try again
        # later
        try:
            return self.client.changelog_since_serial(self.serial)
        except (OSError, http.client.ImproperConnectionState):
            return []
        except xmlrpc.client.ProtocolError as exc:
            if exc.errcode >= 500:
                # Server error; something upstream has broken (gateway,
                # PyPI itself, whatever) so back off for a bit
                return []
            else:
                raise

    def __iter__(self):
        # The next_read flag is used to delay reads to PyPI once we get to the
        # end of the event log entries
        if datetime.utcnow() > self.next_read:
            events = self._get_events()
            if events:
                # pylint: disable=unused-variable
                for (package, version, timestamp, action, serial) in events:
                    if re.search('^add source file', action):
                        # If the event is adding a source file, report a new
                        # version (we're only interested in versions with
                        # associated source releases)
                        if (package, version) not in self.cache:
                            self.cache.append((package, version))
                            yield (package, version)
                    elif re.search('^create', action):
                        # Notify clients of package creation by yielding a
                        # package name with no version
                        yield (package, None)
                    self.serial = serial
            else:
                # If the read is empty we've reached the end of the event log
                # or an error has occurred; make sure we don't bother PyPI for
                # another 10 seconds
                self.next_read = datetime.utcnow() + timedelta(seconds=10)
