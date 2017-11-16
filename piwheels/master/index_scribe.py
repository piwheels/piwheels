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
Defines the :class:`IndexScribe` task; see class for more details.

.. autoclass:: IndexScribe
    :members:
"""

import re
import os
import tempfile
from pathlib import Path

import zmq
from pkg_resources import resource_string, resource_stream, resource_listdir

from .html import tag
from .tasks import PauseableTask
from .the_oracle import DbClient
from .states import mkdir_override_symlink


class IndexScribe(PauseableTask):
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
    name = 'master.index_scribe'

    def __init__(self, config):
        super().__init__(config)
        self.homepage_template = resource_string(
            __name__, 'index.template.html').decode('utf-8')
        self.output_path = Path(config.output_path)
        index_queue = self.ctx.socket(zmq.PULL)
        index_queue.hwm = 100
        index_queue.bind(config.index_queue)
        self.register(index_queue, self.handle_index)
        self.db = DbClient(config)
        self.package_cache = set()
        self.setup_output_path()

    def setup_output_path(self):
        """
        Called on task startup to copy all static resources into the output
        path (and to make sure the output path exists as a directory).
        """
        self.logger.info('setting up output path')
        try:
            self.output_path.mkdir()
        except FileExistsError:
            pass
        try:
            (self.output_path / 'simple').mkdir()
        except FileExistsError:
            pass
        for filename in resource_listdir(__name__, 'static'):
            with (self.output_path / filename).open('wb') as f:
                source = resource_stream(__name__, 'static/' + filename)
                f.write(source.read())
                source.close()

    def run(self):
        self.logger.info('building package cache')
        self.package_cache = set(self.db.get_all_packages())
        super().run()

    def handle_index(self, queue):
        """
        Handle incoming requests to (re)build index files. These will be in the
        form of "HOME", a request to write the homepage with some associated
        statistics, or "PKG", a request to write the index for the specified
        package.

        .. note::

            In all handlers below, care is taken to ensure clients never see a
            partially written file and that temporary files are cleaned up in
            the event of any exceptions.
        """
        msg, *args = queue.recv_pyobj()
        if msg == 'PKG':
            package = args[0]
            if package not in self.package_cache:
                self.package_cache.add(package)
                self.write_root_index()
            self.write_package_index(package,
                                     self.db.get_package_files(package))
        elif msg == 'HOME':
            status_info = args[0]
            self.write_homepage(status_info)
        else:
            self.logger.error('invalid index_queue message: %s', msg)

    def write_homepage(self, status_info):
        """
        Re-writes the site homepage using the provided statistics in the
        homepage template (which is effectively a simple Python format string).

        :param tuple status_info:
            A namedtuple containing statistics obtained by :class:`BigBrother`.
        """
        self.logger.info('writing homepage')
        with tempfile.NamedTemporaryFile(mode='w', dir=str(self.output_path),
                                         delete=False) as index:
            try:
                index.file.write(self.homepage_template.format(**status_info))
            except BaseException:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o664)
                os.replace(index.name, str(self.output_path / 'index.html'))

    def write_root_index(self):
        """
        (Re)writes the index of all packages. This is implicitly called when a
        request to write a package index is received for a package not present
        in the task's cache.
        """
        self.logger.info('writing package index')
        temp_dir = self.output_path / 'simple'
        with tempfile.NamedTemporaryFile(mode='w', dir=str(temp_dir),
                                         delete=False) as index:
            try:
                index.file.write('<!DOCTYPE html>\n')
                index.file.write(
                    tag.html(
                        tag.head(
                            tag.title('Pi Wheels Simple Index'),
                            tag.meta(name='api-version', value=2),
                        ),
                        tag.body(
                            (tag.a(package, href=package), tag.br())
                            for package in self.package_cache
                        )
                    )
                )
            except BaseException:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o644)
                os.replace(index.name,
                           str(self.output_path / 'simple' / 'index.html'))

    def write_package_index(self, package, files):
        """
        (Re)writes the index of the specified package. The file meta-data
        (including the hash) is retrieved from the database, *never* from the
        file-system.

        :param str package:
            The name of the package to write the index for

        :param list files:
            A list of (filename, filehash) tuples.
        """
        self.logger.info('writing index for %s', package)
        pkg_dir = self.output_path / 'simple' / package
        mkdir_override_symlink(pkg_dir)
        with tempfile.NamedTemporaryFile(mode='w', dir=str(pkg_dir),
                                         delete=False) as index:
            try:
                index.file.write('<!DOCTYPE html>\n')
                index.file.write(
                    tag.html(
                        tag.head(
                            tag.title('Links for {}'.format(package))
                        ),
                        tag.body(
                            tag.h1('Links for {}'.format(package)),
                            ((tag.a(
                                f.filename,
                                href='{f.filename}#sha256={f.filehash}'.format(f=f),  # noqa: E501
                                rel='internal'), tag.br())
                             for f in files)
                        )
                    )
                )
            except BaseException:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o644)
                os.replace(index.name, str(pkg_dir / 'index.html'))
                try:
                    # Workaround for #20: after constructing the index for a
                    # package attempt to symlink the "canonicalized" package
                    # name to the actual package directory. The reasons for
                    # doing things this way are rather complex...
                    #
                    # The older package name must exist for the benefit of
                    # older versions of pip. If the symlink already exists *or
                    # is a directory* we ignore it. Yes, it's possible to have
                    # two packages which both have the same canonicalized name,
                    # and for each to have different contents. I don't quite
                    # know how PyPI handle this but their XML and JSON APIs
                    # already include such situations (in a small number of
                    # cases). This setup is designed to create canonicalized
                    # links where possible but not to clobber "real" packages
                    # if they exist.
                    #
                    # What about new packages that want to take the place of a
                    # canonicalized symlink? We (and TransferState.commit)
                    # handle that by removing the symlink and making a
                    # directory in its place.
                    canon_dir = pkg_dir.with_name(canonicalize_name(pkg_dir.name))  # noqa: E501
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
