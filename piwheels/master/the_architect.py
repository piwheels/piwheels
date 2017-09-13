import logging

import zmq

from .tasks import PauseableTask, TaskQuit
from .db import Database


logger = logging.getLogger('master.the_architect')


class TheArchitect(PauseableTask):
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
        self.db = Database(config['database'])

    def close(self):
        super().close()
        self.db.close()
        self.build_queue.close()
        logger.info('closed')

    def run(self):
        logger.info('starting')
        poller = zmq.Poller()
        try:
            poller.register(self.control_queue, zmq.POLLIN)
            poller.register(self.build_queue, zmq.POLLOUT)
            while True:
                for package, version in self.db.get_build_queue():
                    while True:
                        socks = dict(poller.poll(1000))
                        if self.control_queue in socks:
                            self.handle_control()
                        if self.build_queue in socks:
                            self.build_queue.send_json((package, version))
                            break
                # Wait a minute between iterations of the build queue
                socks = dict(poller.poll(60000))
                if self.control_queue in socks:
                    self.handle_control()
        except TaskQuit:
            pass

