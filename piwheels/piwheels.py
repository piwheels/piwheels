import pip
import os
from glob import glob
from time import time

from db import PiWheelsDatabase
from tools import PiWheelsHandler

db = PiWheelsDatabase()
wc = pip.commands.WheelCommand()
handler = PiWheelsHandler()
pip.logger.addHandler(handler)

class PiWheelsBuilder:
    def __init__(self, package, version):
        self.package = package
        self.version = version
        self.filename = None
        self.filesize = None
        self.package_version_tag = None
        self.py_version_tag = None
        self.abi_tag = None
        self.platform_tag = None
        handler.reset()

    def build_wheel(self, wheel_dir='/tmp/piwheels'):
        wheel_dir = '{}/{}'.format(wheel_dir, self.package)
        if not os.path.exists(wheel_dir):
            os.makedirs(wheel_dir)

        _wheel_dir = '--wheel-dir={}'.format(wheel_dir)
        _no_deps = '--no-deps'
        _no_cache = '--no-cache-dir'
        _package_spec = '{}=={}'.format(self.package, self.version)
        start_time = time()
        wc_args = [_wheel_dir, _no_deps, _no_cache, _package_spec]
        self.status = not wc.main(wc_args)
        self.build_time = time() - start_time
        self.output = '\n'.join(handler.log)

        if self.status:
            wheel_file = glob('{}/*.whl'.format(wheel_dir))[0]
            self.filename = wheel_file.split('/')[-1]
            self.filesize = os.stat(wheel_file).st_size
            wheel_tags = wheel_file[:-4].split('-')
            self.package_version_tag = wheel_tags[-4]
            self.py_version_tag = wheel_tags[-3]
            self.abi_tag = wheel_tags[-2]
            self.platform_tag = wheel_tags[-1]

    def log_build(self):
        db.log_build(
            self.package,
            self.version,
            self.status,
            self.output,
            self.filename,
            self.filesize,
            self.build_time,
            self.package_version_tag,
            self.py_version_tag,
            self.abi_tag,
            self.platform_tag
        )
