import os
import tempfile
import logging
from pathlib import Path
from datetime import timedelta

import zmq
from pkg_resources import resource_string, resource_stream

from .html import tag
from .tasks import PauseableTask, TaskQuit
from .the_oracle import DbClient


logger = logging.getLogger('master.index_scribe')


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
    def __init__(self, **config):
        super().__init__(**config)
        self.homepage_template = resource_string(__name__, 'index.template.html').decode('utf-8')
        self.output_path = Path(config['output_path'])
        self.index_queue = self.ctx.socket(zmq.PULL)
        self.index_queue.hwm = 10
        self.index_queue.bind(config['index_queue'])
        self.db = DbClient(**config)
        self.setup_output_path()

    def setup_output_path(self):
        logger.info('setting up output path')
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
        self.index_queue.close()
        logger.info('closed')

    def run(self):
        logger.info('starting')
        poller = zmq.Poller()
        try:
            # Build the initial index from the set of directories that exist
            # under the output path (this is much faster than querying the
            # database for the same info)
            packages = {
                str(d.relative_to(self.output_path / 'simple'))
                for d in (self.output_path / 'simple').iterdir()
                if d.is_dir()
            }

            poller.register(self.control_queue, zmq.POLLIN)
            poller.register(self.index_queue, zmq.POLLIN)
            while True:
                socks = dict(poller.poll(1000))
                if self.control_queue in socks:
                    self.handle_control()
                if self.index_queue in socks:
                    package = self.index_queue.recv_string()
                    if package not in packages:
                        packages.add(package)
                        self.write_root_index(packages)
                    self.write_package_index(package, self.db.get_package_files(package))
        except TaskQuit:
            pass

    def write_homepage(self, status_info):
        logger.info('regenerating homepage')
        with tempfile.NamedTemporaryFile(mode='w', dir=str(self.output_path),
                                         delete=False) as index:
            try:
                index.file.write(self.homepage_template.format(
                    packages_built=status_info['packages_built'],
                    versions_built=status_info['versions_built'],
                    builds_time=timedelta(seconds=status_info['builds_time']),
                    builds_size=status_info['builds_size'] // 1048576
                ))
            except:
                index.delete = True
                raise
            else:
                os.fchmod(index.file.fileno(), 0o664)
                os.replace(index.name, str(self.output_path / 'index.html'))

    def write_root_index(self, packages):
        logger.info('regenerating package index')
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
                            for package in packages
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
        logger.info('generating index for %s', package)
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
