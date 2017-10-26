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
        self.abi_queries = {}
        self.register(build_queue, self.handle_build)

    def handle_build(self, q):
        abi = q.recv_pyobj()
        try:
            query = self.abi_queries[abi]
        except KeyError:
            query = self.db.get_build_queue(abi)
            self.abi_queries[abi] = query
        try:
            q.send_pyobj(next(query))
        except StopIteration:
            # Return None to indicate there's nothing *currently* in the queue
            # for this abi, but set up a new query for next time
            q.send_pyobj(None)
            self.abi_queries[abi] = self.db.get_build_queue(abi)
