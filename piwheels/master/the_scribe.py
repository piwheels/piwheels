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

import os
import gzip
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from itertools import zip_longest
from operator import itemgetter
from collections import namedtuple

import pkg_resources
from chameleon import PageTemplateLoader
import simplejson as json

from .. import const, protocols, tasks, transport
from ..format import format_size
from ..states import mkdir_override_symlink, MasterStats
from .the_oracle import DbClient

UTC = timezone.utc


ProjectRelease = namedtuple('ProjectRelease', (
    'version', 'yanked', 'released', 'skip', 'abis', 'files',
    'builds_succeeded', 'builds_failed'))


class PackageDeleted(ValueError):
    "Error raised when a package is deleted and doesn't need updating"


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
            transport.REP, protocol=protocols.the_scribe)
        scribe_queue.hwm = 100
        scribe_queue.bind(const.SCRIBE_QUEUE)
        self.register(scribe_queue, self.handle_index)
        self.db = DbClient(config, self.logger)
        self.package_cache = None
        self.statistics = {}
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
        startup_templates = {
            'faq.pt': ('FAQ', 'frequently asked questions about the piwheels project'),
            'packages.pt': ('Package search', 'search for packages in the piwheels repository'),
            'stats.pt': ('Stats', 'piwheels usage statistics'),
            'json.pt': ('JSON API', 'information about the piwheels JSON API'),
            '404.pt': ('404 - file not found', 'file not found'),
        }
        for filename in pkg_resources.resource_listdir(__name__, 'templates'):
            if filename in startup_templates:
                title, description = startup_templates[filename]
                source = self.templates[filename](
                    layout=self.templates['layout']['layout'],
                    page=filename.replace('.pt', ''),
                    title=title,
                    description=description,
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

        * "BOTH", a request to write the index and project page for the
          specified package

        * "PROJECT", a request to write just the project page for the specified
          package

        * "LOG", a request to write a build log

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
            if msg in ('BOTH', 'PROJECT'):
                package = data
                if msg == 'BOTH':
                    self.write_pages(package, both=True)
                else:
                    self.write_pages(package)
            elif msg == 'HOME':
                self.write_homepage(MasterStats.from_message(data))
                self.write_sitemap()
            elif msg == 'SEARCH':
                search_index = data
                self.write_search_index(search_index)
            elif msg == 'LOG':
                build_id, log = data
                self.write_log(build_id, log)
            elif msg == 'DELVER':
                package, version = data
                self.delete_version(package, version)
                self.write_pages(package, both=True, exclude={version})
            elif msg == 'DELPKG':
                package = data
                self.package_cache.discard(package)
                self.write_simple_index()
                self.delete_package(package)
            queue.send_msg('DONE')

    def write_homepage(self, statistics):
        """
        Re-writes the site homepage using the provided statistics in the
        homepage template (which is effectively a simple Python format string).

        :param dict statistics:
            A dict containing statistics obtained by :class:`BigBrother`.
        """
        self.logger.info('writing homepage')
        dt = datetime.now(tz=UTC)
        with AtomicReplaceFile(self.output_path / 'index.html',
                               encoding='utf-8') as index:
            index.file.write(self.templates['index'](
                layout=self.templates['layout']['layout'],
                timestamp=dt.strftime('%Y-%m-%d %H:%M %Z'),
                page='home',
                title='Home',
                description='Python package repository providing wheels for Raspberry Pi',
                stats=statistics,
            ))

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

        pages = ['index.html', 'packages.html', 'faq.html', 'json.html', 'stats.html']
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

    def write_pages(self, package, *, both=False, exclude=None):
        """
        (Re)writes the project page and project JSON file (and simple index if
        *both* is True) for the specified *package*.

        :param str package:
            The name of the package to write the pages for

        :param bool both:
            Write both the project page and the simple page if True, otherwise
            only write the project page. Note project page also includes
            project JSON.

        :type exclude: set or None
        :param exclude:
            The set of (deleted) versions to exclude from pages. Defaults to
            ``None``.
        """
        if exclude is None:
            exclude = set()

        data = self.db.get_project_data(package)
        # Rewrite versions as version objects, exclude deleted versions, and
        # sort the releases dict by the parsed version
        data['releases'] = {
            parse_version(version): vers_data
            for version, vers_data in data['releases'].items()
            if version not in exclude
        }
        data['releases'] = {
            version: vers_data
            for version, vers_data in sorted(
                data['releases'].items(), key=itemgetter(0), reverse=True)
        }

        if both:
            self.write_package_index(package, data)
        self.write_project_page(package, data)
        self.write_project_json(package, data)

    def write_package_index(self, package, data):
        """
        (Re)writes the index of the specified *package*. The file meta-data
        (including the hash) is retrieved from the database, *never* from the
        file-system.

        The *data* parameter is expected to be the dictionary of
        package data returned by :meth:`.db.Database.get_project_data`. This
        is expected to have at least the following content in the example case
        of a package named "foo" with version "1.0" containing a validly built
        wheel::

            {
                'releases': {
                    '1.0': {
                        'files': {
                            'foo-1.0-py3-none-any.whl': {
                                'hash': 'abcdef1234567890...',
                                'requires_python': '>= 3.6',
                            },
                        },
                        'yanked': False,
                    },
                },
            }

        :param str package:
            The name of the package to write the index page for.

        :param dict data:
            The dictionary of data returned by
            :meth:`.db.Database.get_project_data` which is expected to have
            at least the structure documented above.
        """
        self.logger.info('writing index for %s', package)

        files = [
            {
                'filename': filename,
                'filehash': file_data['hash'],
                'requires_python': file_data['requires_python'],
                'yanked': vers_data['yanked'],
            }
            for vers, vers_data in data['releases'].items()
            for filename, file_data in vers_data['files'].items()
        ]

        pkg_dir = self.output_path / 'simple' / package
        mkdir_override_symlink(pkg_dir)
        with AtomicReplaceFile(pkg_dir / 'index.html',
                               encoding='utf-8') as index:
            index.file.write(
                self.templates['simple_package'](
                    package=package,
                    files=files))
        if package not in self.package_cache:
            self.package_cache.add(package)
            self.write_simple_index()

    def write_project_page(self, package, data):
        """
        (Re)writes the project page of the specified package.

        The *data* parameter is expected to be the dictionary of
        package data returned by :meth:`.db.Database.get_project_data`. This
        is expected to have at least the following content in the example case
        of a package named "foo" with version "1.0" containing a validly built
        wheel::

            {
                'name': 'foo',
                'description': 'A foomatic package',
                'releases': {
                    '1.0': {
                        'abis': {
                            'cp35m': {
                                'build_id': 1,
                                'status': 'success',
                                'skip': '',
                            }
                        }
                        'files': {
                            'foo-1.0-py3-none-any.whl': {
                                'hash': 'abcdef1234567890...',
                                'size': 123456,
                                'apt_dependencies': {'libc6'},
                            },
                        },
                        'released': datetime(2000, 1, 1, 12, 34, 56),
                        'yanked': False,
                        'skip': '',
                    },
                },
            }

        :param str package:
            The name of the package to write the project page for.

        :param dict data:
            The dictionary of data returned by
            :meth:`.db.Database.get_project_data` which is expected to have
            at least the structure documented above.
        """
        self.logger.info('writing project page for %s', package)

        # This horribly confusing loop simply serves to efficiently extract
        # the apt_dependencies from the latest successful build, which is
        # reported (by default) as the dependencies at the top of the project
        # page. Ideally this would be done in the template, but the logic is
        # just too horrid to do nicely there. We *could* resort to javascript
        # picking the dependencies from the first row of the table, but that
        # then denies non-JS browsers (or search engines) any dependency info
        dependencies = set()
        for version, release in data['releases'].items():
            if not (version.is_prerelease or release['yanked']):
                for filedata in release['files'].values():
                    dependencies = filedata['apt_dependencies']
                    break
                else:
                    continue
                break

        # Add some more useful context to the template; a hard-coded map of
        # ABIs to Debian and Python versions (this should be incorporated into
        # the database at some point), and a list of all ABIs involved in the
        # package.
        known_abis = {
            'cp34m': ('Jessie',   'Python 3.4'),
            'cp35m': ('Stretch',  'Python 3.5'),
            'cp37m': ('Buster',   'Python 3.7'),
            'cp39':  ('Bullseye', 'Python 3.9'),
            'cp311': ('Bookworm', 'Python 3.11'),
        }
        abi_order = list(known_abis) + list(
            abi
            for vers_data in data['releases'].values()
            for abi in vers_data['abis']
            if abi not in known_abis
        )
        all_abis = sorted({
            abi
            for vers_data in data['releases'].values()
            for abi in vers_data['abis']}, key=abi_order.index
        )

        project_dir = self.output_path / 'project' / package
        mkdir_override_symlink(project_dir)
        dt = datetime.now(tz=UTC)
        with AtomicReplaceFile(project_dir / 'index.html', encoding='utf-8') as index:
            index.file.write(
                self.templates['project'](
                    layout=self.templates['layout']['layout'],
                    title=data['name'],
                    description=data['description'],
                    timestamp=datetime.now(tz=UTC),
                    page='project',
                    package=package,
                    releases=data['releases'],
                    dependencies=dependencies,
                    format_size=format_size,
                    known_abis=known_abis,
                    all_abis=all_abis))

        project_aliases = self.db.get_package_aliases(package)
        if project_aliases:
            self.logger.info('creating %s symlinks for project %s',
                             len(project_aliases), package)
        for project_alias in project_aliases:
            project_symlink = self.output_path / 'project' / project_alias
            try:
                project_symlink.symlink_to(project_dir.name)
            except FileExistsError:
                pass

    def write_project_json(self, package, data):
        """
        (Re)writes the project JSON data of the specified package.

        The *data* parameter is expected to be the dictionary of
        package data returned by :meth:`.db.Database.get_project_data`. This
        is expected to have at least the following content in the example case
        of a package named "foo" with version "1.0" containing a validly built
        wheel::

            {
                'name': 'foo',
                'description': 'A foomatic package',
                'releases': {
                    '1.0': {
                        'abis': {
                            'cp35m': {
                                'build_id': 1,
                                'status': 'success',
                                'skip': '',
                            }
                        }
                        'files': {
                            'foo-1.0-py3-none-any.whl': {
                                'hash': 'abcdef1234567890...',
                                'size': 123456,
                                'apt_dependencies': {'libc6'},
                            },
                        },
                        'released': datetime(2000, 1, 1, 12, 34, 56),
                        'yanked': False,
                        'skip': '',
                    },
                },
            }

        :param str package:
            The name of the package to write the project data for.

        :param dict data:
            The dictionary of data returned by
            :meth:`.db.Database.get_project_data` which is expected to have
            at least the structure documented above.
        """
        self.logger.info('writing project json for %s', package)

        project_data = {
            'package': package,
            'summary': data['description'],
            'pypi_url': 'https://pypi.org/project/{}'.format(package),
            'piwheels_url': 'https://www.piwheels.org/project/{}'.format(package),
            'releases': {
                version.original: {
                    'released': vers_data['released'].strftime('%Y-%m-%d %H:%M:%S'),
                    'prerelease': version.is_prerelease,
                    'yanked': vers_data['yanked'],
                    'skip_reason': vers_data['skip'],
                    'files': {
                        filename: {
                            'filehash': file_data['hash'],
                            'filesize': file_data['size'],
                            'builder_abi': file_data['abi_builder'],
                            'file_abi_tag': file_data['abi_file'],
                            'platform': file_data['platform'],
                            'requires_python': file_data['requires_python'],
                            'apt_dependencies': sorted(file_data['apt_dependencies']),
                        }
                        for filename, file_data in vers_data['files'].items()
                    },
                }
                for version, vers_data in data['releases'].items()
            },
        }

        pkg_dir = self.output_path / 'project' / package / 'json'
        mkdir_override_symlink(pkg_dir)
        with AtomicReplaceFile(pkg_dir / 'index.json', encoding='utf-8') as index:
            json.dump(project_data, index)

    def write_log(self, build_id, log):
        """
        Attempts to write the *log* of build *build_id* to the log output
        directories, splitting the numeric build id into three parts to flatten
        the output hierarchy. Log data is also gzip compressed.
        """
        self.logger.info('writing log for build %d', build_id)

        levels = []
        n = build_id
        for i in range(3):
            n, m = divmod(n, 10000)
            levels.append(m)
        levels = ['{:04d}'.format(level) for level in reversed(levels)]

        log_dir = self.output_path / 'logs' / levels[0] / levels[1]
        log_dir.mkdir(parents=True, exist_ok=True)
        # No need for AtomicReplaceFile here. The log we're writing should
        # *never* exist. In fact, it should be an error if it does hence the
        # use of the "x" mode
        with (log_dir / (levels[2] + '.txt.gz')).open('xb') as f:
            with gzip.open(f, 'wt', encoding='utf-8', errors='replace') as arc:
                arc.write(log)

    def delete_package(self, package):
        """
        Attempts to remove the index and project page directories (including all
        known wheel files) of the specified *package*.

        :param str package:
            The name of the package to delete.
        """
        self.logger.info('deleting package %s', package)
        if len(package) == 0:
            # refuse to delete /simple/ and /project/ by accident
            raise RuntimeError('Attempted to delete everything')

        # remove any symlinks for project aliases
        for project_alias in self.db.get_package_aliases(package):
            project_symlink = self.output_path / 'project' / project_alias
            try:
                project_symlink.unlink()
            except FileNotFoundError:
                self.logger.error('symlink not found: %s', project_symlink)

        pkg_dir = self.output_path / 'simple' / package
        proj_dir = self.output_path / 'project' / package
        proj_json_dir = proj_dir / 'json'

        files = {pkg_dir / f for f in self.db.get_package_files(package)}
        files |= {
            pkg_dir / 'index.html',
            proj_dir / 'index.html',
            proj_json_dir / 'index.json',
        }

        # try to delete every known wheel file, the HTML files and JSON file
        for file_path in files:
            try:
                file_path.unlink()
                self.logger.debug('file deleted: %s', file_path)
            except FileNotFoundError:
                self.logger.error('file not found: %s', file_path)

        for dir_path in (pkg_dir, proj_json_dir, proj_dir):
            try:
                dir_path.rmdir()
            except OSError as e:
                self.logger.error('failed to remove directory %s: %s',
                                  dir_path, repr(e))

    def delete_version(self, package, version):
        """
        Attempts to remove any known wheel files corresponding with deleted
        *versions* of the specified *package*.

        :param str package:
            The name of the package to delete files for.

        :param str version:
            The version of *package* to delete files for.
        """
        self.logger.info('deleting package %s version %s', package, version)
        pkg_dir = self.output_path / 'simple' / package
        for file in self.db.get_version_files(package, version):
            file_path = pkg_dir / file
            try:
                file_path.unlink()
                self.logger.info('File deleted: %s', file)
            except FileNotFoundError:
                self.logger.error('File not found: %s', file)


# https://docs.python.org/3/library/itertools.html
def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


def parse_version(s):
    v = pkg_resources.parse_version(s)
    # Keep a reference to the original string as otherwise it's unrecoverable;
    # e.g. 0.1a parses to 0.1a0. As this is different, keyed lookups with the
    # parsed variant will fail
    v.original = s
    return v


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
