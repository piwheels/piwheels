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

    def handle_front(self, q):
        if self.workers:
            client, empty, request = q.recv_multipart()
            worker = self.workers.pop(0)
            self.back_queue.send_multipart([worker, empty, client, empty, request])

    def handle_back(self, q):
        worker, empty, *msg = q.recv_multipart()
        self.workers.append(worker)
        if msg != [b'READY']:
            self.front_queue.send_multipart(msg)
