import re
import logging
import http.client
import xmlrpc.client
from collections import namedtuple, deque
from time import sleep, time

logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

PackageVersion = namedtuple('PackageVersion', ('package', 'version'))


class PyPI():
    """
    When treated as an iterator, this class yields PackageVersion tuples
    indicating new packages or package versions registered on PyPI (only
    versions with files are reported). A small attempt is made to avoid
    duplicate reports, but we don't attempt to avoid reporting stuff already in
    the database (it's simpler to just start from the beginning of PyPI's log
    and work through it).

    When no more entries are found, the iterator ends. However, note that PyPI
    (very sensibly) limits the number of entries in a single query (to 50,000
    at the time of writing), so the instance will need repeated querying to
    retrieve all rows (this works in our favour though as it means we can poll
    the internal control queue between runs).

    The *pypi_root* argument configures the web address at which to find the
    PyPI XML-RPC server.
    """

    def __init__(self, pypi_root='https://pypi.python.org/pypi'):
        self.retries = 3
        self.next_read = 0
        self.last_serial = 0
        self.packages = set()
        # Keep a list of the last 100 (package, version) tuples so we can make
        # a vague attempt at reducing duplicate reports
        self.cache = deque(maxlen=100)
        self.client = xmlrpc.client.ServerProxy(pypi_root)

    def _get_events(self):
        # NOTE: starting at serial 0 doesn't return *all* records as PyPI (very
        # sensibly) limits the number of entries in a result set (to 50000 at
        # the time of writing). Also on rare occasions we get some form of HTTP
        # improper state, so allow retries
        for retry in range(self.retries, -1, -1):
            try:
                return self.client.changelog_since_serial(self.last_serial)
            except http.client.ImproperConnectionState:
                if retry:
                    sleep(5)
                else:
                    raise

    def __iter__(self):
        # First seed a list of all packages; there doesn't seem to be a specific
        # action for registering a new package on PyPI (or rather, there is,
        # but it seems uploads for a package can occur before the create event,
        # so it's more reliable to just keep a cache of the packages we've
        # seen and figure out new ones from there)
        if not self.packages:
            self.packages = set(self.client.list_packages())
            for package in self.packages:
                yield PackageVersion(package, None)
        # The next_read flag is used to delay reads to PyPI once we get to the
        # end of tthe event log entries
        if time() > self.next_read:
            events = self._get_events()
            if events:
                for (package, version, timestamp, action, serial) in events:
                    # If we've never seen the package before, report it as a new
                    # one
                    if package not in self.packages:
                        self.packages.add(package)
                        yield PackageVersion(package, None)
                    # If the event is adding a file, report a new version (we're
                    # only interested in versions with associated file releases)
                    if re.search('^add [^ ]+ file', action):
                        rec = PackageVersion(package, version)
                        if rec not in self.cache:
                            self.cache.append(rec)
                            yield rec
                    self.last_serial = serial
            else:
                # If the read is empty we've reached the end of the event log;
                # make sure we don't bother PyPI for another 10 seconds
                self.next_read = time() + 10
