from threading import Thread

import zmq

from .db import Database
from .pypi import PyPI


class TaskQuit(Exception):
    """
    Exception raised when the "QUIT" message is received by the internal
    control queue.
    """


class Task(Thread):
    def __init__(self, **config):
        super().__init__()
        self.ctx = zmq.Context.instance()
        self.control_queue = self.ctx.socket(zmq.SUB)
        self.control_queue.connect(config['int_control_queue'])
        self.control_queue.setsockopt_string(zmq.SUBSCRIBE, '')

    def close(self):
        self.join()
        self.control_queue.close()

    def handle_control(self, timeout=0):
        if self.control_queue.poll(timeout):
            msg, *args = self.control_queue.recv_json()
            if msg == 'QUIT':
                raise TaskQuit


class PauseableTask(Task):
    def handle_control(self, timeout=0):
        if self.control_queue.poll(timeout):
            msg, *args = self.control_queue.recv_json()
            if msg == 'QUIT':
                raise TaskQuit
            elif msg == 'PAUSE':
                while True:
                    msg, *args = self.control_queue.recv_json()
                    if msg == 'QUIT':
                        raise TaskQuit
                    elif msg == 'RESUME':
                        break


class DatabaseMixin():
    def __init__(self, **config):
        super().__init__(**config)
        self.db = Database(config['database'])

    def close(self):
        super().close()
        self.db.close()


class PyPIMixin():
    def __init__(self, **config):
        super().__init__(**config)
        self.pypi = PyPI(config['pypi_root'])

    def close(self):
        super().close()
        self.pypi.close()
