"Defines the :class:`Seraph` task; see class for more details"

import zmq
import zmq.error

from .tasks import Task


class Seraph(Task):
    """
    This task is a simple load-sharing router for :class:`TheOracle` tasks.
    """
    name = 'master.seraph'

    def __init__(self, config):
        super().__init__(config)
        self.front_queue = self.ctx.socket(zmq.ROUTER)
        self.front_queue.hwm = 10
        self.front_queue.bind(config['db_queue'])
        self.back_queue = self.ctx.socket(zmq.ROUTER)
        self.back_queue.hwm = 10
        self.back_queue.bind(config['oracle_queue'])
        self.workers = []
        self.register(self.front_queue, self.handle_front)
        self.register(self.back_queue, self.handle_back)

    def handle_front(self, queue):
        """
        If any workers are currently available, receive :class:`DbClient`
        requests from the front queue and send it on to the worker including
        the client's address frame.
        """
        if self.workers:
            client, _, request = queue.recv_multipart()
            worker = self.workers.pop(0)
            self.back_queue.send_multipart([worker, _, client, _, request])

    def handle_back(self, queue):
        """
        Receive a response from an instance of :class:`TheOracle` on the back
        queue. Strip off the worker's address frame and add it back to the
        available queue then send the response back to the client that made the
        original request.
        """
        worker, _, *msg = queue.recv_multipart()
        self.workers.append(worker)
        if msg != [b'READY']:
            self.front_queue.send_multipart(msg)
