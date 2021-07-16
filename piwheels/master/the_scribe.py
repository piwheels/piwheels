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

import io
import os
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from itertools import zip_longest
from operator import attrgetter
from collections import namedtuple

import pkg_resources
from chameleon import PageTemplateLoader
import simplejson as json

from .. import const, protocols, tasks, transport
from ..format import format_size, canonicalize_name
from ..states import mkdir_override_symlink, MasterStats
from .the_oracle import DbClient

UTC = timezone.utc


ProjectRelease = namedtuple('ProjectRelease', (
    'version', 'yanked', 'released', 'skip', 'abis', 'files',
    'builds_succeeded', 'builds_failed'))

def _is_compatible_with_abi(abi, builds_succeeded, files):
    return abi in builds_succeeded or any(
        f['file_abi_tag'] == 'none' and abi >= f['builder_abi']
        for f in files
    )

def _get_abi_status(abi, builds_succeeded, builds_failed, files, skip):
    status = {
        'css_class': '',
        'title': '',
    }
    if abi in builds_failed:
        status['css_class'] = 'buildfailed'
        status['title'] = 'Build failed'
    elif _is_compatible_with_abi(abi, builds_succeeded, files):
        status['css_class'] = 'buildpassed'
        status['title'] = 'Build succeeded'
    elif skip:
        status['css_class'] = 'buildskipped'
        status['title'] = 'Skipped: {}'.format(skip)
    return status


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
            elif msg == 'DELVER':
                package, version = data
                self.delete_version(package, version)
                pages = ('index', 'project')
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
            only write the project page. Note project page also includes project
            JSON.

        :type exclude: set or None
        :param exclude:
            The set of (deleted) versions to exclude from pages. Defaults to
            ``None``.
        """
        if exclude is None:
            exclude = set()
        files = self.get_files(package, exclude)
        if both:
            self.write_package_index(package, files)
        versions = self.get_versions(package, exclude)
        releases = self.get_releases(versions, files)
        description = self.db.get_package_description(package)
        self.write_project_page(package, releases, description)
        self.write_project_json(package, releases, description)

    def write_package_index(self, package, files):
        """
        (Re)writes the index of the specified package. The file meta-data
        (including the hash) is retrieved from the database, *never* from the
        file-system.

        :param str package:
            The name of the package to write the index for

        :param str files:
            The list of files to include in the index
        """
        self.logger.info('writing index for %s', package)
        pkg_dir = self.output_path / 'simple' / package
        mkdir_override_symlink(pkg_dir)
        with AtomicReplaceFile(pkg_dir / 'index.html',
                               encoding='utf-8') as index:
            index.file.write(self.templates['simple_package'](
                package=package,
                files=files
            ))
        if package not in self.package_cache:
            self.package_cache.add(package)
            self.write_simple_index()

    def write_project_page(self, package, releases, description):
        """
        (Re)writes the project page of the specified package.

        :param str package:
            The name of the package to write the project page for

        :param str releases:
            The list of releases to include in the project page

        :param str description:
            The project summary text
        """
        self.logger.info('writing project page for %s', package)
        num_files = sum(len(release.files) for release in releases)
        release_files = [
            release.files
            for release in releases
            if not (release.version.is_prerelease or release.yanked)
        ]
        try:
            dependencies = release_files[0][0]['apt_dependencies']
        except IndexError:
            dependencies = set()
        project_name = self.db.get_project_display_name(package)
        project_dir = self.output_path / 'project' / package
        mkdir_override_symlink(project_dir)
        dt = datetime.now(tz=UTC)
        with AtomicReplaceFile(project_dir / 'index.html', encoding='utf-8') as index:
            index.file.write(self.templates['project'](
                layout=self.templates['layout']['layout'],
                package=package,
                project=project_name,
                releases=releases,
                num_files=num_files,
                dependencies=dependencies,
                format_size=format_size,
                timestamp=dt.strftime('%Y-%m-%d %H:%M %Z'),
                title=project_name,
                description=description,
                page='project'))
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

    def write_project_json(self, package, releases, description):
        """
        (Re)writes the project JSON file of the specified package.

        :param str package:
            The name of the package to write the project page for

        :param str releases:
            The list of releases to include in the project page

        :param str description:
            The project summary text
        """
        self.logger.info('writing project json for %s', package)
        releases_dict = {
            release.version.original: {
                'released': release.released.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'prerelease': release.version.is_prerelease,
                'yanked': release.yanked,
                'skip_reason': release.skip,
                'files': {
                    file['filename']: {
                        k: v
                        for k, v in file.items()
                        if k != 'filename'
                    }
                    for file in release.files
                }
            }
            for release in releases
        }
        project_data = {
            'package': package,
            'summary': description,
            'pypi_url': 'https://pypi.org/project/{}'.format(package),
            'piwheels_url': 'https://www.piwheels.org/project/{}'.format(package),
            'releases': releases_dict,
        }
        pkg_dir = self.output_path / 'project' / package / 'json'
        mkdir_override_symlink(pkg_dir)
        with AtomicReplaceFile(pkg_dir / 'index.json', encoding='utf-8') as index:
            json.dump(project_data, index)

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

    def get_versions(self, package, exclude):
        """
        Retrieves a sorted list of versions and associated data for *package*
        excluding any versions in *exclude*.

        :param str package:
            The name of the package to get versions for.

        :type exclude: set or None
        :param exclude:
            Set of versions to exclude from results.
        """
        versions = [
            row._replace(version=parse_version(row.version))
            for row in self.db.get_project_versions(package)
            if row.version not in exclude
        ]
        return sorted(versions, key=attrgetter('version'), reverse=True)

    def get_files(self, package, exclude):
        """
        Retrieves a list of files and associated data for *package* excluding
        any files from versions in *exclude*.

        :param str package:
            The name of the package to get versions for.

        :type exclude: set or None
        :param exclude:
            Set of versions to exclude from results.
        """
        return [
            row._replace(version=parse_version(row.version))
            for row in self.db.get_project_files(package)
            if row.version not in exclude
        ]

    def get_releases(self, versions, files):
        """
        Combines the given *files* and *versions* for a project into a list of
        releases containing all the release information required to write out
        the project page and project JSON file for the given package. Returns
        the list of releases.

        :param list versions:
            The name of the package to get versions for.

        :param list files:
            Set of versions to exclude from results.
        """
        releases = []
        for version in versions:
            version_files = [
                {
                    'filename': f.filename,
                    'filehash': f.filehash,
                    'filesize': f.filesize,
                    'builder_abi': f.builder_abi,
                    'file_abi_tag': f.file_abi_tag,
                    'platform': f.platform_tag,
                    'requires_python': f.requires_python,
                    'apt_dependencies': sorted(f.dependencies) if f.dependencies else [],
                }
                for f in files
                if f.version.original == version.version.original
            ]
            builds_succeeded = [abi for abi in version.builds_succeeded.split(',') if abi]
            builds_failed = [abi for abi in version.builds_failed.split(',') if abi]
            abis = {
                abi: _get_abi_status(
                    abi, builds_succeeded, builds_failed, version_files,
                    version.skip)
                for abi in self.db.get_build_abis(exclude_skipped=True)
            }
            release = ProjectRelease(
                version=version.version,
                yanked=version.yanked,
                released=version.released,
                skip=version.skip,
                abis=abis,
                files=version_files,
                builds_succeeded=builds_succeeded,
                builds_failed=builds_failed,
            )
            releases.append(release)
        return releases


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
