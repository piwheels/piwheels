import logging

import zmq
import zmq.error

from .tasks import PauseableTask, TaskQuit
from .pypi import PyPI
from .the_oracle import DbClient


logger = logging.getLogger('master.cloud_gazer')


class CloudGazer(PauseableTask):
    """
    This task scrapes PyPI for the list of available packages, and the versions
    of those packages. This information is written into the backend database for
    :class:`QueueStuffer` to use.
    """
    def __init__(self, **config):
        super().__init__(**config)
        self.pypi = PyPI(config['pypi_root'])
        self.db = DbClient(**config)
        self.packages = set()
        self.versions = set()

    def close(self):
        super().close()
        self.db.close()
        self.pypi.close()
        logger.info('closed')

    def run(self):
        logger.info('starting')
        poller = zmq.Poller()
        try:
            poller.register(self.control_queue, zmq.POLLIN)
            self.pypi.last_serial = self.db.get_pypi_serial()
            packages = set(self.db.get_all_packages())
            versions = set(self.db.get_all_package_versions())
            while True:
                for package, version in self.pypi:
                    if version is None:
                        if package not in packages:
                            self.db.add_new_package(package)
                            packages.add(package)
                    else:
                        if (package, version) not in versions:
                            self.db.add_new_package_version(package, version)
                            versions.add((package, version))
                    if poller.poll(0):
                        self.handle_control()
                self.db.set_pypi_serial(self.pypi.last_serial)
                if poller.poll(10000):
                    self.handle_control()
        except zmq.error.Again:
            try:
                self.handle_control()
            except TaskQuit:
                pass
            else:
                raise
        except TaskQuit:
            pass
