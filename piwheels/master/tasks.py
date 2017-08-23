from threading import Thread

import zmq


class TaskQuit(Exception):
    """
    Exception raised when the "QUIT" message is received by the internal
    control queue.
    """


class Task(Thread):
    def __init__(self, **config):
        super().__init__()
        self.ctx = zmq.Context.instance()
        self.control_queue = ctx.socket(zmq.SUB)
        self.control_queue.connect(config['int_control_queue'])
        self.control_queue.setsockopt_string(zmq.SUBSCRIBE, '')
        self.start()

    def close(self):
        self.join()
        self.control_queue.close()

    def handle_control(self, timeout=0):
        if self.control_queue.poll(timeout):
            msg = self.control_queue.recv_string()
            if msg == 'QUIT':
                raise TaskQuit


class PausableTask(Task):
    def handle_control(self, timeout=0):
        if self.control_queue.poll(timeout):
            msg = self.control_queue.recv_string()
            if msg == 'QUIT':
                raise TaskQuit
            elif msg == 'PAUSE':
                while True:
                    msg = self.control_queue.recv_string()
                    if msg == 'QUIT':
                        raise TaskQuit
                    elif msg == 'RESUME':
                        break


class DatabaseMixin():
    def __init__(self, **config):
        super().__init__(**config)
        self.db = Database(config['database'])

    def close(self):
        self.db.close()
        super().close()


class PyPIMixin():
    def __init__(self, **config):
        super().__init__(**config)
        self.pypi = PyPI(config['pypi_root'])

    def close(self):
        self.pypi.close()
        super().close()

