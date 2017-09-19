import os
import tempfile
from pathlib import Path

import zmq
from pkg_resources import resource_string, resource_stream

from .html import tag
from .tasks import PauseableTask
from .the_oracle import DbClient


class IndexScribe(PauseableTask):
    """
    This task is responsible for writing web-page ``index.html`` files. It reads
    the names of packages off the internal "indexes" queue and rebuilds the
    ``index.html`` for that package and, optionally, the overall ``index.html``
    if the package is one that wasn't previously present.

    .. note::

        It is important to note that package names are never pushed into the
        internal "indexes" queue until all file-transfers associated with the
        build are complete. Furthermore, while the entire index for a package is
        re-built, hashes are *never* re-calculated from the disk files (they are
        always read from the database).
    """
    name = 'master.index_scribe'

    def __init__(self, **config):
        super().__init__(**config)
        self.homepage_template = resource_string(__name__, 'index.template.html').decode('utf-8')
        self.output_path = Path(config['output_path'])
        index_queue = self.ctx.socket(zmq.PULL)
        index_queue.hwm = 10
        index_queue.bind(config['index_queue'])
        self.register(index_queue, self.handle_index)
        self.db = DbClient(**config)
        self.package_cache = set()
        self.setup_output_path()

    def setup_output_path(self):
        self.logger.info('setting up output path')
        try:
            self.output_path.mkdir()
        except FileExistsError:
            pass
        try:
            (self.output_path / 'simple').mkdir()
        except FileExistsError:
            pass
        for filename in ('raspberry-pi-logo.svg', 'python-logo.svg'):
            with (self.output_path / filename).open('wb') as f:
                source = resource_stream(__name__, filename)
                f.write(source.read())
                source.close()

    def close(self):
        super().close()
        self.db.close()

    def run(self):
        # Build the initial index from the set of directories that exist
        # under the output path (this is much faster than querying the
        # database for the same info)
        self.logger.info('building package cache')
        self.package_cache = {
            str(d.relative_to(self.output_path / 'simple'))
            for d in (self.output_path / 'simple').iterdir()
            if d.is_dir()
        }
        super().run()

    def handle_index(self, q):
        msg, *args = q.recv_pyobj()
        if msg == 'PKG':
            package = args[0]
            if package not in self.package_cache:
                self.package_cache.add(package)
                self.write_root_index()
            self.write_package_index(package, self.db.get_package_files(package))
        elif msg == 'HOME':
            status_info = args[0]
            self.write_homepage(status_info)
        else:
            self.logger.error('invalid index_queue message: %s', msg)

    def write_homepage(self, status_info):
        self.logger.info('writing homepage')
        with tempfile.NamedTemporaryFile(mode='w', dir=str(self.output_path),
                                         delete=False) as index:
            try:
                index.file.write(self.homepage_template.format(
                    packages_built=status_info['packages_built'],
                    versions_built=status_info['versions_built'],
                    builds_time=status_info['builds_time'],
                    builds_size=status_info['builds_size'] // 1048576
                ))
            except:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o664)
                os.replace(index.name, str(self.output_path / 'index.html'))

    def write_root_index(self):
        self.logger.info('writing package index')
        with tempfile.NamedTemporaryFile(
                mode='w', dir=str(self.output_path / 'simple'),
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
            except:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o644)
                os.replace(index.name, str(self.output_path / 'simple' / 'index.html'))

    def write_package_index(self, package, files):
        self.logger.info('writing index for %s', package)
        with tempfile.NamedTemporaryFile(
                mode='w', dir=str(self.output_path / 'simple' / package),
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
                            (
                                (tag.a(rec.filename,
                                       href='{rec.filename}#sha256={rec.filehash}'.format(rec=rec),
                                       rel='internal'), tag.br())
                                for rec in files
                            )
                        )
                    )
                )
            except:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o644)
                os.replace(index.name, str(self.output_path / 'simple' / package / 'index.html'))
