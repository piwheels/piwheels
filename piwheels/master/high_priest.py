import logging
from threading import Thread

import zmq

from .tasks import TaskQuit


class HighPriest(Thread):  # NOTE: not a Task descendant
    """
    The high priest is responsible for reporting the state of the system, and
    all associated slaves to whoever or whatever might be listening to the
    external status queue. It is also responsible for receiving orders from the
    external control queue and relaying those orders to the internal control
    queue.
    """
    name = 'master.high_priest'

    def __init__(self, config):
        super().__init__()
        self.ctx = zmq.Context.instance()
        self.logger = logging.getLogger(self.name)
        self.int_control_queue = self.ctx.socket(zmq.PUB)
        self.int_control_queue.hwm = 10
        self.int_control_queue.bind(config['int_control_queue'])
        self.ext_control_queue = self.ctx.socket(zmq.PULL)
        self.ext_control_queue.hwm = 10
        self.ext_control_queue.bind(config['ext_control_queue'])
        self.int_status_queue = self.ctx.socket(zmq.PULL)
        self.int_status_queue.hwm = 10
        self.int_status_queue.bind(config['int_status_queue'])
        self.ext_status_queue = self.ctx.socket(zmq.PUB)
        self.ext_status_queue.hwm = 10
        self.ext_status_queue.bind(config['ext_status_queue'])

    def close(self):
        self.join()
        self.logger.info('closed')

    def run(self):
        self.logger.info('starting')
        poller = zmq.Poller()
        try:
            poller.register(self.ext_control_queue, zmq.POLLIN)
            poller.register(self.int_status_queue, zmq.POLLIN)
            while True:
                socks = dict(poller.poll())
                if self.int_status_queue in socks:
                    self.ext_status_queue.send(self.int_status_queue.recv())
                if self.ext_control_queue in socks:
                    msg, *args = self.ext_control_queue.recv_pyobj()
                    if msg == 'QUIT':
                        self.logger.warning('shutting down on QUIT message')
                        raise TaskQuit
                    elif msg == 'KILL':
                        self.logger.warning('killing slave %d', args[0])
                    elif msg == 'PAUSE':
                        self.logger.warning('pausing operations')
                    elif msg == 'RESUME':
                        self.logger.warning('resuming operations')
                    self.int_control_queue.send_pyobj([msg] + args)
        except TaskQuit:
            pass
        finally:
            self.int_control_queue.send_pyobj(['QUIT'])
