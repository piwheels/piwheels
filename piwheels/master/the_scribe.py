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
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

import pkg_resources
from chameleon import PageTemplateLoader

from .. import const, protocols, tasks, transport
from ..format import format_size
from .html import tag
from .the_oracle import DbClient
from .states import mkdir_override_symlink


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
        scribe_queue = self.ctx.socket(
            transport.PULL, protocol=protocols.the_scribe)
        scribe_queue.hwm = 100
        scribe_queue.bind(const.SCRIBE_QUEUE)
        self.register(scribe_queue, self.handle_index)
        self.db = DbClient(config)
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
            self.write_root_index()

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
        startup_templates = {'faq.pt', 'packages.pt', 'stats.pt'}
        for filename in pkg_resources.resource_listdir(__name__, 'templates'):
            if filename in startup_templates:
                source = self.templates[filename](
                        layout=self.templates['layout']['layout'],
                        page=filename.replace('.html', '')
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
                    self.write_root_index()
                self.write_package_index(package)
                self.write_project_page(package)
            elif msg == 'PKGPROJ':
                package = data
                self.write_project_page(package)
            elif msg == 'HOME':
                status_info = data
                self.write_homepage(status_info)
            elif msg == 'SEARCH':
                search_index = data
                self.write_search_index(search_index)

    def write_homepage(self, statistics):
        """
        Re-writes the site homepage using the provided statistics in the
        homepage template (which is effectively a simple Python format string).

        :param dict statistics:
            A dict containing statistics obtained by :class:`BigBrother`.
        """
        self.logger.info('writing homepage')
        dt = datetime.now()
        with AtomicReplaceFile(self.output_path / 'index.html',
                               encoding='utf-8') as index:
            index.file.write(self.templates['index'](
                layout=self.templates['layout']['layout'],
                timestamp=dt.strftime('%Y-%m-%d %H:%M'),
                page='home',
                **statistics))

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

    def write_root_index(self):
        """
        (Re)writes the index of all packages. This is implicitly called when a
        request to write a package index is received for a package not present
        in the task's cache.
        """
        self.logger.info('writing package index')
        with AtomicReplaceFile(self.output_path / 'simple' / 'index.html',
                               encoding='utf-8') as index:
            index.file.write('<!DOCTYPE html>\n')
            index.file.write(
                tag.html(
                    tag.head(
                        tag.title('piwheels Simple Index'),
                        tag.meta(name='api-version', value=2),
                    ),
                    tag.body(
                        (tag.a(package, href=package), tag.br())
                        for package in self.package_cache
                    )
                )
            )

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
        with AtomicReplaceFile(pkg_dir / 'index.html',
                               encoding='utf-8') as index:
            index.file.write('<!DOCTYPE html>\n')
            index.file.write(
                tag.html(
                    tag.head(
                        tag.title('Links for ', package)
                    ),
                    tag.body(
                        tag.h1('Links for ', package),
                        ((tag.a(
                            filename,
                            href='{filename}#sha256={filehash}'.format(
                                filename=filename, filehash=filehash),
                            rel='internal'), tag.br(), '\n')
                         for filename, filehash
                         in self.db.get_package_files(package).items())
                    )
                )
            )
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
        versions = sorted(
            self.db.get_project_versions(package),
            key=lambda row: pkg_resources.parse_version(row.version),
            reverse=True)
        files = sorted(
            self.db.get_project_files(package),
            key=lambda row: (
                pkg_resources.parse_version(row.version),
                row.filename
            ), reverse=True)
        if files:
            dependencies = self.db.get_file_dependencies(files[0].filename)
            if 'apt' in dependencies:
                dependencies['apt'] = dependencies['apt'] - self.default_libs
        else:
            dependencies = {}
        self.logger.info('writing project page for %s', package)
        pkg_dir = self.output_path / 'project' / package
        mkdir_override_symlink(pkg_dir)
        dt = datetime.now()
        with AtomicReplaceFile(pkg_dir / 'index.html', encoding='utf-8') as index:
            index.file.write(self.templates['project'](
                layout=self.templates['layout']['layout'],
                package=package,
                versions=versions,
                files=files,
                dependencies=dependencies,
                format_size=format_size,
                timestamp=dt.strftime('%Y-%m-%d %H:%M'),
                url=lambda filename, filehash:
                    '/simple/{package}/{filename}#sha256={filehash}'.format(
                        package=package, filename=filename, filehash=filehash),
                page='project'))
        try:
            # See write_package_index for explanation...
            canon_dir = pkg_dir.with_name(canonicalize_name(pkg_dir.name))
            canon_dir.symlink_to(pkg_dir.name)
        except FileExistsError:
            pass


# From pip/_vendor/packaging/utils.py
# pylint: disable=invalid-name
_canonicalize_regex = re.compile(r"[-_.]+")


def canonicalize_name(name):
    # pylint: disable=missing-docstring
    # This is taken from PEP 503.
    return _canonicalize_regex.sub("-", name).lower()


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
