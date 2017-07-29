import pip
import logging
import tempfile
from glob import glob
from time import time
from pathlib import Path


class PiWheelsHandler(logging.Handler):
    """
    Custom logging handler appends all messages to a list
    """
    def emit(self, record):
        self.log.append(self.format(record))

    def reset(self):
        self.log = []


wc = pip.commands.WheelCommand()
handler = PiWheelsHandler()
pip.logger.addHandler(handler)


class PiWheelsBuilder:
    """
    PiWheels builder class

    Builds Python wheels of a given version of a given package
    """
    def __init__(self, package, version):
        self.wheel_dir = None
        self.package = package
        self.version = version
        self.filename = None
        self.filesize = None
        self.package_version_tag = None
        self.py_version_tag = None
        self.abi_tag = None
        self.platform_tag = None
        handler.reset()

    def build(self):
        self.wheel_dir = tempfile.TemporaryDirectory()

        _wheel_dir = '--wheel-dir={}'.format(wheel_dir.name)
        _no_deps = '--no-deps'
        _no_cache = '--no-cache-dir'
        _package_spec = '{}=={}'.format(self.package, self.version)
        start_time = time()
        self.status = not wc.main((_wheel_dir, _no_deps, _no_cache, _package_spec))
        self.duration = time() - start_time
        self.output = '\n'.join(handler.log)

        if self.status:
            self.wheel_file = Path(wheel_dir.name).glob('*.whl')[0]
            self.filename = self.wheel_file.name
            self.filesize = self.wheel_file.stat().st_size
            wheel_tags = self.filename[:-4].split('-')
            self.package_version_tag = wheel_tags[-4]
            self.py_version_tag = wheel_tags[-3]
            self.abi_tag = wheel_tags[-2]
            self.platform_tag = wheel_tags[-1]

    def clean(self):
        if self.wheel_dir:
            self.wheel_dir.cleanup()
            self.wheel_dir = None

