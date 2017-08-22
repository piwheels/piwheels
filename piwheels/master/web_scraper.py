from .tasks import PausableTask, DatabaseMixin, PyPIMixin, TaskQuit


class WebScraper(PausableTask, DatabaseMixin, PyPIMixin):
    """
    This task scrapes PyPI for the list of available packages, and the versions
    of those packages. This information is written into the backend database for
    :class:`QueueStuffer` to use.
    """
    def run(self):
        try:
            while True:
                self.db.update_package_list(self.pypi.get_all_packages())
                for package in self.db.get_all_packages():
                    self.handle_control()
                    db.update_package_version_list(
                        package, self.pypi.get_package_versions(package))
                self.handle_control(60000)
        except TaskQuit:
            pass

