import zmq

from .tasks import PauseableTask, DatabaseMixin, TaskQuit


class TheArchitect(DatabaseMixin, PauseableTask):
    """
    This task queries the backend database to determine which versions of
    packages have yet to be built (and aren't marked to be skipped). It places a
    tuple of (package, version) for each such build into the internal "builds"
    queue for :class:`SlaveDriver` to read.
    """
    def __init__(self, **config):
        super().__init__(**config)
        self.build_queue = self.ctx.socket(zmq.PUSH)
        self.build_queue.hwm = 1
        self.build_queue.bind(config['build_queue'])

    def close(self):
        self.build_queue.close()
        super().close()

    def run(self):
        try:
            while True:
                for package, version in self.db.get_build_queue():
                    while True:
                        self.handle_control()
                        if self.build_queue.poll(1000, zmq.POLLOUT):
                            self.build_queue.send_json((package, version))
                            break
                self.handle_control(60000)
        except TaskQuit:
            pass

