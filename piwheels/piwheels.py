import pip
import os
import better_exceptions
from glob import glob
from time import time

from db import PiWheelsDatabase
from auth import dbname, user, host, password
from tools import PiWheelsHandler

db = PiWheelsDatabase(dbname, user, host, password)
wc = pip.commands.WheelCommand()
handler = PiWheelsHandler()
pip.logger.addHandler(handler)

temp_dir = '/tmp/piwheels'

class PiWheelsBuilder:
    def __init__(self, package):
        self.package = package
        self.filename = None
        self.filesize = None
        self.version = None
        self.py_version_tag = None
        self.abi_tag = None
        self.platform_tag = None

        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        self._temp_dir_contents_before = self._get_temp_dir_contents()
        handler.reset()

    def _get_temp_dir_contents(self):
        return set(glob('{}/*'.format(temp_dir)))

    def build_wheel(self):
        wheel_dir = '--wheel-dir={}'.format(temp_dir)
        no_deps = '--no-deps'
        no_cache = '--no-cache-dir'
        start_time = time()
        self.status = not wc.main([wheel_dir, no_deps, no_cache, self.package])
        self.build_time = time() - start_time
        self.output = '\n'.join(handler.log)

        if self.status:
            temp_dir_contents_after = self._get_temp_dir_contents()
            temp_dir_diff = list(temp_dir_contents_after.difference(
                self._temp_dir_contents_before
            ))
            if len(temp_dir_diff) == 1:
                wheel_path = temp_dir_diff[0]
                self.filename = wheel_path.split('/')[-1]
                self.filesize = os.stat(wheel_path).st_size
                wheel_tags = wheel_path[:-4].split('-')[-4:]
                self.version = wheel_tags[-4]
                self.py_version_tag = wheel_tags[-3]
                self.abi_tag = wheel_tags[-2]
                self.platform_tag = wheel_tags[-1]

    def log_build(self):
        db.log_build(
            self.package,
            self.status,
            self.output,
            self.filename,
            self.filesize,
            self.build_time,
            self.version,
            self.py_version_tag,
            self.abi_tag,
            self.platform_tag
        )
