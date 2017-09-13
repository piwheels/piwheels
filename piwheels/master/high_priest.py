import logging
from threading import Thread

import zmq

from .tasks import TaskQuit


logger = logging.getLogger('master.high_priest')


class HighPriest(Thread):  # NOTE: not a Task descendant
    """
    The high priest is responsible for reporting the state of the system, and
    all associated slaves to whoever or whatever might be listening to the
    external status queue. It is also responsible for receiving orders from the
    external control queue and relaying those orders to the internal control
    queue.
    """
    def __init__(self, **config):
        super().__init__()
        self.ctx = zmq.Context.instance()
        self.int_control_queue = self.ctx.socket(zmq.PUB)
        self.int_control_queue.hwm = 1
        self.int_control_queue.bind(config['int_control_queue'])
        self.ext_control_queue = self.ctx.socket(zmq.PULL)
        self.ext_control_queue.hwm = 1
        self.ext_control_queue.bind(config['ext_control_queue'])
        self.int_status_queue = self.ctx.socket(zmq.PULL)
        self.int_status_queue.hwm = 10
        self.int_status_queue.bind(config['int_status_queue'])
        self.ext_status_queue = self.ctx.socket(zmq.PUB)
        self.ext_status_queue.hwm = 10
        self.ext_status_queue.bind(config['ext_status_queue'])

    def close(self):
        self.join()
        self.ext_status_queue.close()
        self.ext_control_queue.close()
        self.int_status_queue.close()
        self.int_control_queue.close()
        logger.info('closed')

    def run(self):
        logger.info('starting')
        poller = zmq.Poller()
        try:
            poller.register(self.ext_control_queue, zmq.POLLIN)
            poller.register(self.int_status_queue, zmq.POLLIN)
            while True:
                socks = dict(poller.poll())
                if self.int_status_queue in socks:
                    self.ext_status_queue.send(self.int_status_queue.recv())
                if self.ext_control_queue in socks:
                    msg, *args = self.ext_control_queue.recv_json()
                    if msg == 'QUIT':
                        logger.warning('shutting down on QUIT message')
                        raise TaskQuit
                    elif msg == 'KILL':
                        logger.warning('killing slave %d', args[0])
                    elif msg == 'PAUSE':
                        logger.warning('pausing operations')
                    elif msg == 'RESUME':
                        logger.warning('resuming operations')
                    self.int_control_queue.send_json([msg] + args)
        except TaskQuit:
            pass
        finally:
            self.int_control_queue.send_json(['QUIT'])
