from .tasks import PauseableTask, DatabaseMixin, PyPIMixin, TaskQuit


class CloudGazer(DatabaseMixin, PyPIMixin, PauseableTask):
    """
    This task scrapes PyPI for the list of available packages, and the versions
    of those packages. This information is written into the backend database for
    :class:`QueueStuffer` to use.
    """
    def run(self):
        try:
            self.pypi.last_serial = self.db.get_pypi_serial()
            while True:
                for package, version in self.pypi:
                    self.handle_control()
                    if version is None:
                        self.db.add_new_package(package)
                    else:
                        self.db.add_new_package_version(package, version)
                self.handle_control(10000)
        except TaskQuit:
            pass
        finally:
            self.db.set_pypi_serial(self.pypi.last_serial)

