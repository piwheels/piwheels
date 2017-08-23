import os
import tempfile
from pathlib import Path

import zmq

from .html import tag
from .tasks import PausableTask, DatabaseMixin, TaskQuit


class IndexScribe(PausableTask, DatabaseMixin):
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
        self.output_path = Path(config['output_path'])
        self.index_queue = self.ctx.socket(zmq.PULL)
        self.index_queue.hwm = 10
        self.index_queue.connect(config['index_queue'])

    def close(self):
        self.index_queue.close()
        super().close()

    def run(self):
        try:
            # Build the initial index from the set of directories that exist
            # under the output path (this is much faster than querying the
            # database for the same info)
            packages = {
                str(d.relative_to(self.output_path / 'simple'))
                for d in (self.output_path / 'simple').iterdir()
                if d.is_dir()
            }

            while True:
                self.handle_control()
                if not self.index_queue.poll(1000):
                    continue
                package = self.index_queue.recv_string()
                if package not in packages:
                    packages.add(package)
                    self.write_root_index(packages)
                self.write_package_index(package, self.db.get_package_files(package))
        except TaskQuit:
            pass

    def write_root_index(self, packages):
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
