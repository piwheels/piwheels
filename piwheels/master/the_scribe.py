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
Defines the :class:`TheScribe` task; see class for more details.

.. autoclass:: TheScribe
    :members:
"""

import re
import io
import os
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from itertools import zip_longest

import pkg_resources
from chameleon import PageTemplateLoader
try:
    import simplejson as json
except ImportError:
    import json

from .. import const, protocols, tasks, transport
from ..format import format_size
from ..states import mkdir_override_symlink
from .the_oracle import DbClient


UTC = timezone.utc
dt_format = '%Y-%m-%d %H:%M'


class TheScribe(tasks.PauseableTask):
    """
    This task is responsible for writing web-page ``index.html`` files. It
    reads the names of packages off the internal "indexes" queue and rebuilds
    the ``index.html`` for that package and, optionally, the overall
    ``index.html`` if the package is one that wasn't previously present.

    .. note::

        It is important to note that package names are never pushed into the
        internal "indexes" queue until all file-transfers associated with the
        build are complete. Furthermore, while the entire index for a package
        is re-built, hashes are *never* re-calculated from the disk files (they
        are always read from the database).
    """
    name = 'master.the_scribe'

    def __init__(self, config):
        super().__init__(config)
        self.output_path = Path(config.output_path)
        scribe_queue = self.socket(
            transport.PULL, protocol=protocols.the_scribe)
        scribe_queue.hwm = 100
        scribe_queue.bind(const.SCRIBE_QUEUE)
        self.register(scribe_queue, self.handle_index)
        self.db = DbClient(config, self.logger)
        self.package_cache = None
        self.statistics = {}
        with pkg_resources.resource_stream(__name__, 'default_libs.txt') as s:
            with io.TextIOWrapper(s, encoding='ascii') as t:
                self.default_libs = set(line.strip() for line in t)
        self.templates = PageTemplateLoader(
            search_path=[
                pkg_resources.resource_filename(__name__, 'templates')
            ],
            default_extension='.pt')

    def close(self):
        self.db.close()
        super().close()
        pkg_resources.cleanup_resources()

    def once(self):
        self.setup_output_path()
        self.logger.info('building package cache')
        self.package_cache = self.db.get_all_packages()
        # Perform a one-time write of the root index if it doesn't exist; this
        # is primarily for limited setups which don't expect to see "new"
        # packages show up (the usual trigger for re-writing the root index)
        if not (self.output_path / 'simple' / 'index.html').exists():
            self.write_simple_index()

    def setup_output_path(self):
        """
        Called on task startup to copy all static resources into the output
        path (and to make sure the output path exists as a directory).
        """
        self.logger.info('setting up output path')
        required_paths = (
            self.output_path,
            self.output_path / 'simple',
            self.output_path / 'project',
        )
        for path in required_paths:
            try:
                path.mkdir()
            except FileExistsError:
                pass
        for filename in pkg_resources.resource_listdir(__name__, 'static'):
            source = pkg_resources.resource_stream(__name__, 'static/' + filename)
            with AtomicReplaceFile(self.output_path / filename) as f:
                shutil.copyfileobj(source, f)
        startup_templates = {'index.pt', 'faq.pt', 'packages.pt', 'stats.pt', 'json.pt'}
        for filename in pkg_resources.resource_listdir(__name__, 'templates'):
            if filename in startup_templates:
                source = self.templates[filename](
                        layout=self.templates['layout']['layout'],
                        page=filename.replace('.pt', '')
                    )
                with AtomicReplaceFile(
                        (self.output_path / filename).with_suffix('.html'),
                        encoding='utf-8') as f:
                    f.write(source)

    def handle_index(self, queue):
        """
        Handle incoming requests to (re)build index files. These will be in the
        form of:

        * "HOME", a request to write the homepage with some associated
          statistics
        * "PKGBOTH", a request to write the index and project page for
          the specified package
        * "PKGPROJ", a request to write just the project page for the specified
          package

        .. note::

            In all handlers below, care is taken to ensure clients never see a
            partially written file and that temporary files are cleaned up in
            the event of any exceptions.
        """
        try:
            msg, data = queue.recv_msg()
        except IOError as e:
            self.logger.error(str(e))
        else:
            if msg == 'PKGBOTH':
                package = data
                if package not in self.package_cache:
                    self.package_cache.add(package)
                    self.write_simple_index()
                self.write_package_index(package)
                self.write_project_page(package)
                self.write_project_json(package)
            elif msg == 'PKGPROJ':
                package = data
                self.write_project_page(package)
                self.write_project_json(package)
            elif msg == 'HOME': # this doesn't write the homepage anymore
                status_info = data
                self.write_statistics_json(status_info)
                self.write_sitemap()
            elif msg == 'SEARCH':
                search_index = data
                self.write_search_index(search_index)

    def write_statistics_json(self, data):
        """
        Re-writes the statistics JSON file, which provides dynamic data to the
        homepage.

        :param dict data:
            A dict containing statistics obtained by :class:`BigBrother`.
        """
        self.logger.info('writing statistics json')
        with AtomicReplaceFile(self.output_path / 'statistics.json',
                               encoding='utf-8') as index:
            statistics = {
                'num_packages': data['packages_built'],
                'num_versions': 0,
                'num_wheels': data['files_count'],
                'downloads_day': 0,
                'downloads_week': 0,
                'downloads_month': data['downloads_last_month'],
                'downloads_year': 0,
                'downloads_all': data['downloads_all'],
                'downloads_bandwidth_bytes': 10e12,
                'downloads_bandwidth': '10TB',
                'time_saved_day': 0,
                'time_saved_week': 0,
                'time_saved_month': 0,
                'time_saved_year': 0,
                'time_saved_all': 0,
                'energy_saved_all': 0,
                'top_10_packages_month': [
                    ['pycparser', 56507],
                    ['numpy', 76970],
                    ['PyYAML', 65887],
                    ['cffi', 56522],
                    ['tensorflow', 49508],
                    ['cryptography', 48071],
                    ['MarkupSafe', 44944],
                    ['future', 42133],
                    ['home-assistant-frontend', 38750],
                    ['paho-mqtt', 36273],
                ],
                'top_30_packages_all': [
                    ['pycparser', 203432],
                    ['home-assistant-frontend', 157924],
                    ['PyYAML', 153907],
                    ['cffi', 143998],
                    ['MarkupSafe', 138488],
                    ['SQLAlchemy', 133629],
                    ['multidict', 132226],
                    ['numpy', 130044],
                    ['aiohttp', 129322],
                    ['future', 121117],
                    ['cryptography', 109670],
                    ['idna_ssl', 109317],
                    ['mutagen', 100491],
                    ['user-agents', 81608],
                    ['netifaces', 79248],
                    ['pycryptodome', 78503],
                    ['gTTS-token', 75068],
                    ['yarl', 73824],
                    ['voluptuous-serialize', 71656],
                    ['paho-mqtt', 63925],
                    ['bcrypt', 58017],
                    ['RPi.GPIO', 50246],
                    ['Pillow', 48757],
                    ['docopt', 43908],
                    ['psutil', 40205],
                    ['PyQRCode', 39436],
                    ['matplotlib', 38412],
                    ['tensorflow', 38335],
                    ['opencv-python', 37274],
                    ['ifaddr', 36804],
                ],
                'downloads_by_month': [
                    # last 12 full months
                    ['2019-01-01', 100000],
                    ['2019-02-01', 200000],
                    ['2019-03-01', 300000],
                    ['2019-04-01', 400000],
                    ['2019-05-01', 500000],
                    ['2019-06-01', 600000],
                    ['2019-07-01', 700000],
                    ['2019-08-01', 800000],
                    ['2019-09-01', 900000],
                    ['2019-10-01', 1000000],
                    ['2019-11-01', 1100000],
                    ['2019-12-01', 1200000],
                ],
                'downloads_by_day': [
                    # need a year's worth here
                    ['2019-01-01', 1000],
                    ['2019-01-02', 1100],
                    ['2019-01-03', 1200],
                    ['2019-01-04', 1300],
                    ['2019-01-05', 1400],
                    ['2019-01-06', 1300],
                    ['2019-01-07', 1200],
                    ['2019-01-08', 1100],
                    ['2019-01-09', 1100],
                    ['2019-01-10', 1200],
                    ['2019-01-11', 1400],
                    ['2019-01-12', 1500],
                    ['2019-01-13', 1600],
                    ['2019-01-14', 1800],
                    ['2019-01-15', 2000],
                    ['2019-01-16', 1900],
                    ['2019-01-17', 1900],
                    ['2019-01-18', 2100],
                    ['2019-01-19', 2200],
                    ['2019-01-20', 2300],
                    ['2019-01-21', 2400],
                    ['2019-01-22', 2400],
                    ['2019-01-23', 2000],
                    ['2019-01-24', 2100],
                    ['2019-01-25', 2100],
                    ['2019-01-26', 2200],
                    ['2019-01-27', 2100],
                    ['2019-01-28', 2300],
                    ['2019-01-29', 2300],
                    ['2019-01-30', 2200],
                    ['2019-01-31', 2100],
                ],
                'time_saved_by_month': [
                    # last 12 full months - value in years
                    ['2019-01-01', 4.5],
                    ['2019-02-01', 5.2],
                    ['2019-03-01', 6],
                    ['2019-04-01', 7],
                    ['2019-05-01', 7],
                    ['2019-06-01', 8],
                    ['2019-07-01', 10],
                    ['2019-08-01', 11],
                    ['2019-09-01', 12],
                    ['2019-10-01', 12],
                    ['2019-11-01', 11],
                    ['2019-12-01', 12],
                ],
                'python_versions_by_month': [
                    # last 12 full months - value in %
                    ['3.4', [['2019-01-01', 5], ['2019-02-01', 4], ['2019-03-01', 3]]],
                    ['3.5', [['2019-01-01', 90], ['2019-02-01', 85], ['2019-03-01', 25]]],
                    ['3.7', [['2019-01-01', 5], ['2019-02-01', 11], ['2019-03-01', 72]]],
                ],
                'arch_by_month': [
                    # last 12 full months - value in %
                    ['linux_armv6l', [['2019-01-01', 20], ['2019-02-01', 19], ['2019-03-01', 17]]],
                    ['linux_armv7l', [['2019-01-01', 75], ['2019-02-01', 77], ['2019-03-01', 79]]],
                    ['x86_64', [['2019-01-01', 1], ['2019-02-01', 2], ['2019-03-01', 2]]],
                    ['x86', [['2019-01-01', 4], ['2019-02-01', 2], ['2019-03-01', 1]]],
                ],
                'os_by_month': [
                    # last 12 full months - value in %
                    ['Raspbian', [['2019-01-01', 95], ['2019-02-01', 93], ['2019-03-01', 90]]],
                    ['Ubuntu', [['2019-01-01', 5], ['2019-02-01', 7], ['2019-03-01', 10]]],
                ],
                'raspbian_versions_by_month': [
                    # last 12 full months - value in %
                    ['Jessie', [['2019-01-01', 5], ['2019-02-01', 4], ['2019-03-01', 3]]],
                    ['Stretch', [['2019-01-01', 90], ['2019-02-01', 85], ['2019-03-01', 25]]],
                    ['Buster', [['2019-01-01', 5], ['2019-02-01', 11], ['2019-03-01', 72]]],
                ],
                'updated': datetime.now(tz=UTC).strftime(dt_format),
            }
            json.dump(statistics, index.file, check_circular=False,
                      separators=(',', ':'))

    def write_search_index(self, search_index):
        """
        Re-writes the JSON search index using the provided statistics.

        :param dict search_index:
            A dict mapping package names to their download count obtained by
            :class:`BigBrother`.
        """
        self.logger.info('writing search index')
        with AtomicReplaceFile(self.output_path / 'packages.json',
                               encoding='utf-8') as index:
            # Re-organize into a list of package, count tuples as this is
            # what the JS actually wants
            search_index = [
                (package, count_recent, count_all)
                for package, (count_recent, count_all) in search_index.items()
            ]
            json.dump(search_index, index.file,
                      check_circular=False, separators=(',', ':'))

    def write_sitemap(self):
        """
        (Re)writes the XML sitemap pages and index.
        """
        self.logger.info('writing sitemap')

        pages = ['index.html', 'packages.html', 'faq.html', 'stats.html', 'json.html']
        with AtomicReplaceFile(self.output_path / 'sitemap0.xml',
                               encoding='utf-8') as page:
            page.file.write(self.templates['sitemap_static'](pages=pages))
        links_per_page = 50000  # google sitemap limit
        n = 0
        pages = grouper(self.package_cache, links_per_page)
        for n, packages in enumerate(pages, start=1):
            with AtomicReplaceFile(self.output_path / 'sitemap{}.xml'.format(n),
                                   encoding='utf-8') as page:
                page.file.write(self.templates['sitemap_page'](
                    packages=packages)
                )
        dt = datetime.now()
        with AtomicReplaceFile(self.output_path / 'sitemap.xml',
                             encoding='utf-8') as sitemap:
          sitemap.file.write(self.templates['sitemap_index'](
              pages=range(n),
              timestamp=dt.strftime('%Y-%m-%d'))
          )

    def write_simple_index(self):
        """
        (Re)writes the index of all packages. This is implicitly called when a
        request to write a package index is received for a package not present
        in the task's cache.
        """
        self.logger.info('writing package index')
        with AtomicReplaceFile(self.output_path / 'simple' / 'index.html',
                               encoding='utf-8') as index:
            index.file.write(self.templates['simple_index'](
                packages=self.package_cache))

    def write_package_index(self, package):
        """
        (Re)writes the index of the specified package. The file meta-data
        (including the hash) is retrieved from the database, *never* from the
        file-system.

        :param str package:
            The name of the package to write the index for
        """
        self.logger.info('writing index for %s', package)
        pkg_dir = self.output_path / 'simple' / package
        mkdir_override_symlink(pkg_dir)
        files = sorted(
            self.db.get_project_files(package),
            key=lambda row: (
                pkg_resources.parse_version(row.version),
                row.filename
            ), reverse=True)
        with AtomicReplaceFile(pkg_dir / 'index.html',
                               encoding='utf-8') as index:
            index.file.write(self.templates['simple_package'](
                package=package,
                files=files
            ))
        try:
            # Workaround for #20: after constructing the index for a package
            # attempt to symlink the "canonicalized" package name to the actual
            # package directory. The reasons for doing things this way are
            # rather complex...
            #
            # The older package name must exist for the benefit of older
            # versions of pip. If the symlink already exists *or is a
            # directory* we ignore it. Yes, it's possible to have two packages
            # which both have the same canonicalized name, and for each to have
            # different contents. I don't quite know how PyPI handle this but
            # their XML and JSON APIs already include such situations (in a
            # small number of cases). This setup is designed to create
            # canonicalized links where possible but not to clobber "real"
            # packages if they exist.
            #
            # What about new packages that want to take the place of a
            # canonicalized symlink? We (and TransferState.commit) handle that
            # by removing the symlink and making a directory in its place.
            canon_dir = pkg_dir.with_name(canonicalize_name(pkg_dir.name))
            canon_dir.symlink_to(pkg_dir.name)
        except FileExistsError:
            pass

    def write_project_page(self, package):
        """
        (Re)writes the project page of the specified package.

        :param str package:
            The name of the package to write the project page for
        """
        self.logger.info('writing project page for %s', package)
        pkg_dir = self.output_path / 'project' / package
        mkdir_override_symlink(pkg_dir)
        with AtomicReplaceFile(pkg_dir / 'index.html', encoding='utf-8') as index:
            index.file.write(self.templates['project'](
                layout=self.templates['layout']['layout'],
                page='project',
                package=package))
        try:
            # See write_package_index for explanation...
            canon_dir = pkg_dir.with_name(canonicalize_name(pkg_dir.name))
            canon_dir.symlink_to(pkg_dir.name)
        except FileExistsError:
            pass

    def write_project_json(self, package):
        """
        (Re)writes the JSON file for the specified package.

        :param str package:
            The name of the package to write the JSON file for
        """
        self.logger.info('writing json file for %s', package)
        pkg_dir = self.output_path / 'project' / package / 'json'
        mkdir_override_symlink(pkg_dir)
        versions = self.get_project_versions_and_files(package)
        json_file = pkg_dir / 'index.json'
        with AtomicReplaceFile(json_file, encoding='utf-8') as index:
            package_info = {
                'package': package,
                'num_versions': get_num_versions(versions),
                'num_files': get_num_files(versions),
                'versions': versions,
                'num_downloads': get_num_downloads(package),
                'num_downloads_30_days': get_num_downloads_30_days(package),
                'downloads': get_downloads(package),
                'project_url': 'https://www.piwheels.org/project/{}'.format(package),
                'simple_url': 'https://www.piwheels.org/simple/{}'.format(package),
                'updated': datetime.now(tz=UTC).strftime(dt_format),
            }
            json.dump(package_info, index.file, check_circular=False,
                      separators=(',', ':'))

    def get_project_versions_and_files(self, package):
        """
        Returns a list of all versions for the specified *package*, including
        nested details of all files, for the JSON file.
        """
        data = self.db.get_project_versions(package)
        versions = {}
        for (version, released, build_id, skip, duration, status, filename,
             filesize, filehash, builder_abi, file_abi_tag, platform_tag,
             apt_dependencies) in data:
            if version not in versions:
                versions[version] = {
                    'released': released.strftime(dt_format),
                    'skip': skip,
                    'builds': {},
                }
            if status:
                if file_abi_tag not in versions[version]['builds']:
                    versions[version]['builds'][file_abi_tag] = {
                        'successful_builds': {},
                        'failed_builds': {},
                    }
                versions[version]['builds'][file_abi_tag]['successful_builds'][platform_tag] = {
                    'build_id': build_id,
                    'builder_abi': builder_abi,
                    'filename': filename,
                    'filesize': filesize,
                    'filesize_human': format_size(filesize),
                    'filehash': filehash,
                    'duration': duration_to_secs(duration),
                    'duration_adjusted': duration_adjusted(duration, platform_tag),
                    'apt_dependencies': apt_dependencies,
                    'url': 'https://www.piwheels.org/simple/{}/{}'.format(package, filename),
                }
            elif build_id:
                if builder_abi not in versions[version]['builds']:
                    versions[version]['builds'][builder_abi] = {
                        'successful_builds': {},
                        'failed_builds': {},
                    }
                versions[version]['builds'][builder_abi]['failed_builds'] = {
                    'build_id': build_id,
                    'duration': duration_to_secs(duration),
                }
        return versions

# From pip/_vendor/packaging/utils.py
# pylint: disable=invalid-name
_canonicalize_regex = re.compile(r"[-_.]+")


def canonicalize_name(name):
    # pylint: disable=missing-docstring
    # This is taken from PEP 503.
    return _canonicalize_regex.sub("-", name).lower()


# https://docs.python.org/3/library/itertools.html
def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)

def get_num_versions(versions):
    "Return the number of versions we have for a package from its versions dict"
    return len([
        1 for v in versions.values()
        if get_num_files_for_version(v['builds']) > 0
    ])

def get_num_files(versions):
    "Return the number of files we have for a package from its versions dict"
    return sum(
        get_num_files_for_version(v['builds'])
        for v in versions.values()
    )

def get_num_files_for_version(builds):
    """
    Return the number of files we have for a particular version of a package
    from its builds dict
    """
    return sum(len(b['successful_builds']) for b in builds.values())

def duration_to_secs(duration):
    "Convert duration to seconds. If duration is more than a day, return None."
    if duration:
        if duration < timedelta(days=1):
            duration = str(duration)
            if ':' in duration:
                h, m, s = (float(n) for n in duration.split(':'))
                return h * 60 * 60 + m * 60 + s

def duration_adjusted(duration, platform):
    "Return the platform-adjusted duration in seconds (6x for armv6)"
    duration = duration_to_secs(duration)
    if duration:
        return duration * (6 if platform == 'linux_armv6l' else 1)

def get_num_downloads(package):
    "Return the total number of downloads a package has had"
    return 0

def get_num_downloads_30_days(package):
    "Return the number of downloads a package has had in the last 30 days"
    return 0

def get_downloads(package):
    "Return a list of (date, num_downloads) tuples for a package"
    return [
        ('2019-01-01', 100),
        ('2019-01-02', 110),
        ('2019-01-03', 120),
        ('2019-01-04', 130),
        ('2019-01-05', 140),
        ('2019-01-06', 150),
        ('2019-01-07', 160),
        ('2019-01-08', 170),
        ('2019-01-09', 100),
        ('2019-01-10', 110),
        ('2019-01-11', 120),
        ('2019-01-12', 130),
        ('2019-01-13', 140),
        ('2019-01-14', 150),
        ('2019-01-15', 160),
        ('2019-01-16', 170),
        ('2019-01-17', 160),
        ('2019-01-18', 170),
        ('2019-01-19', 100),
        ('2019-01-20', 110),
        ('2019-01-21', 120),
        ('2019-01-22', 130),
        ('2019-01-23', 140),
        ('2019-01-24', 150),
        ('2019-01-25', 160),
        ('2019-01-26', 170),
        ('2019-01-27', 160),
        ('2019-01-28', 170),
        ('2019-01-29', 100),
        ('2019-01-30', 100),
    ]


class AtomicReplaceFile:
    """
    A context manager for atomically replacing a target file.

    Uses :class:`tempfile.NamedTemporaryFile` to construct a temporary file in
    the same directory as the target file. The associated file-like object is
    returned as the context manager's variable; you should write the content
    you wish to this object.

    When the context manager exits, if no exception has occurred, the temporary
    file will be renamed over the target file atomically (and sensible
    permissions will be set, i.e. 0644 & umask).  If an exception occurs during
    the context manager's block, the temporary file will be deleted leaving the
    original target file unaffected and the exception will be re-raised.

    :param pathlib.Path path:
        The full path and filename of the target file. This is expected to be
        an absolute path.

    :param str encoding:
        If ``None`` (the default), the temporary file will be opened in binary
        mode. Otherwise, this specifies the encoding to use with text mode.
    """
    def __init__(self, path, encoding=None):
        if isinstance(path, str):
            path = Path(path)
        self._path = path
        self._tempfile = tempfile.NamedTemporaryFile(
            mode='wb' if encoding is None else 'w',
            dir=str(self._path.parent), encoding=encoding, delete=False)
        self._withfile = None

    def __enter__(self):
        self._withfile = self._tempfile.__enter__()
        return self._withfile

    def __exit__(self, exc_type, exc_value, exc_tb):
        os.fchmod(self._withfile.file.fileno(), 0o644)
        result = self._tempfile.__exit__(exc_type, exc_value, exc_tb)
        if exc_type is None:
            os.rename(self._withfile.name, str(self._path))
        else:
            os.unlink(self._withfile.name)
        return result
