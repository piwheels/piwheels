import os
import sys
import logging
import tempfile
import hashlib
from time import time
from pathlib import Path

import pip


class PiWheelsHandler(logging.Handler):
    """
    Custom logging handler appends all messages to a list
    """
    def emit(self, record):
        self.log.append(self.format(record))

    def reset(self):
        self.log = []

# Force git to fail if it needs to prompt for anything (a disturbing minority
# of packages try to run git clone during their setup.py ...)
os.environ['GIT_TERMINAL_PROMPT'] = '0'

# Force any attempt to read from the command line to fail by closing stdin
# (it's not enough to just close sys.stdin as that's a wrapper for the "real"
# stdin)
sys.stdin.close()
os.close(0)

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
        self.filehash = None
        self.package_version_tag = None
        self.py_version_tag = None
        self.abi_tag = None
        self.platform_tag = None
        handler.reset()

    def build(self):
        self.wheel_dir = tempfile.TemporaryDirectory()
        start = time()
        self.status = not wc.main([
            '--wheel-dir={}'.format(self.wheel_dir.name),
            '--no-deps',         # don't build dependencies
            '--no-cache-dir',    # disable the cache directory
            '--exists-action=w', # if paths already exist, wipe them
            '{}=={}'.format(self.package, self.version),
        ])
        self.duration = time() - start
        self.output = '\n'.join(handler.log)

        if self.status:
            self.wheel_file = next(Path(self.wheel_dir.name).glob('*.whl'))
            self.filename = self.wheel_file.name
            self.filesize = self.wheel_file.stat().st_size
            m = hashlib.sha256()
            with self.wheel_file.open('rb') as f:
                while True:
                    buf = f.read(65536)
                    if buf:
                        m.update(buf)
                    else:
                        break
            self.filehash = m.hexdigest().lower()
            wheel_tags = self.filename[:-4].split('-')
            self.package_version_tag = wheel_tags[-4]
            self.py_version_tag = wheel_tags[-3]
            self.abi_tag = wheel_tags[-2]
            self.platform_tag = wheel_tags[-1]

    def open(self):
        return self.wheel_file.open('rb')

    def clean(self):
        if self.wheel_dir:
            self.wheel_dir.cleanup()
            self.wheel_dir = None

