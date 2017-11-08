"Defines the :class:`CloudGazer` task; see class for more details"

from .tasks import PauseableTask
from .pypi import PyPI
from .the_oracle import DbClient


class CloudGazer(PauseableTask):
    """
    This task scrapes PyPI for the list of available packages, and the versions
    of those packages. This information is written into the backend database
    for :class:`QueueStuffer` to use.
    """
    name = 'master.cloud_gazer'

    def __init__(self, config):
        super().__init__(config)
        self.pypi = PyPI(config['pypi_root'])
        self.db = DbClient(config)
        self.packages = set()

    def loop(self):
        for package, version in self.pypi:
            if version is None:
                if package not in self.packages:
                    if self.db.add_new_package(package):
                        self.packages.add(package)
                        self.logger.info('added package %s', package)
            else:
                if self.db.add_new_package_version(package, version):
                    self.logger.info('added package %s version %s',
                                     package, version)
            self.poll(0)
        self.db.set_pypi_serial(self.pypi.last_serial)

    def run(self):
        self.logger.info('retrieving current state')
        self.pypi.last_serial = self.db.get_pypi_serial()
        self.packages = set(self.db.get_all_packages())
        self.logger.info('querying upstream')
        super().run()
