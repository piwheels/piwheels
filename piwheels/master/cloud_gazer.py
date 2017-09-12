import zmq

from .tasks import PauseableTask, TaskQuit
from .pypi import PyPI
from .the_oracle import DbClient


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

    def close(self):
        self.db.close()
        self.pypi.close()
        super().close()

    def run(self):
        poller = zmq.Poller()
        try:
            poller.register(self.control_queue, zmq.POLLIN)
            self.pypi.last_serial = self.db.get_pypi_serial()
            while True:
                for package, version in self.pypi:
                    if version is None:
                        self.db.add_new_package(package)
                    else:
                        self.db.add_new_package_version(package, version)
                    if poller.poll():
                        self.handle_control()
                if poller.poll(10000):
                    self.handle_control()
        except TaskQuit:
            pass
        finally:
            self.db.set_pypi_serial(self.pypi.last_serial)
