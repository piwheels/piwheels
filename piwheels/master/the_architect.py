import zmq

from .tasks import Task
from .db import Database


class TheArchitect(Task):
    """
    This task queries the backend database to determine which versions of
    packages have yet to be built (and aren't marked to be skipped). It places a
    tuple of (package, version) for each such build into the internal "builds"
    queue for :class:`SlaveDriver` to read.
    """
    name = 'master.the_architect'

    def __init__(self, config):
        super().__init__(config)
        self.db = Database(config['database'])
        build_queue = self.ctx.socket(zmq.REP)
        build_queue.hwm = 1
        build_queue.bind(config['build_queue'])
        self.abi_queues = {}
        self.register(build_queue, self.handle_build)

    def close(self):
        super().close()
        self.db.close()

    def handle_build(self, q):
        abi = q.recv_pyobj()
        try:
            q.send_pyobj(self.abi_queues[abi].pop())
        except (KeyError, IndexError):
            # If the queue is exhausted or doesn't exist yet, send back None
            # immediately (to indicate there's nothing to do *this time round*)
            # then (re-)build the queue for the specified ABI
            q.send_pyobj(None)
            self.abi_queues[abi] = self.db.get_build_queue(abi)
