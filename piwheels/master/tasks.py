import logging
from threading import Thread
from collections import OrderedDict

import zmq


class TaskQuit(Exception):
    """
    Exception raised when the "QUIT" message is received by the internal
    control queue.
    """


class Task(Thread):
    name = 'Task'

    def __init__(self, config):
        super().__init__()
        self.ctx = zmq.Context.instance()
        # Use an ordered dictionary to ensure the control queue is always
        # checked first
        self.handlers = OrderedDict()
        self.poller = zmq.Poller()
        self.logger = logging.getLogger(self.name)
        control_queue = self.ctx.socket(zmq.SUB)
        control_queue.connect(config['int_control_queue'])
        control_queue.setsockopt_string(zmq.SUBSCRIBE, '')
        self.register(control_queue, self.handle_control)

    def register(self, queue, handler, flags=zmq.POLLIN):
        self.poller.register(queue, flags)
        self.handlers[queue] = handler

    def close(self):
        self.logger.info('closing')
        self.join()
        for q in self.handlers:
            q.close(linger=1000)

    def handle_control(self, q):
        msg, *args = q.recv_pyobj()
        if msg == 'QUIT':
            raise TaskQuit

    def loop(self):
        pass

    def poll(self, timeout=1000):
        while True:
            socks = dict(self.poller.poll(timeout))
            try:
                for q in socks:
                    self.handlers[q](q)
            except zmq.error.Again:
                continue
            break

    def run(self):
        self.logger.info('starting')
        while True:
            try:
                self.loop()
                self.poll()
            except TaskQuit:
                break


class PauseableTask(Task):
    def handle_control(self, q):
        msg, *args = q.recv_pyobj()
        if msg == 'QUIT':
            raise TaskQuit
        elif msg == 'PAUSE':
            while True:
                msg, *args = q.recv_pyobj()
                if msg == 'QUIT':
                    raise TaskQuit
                elif msg == 'RESUME':
                    break
