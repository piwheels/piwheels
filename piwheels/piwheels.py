import pip
import os
import xmlrpc.client as xmlrpclib
import logging
from time import time

from db import PiWheelsDatabase
from auth import dbname, user, host, password

db = PiWheelsDatabase(dbname, user, host, password)

client = xmlrpclib.ServerProxy('https://pypi.python.org/pypi')
packages = sorted(client.list_packages())

wc = pip.commands.WheelCommand()

wheels_dir = '/var/www/html'


class MyHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        self.log.append(msg)
        if msg.startswith('Saved'):
            file_path = msg.split(' ')[-1]
            self.filename = file_path.split('/')[-1]
            self.filesize = os.stat(file_path).st_size

    def reset(self):
        self.log = []
        self.filename = None
        self.filesize = None


def main():
    handler = MyHandler()
    pip.logger.addHandler(handler)
    build_start_time = time()
    success = 0
    for package in packages:
        handler.reset()
        start_time = time()
        module_dir = '{}/{}'.format(wheels_dir, package)
        if not os.path.exists(module_dir):
            os.makedirs(module_dir)
        wheel_dir = '--wheel-dir={}'.format(module_dir)
        no_deps = '--no-deps'
        status = not wc.main([wheel_dir, no_deps, package])
        success += status

        architecture = 'armv7'
        output = '\n'.join(handler.log)
        filename = handler.filename
        filesize = handler.filesize
        build_time = time() - start_time
        db.log_build(
            package, architecture, status, output, filename, filesize,
            build_time
        )
    total_time = time() - build_start_time
    num_packages = len(packages)
    fail = num_packages - success
    db.log_build_run(num_packages, success, fail, total_time)

if __name__ == '__main__':
    main()
