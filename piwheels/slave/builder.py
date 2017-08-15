import os
import tempfile
import hashlib
from subprocess import Popen, DEVNULL, TimeoutExpired
from time import time
from pathlib import Path


class PiWheelsPackage:
    def __init__(self, path):
        self.wheel_file = path
        self.filename = path.name
        self.filesize = path.stat().st_size
        m = hashlib.sha256()
        with path.open('rb') as f:
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

    def open(self, mode='rb'):
        return self.wheel_file.open(mode)


class PiWheelsBuilder:
    """
    PiWheels builder class

    Builds Python wheels of a given version of a given package
    """
    def __init__(self, package, version):
        self.wheel_dir = None
        self.package = package
        self.version = version
        self.duration = None
        self.output = ''
        self.files = []

    def build(self, timeout=None):
        self.wheel_dir = tempfile.TemporaryDirectory()
        with tempfile.NamedTemporaryFile(dir=self.wheel_dir.name) as log_file:
            env = os.environ.copy()
            # Force git to fail if it needs to prompt for anything (a disturbing
            # minority of packages try to run git clone during their setup.py)
            env['GIT_ALLOW_PROTOCOL'] = 'file'
            args = [
                'pip', 'wheel',
                '--wheel-dir={}'.format(self.wheel_dir.name),
                '--log={}'.format(log_file.name),
                '--no-deps',                    # don't build dependencies
                '--no-cache-dir',               # disable the cache directory
                '--exists-action=w',            # if paths already exist, wipe them
                '--disable-pip-version-check',  # don't bother checking for new pip
                '{}=={}'.format(self.package, self.version),
            ]
            start = time()
            proc = Popen(
                args,
                stdin=DEVNULL,     # ensure stdin is /dev/null; this causes
                                   # anything silly enough to use input() in
                                   # its setup.py to fail immediately
                stdout=DEVNULL,    # also ignore all output
                stderr=DEVNULL,
                env=env
            )
            # If the build times out attempt to kill it with SIGTERM; if that
            # hasn't worked after 10 seconds, resort to SIGKILL
            try:
                proc.wait(timeout)
            except TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(10)
                except TimeoutExpired:
                    proc.kill()
            self.duration = time() - start
            self.status = proc.returncode == 0
            log_file.seek(0)
            self.output = log_file.read()

            if self.status:
                for path in Path(self.wheel_dir.name).glob('*.whl'):
                    self.files.append(PiWheelsPackage(path))

    def clean(self):
        if self.wheel_dir:
            self.wheel_dir.cleanup()
            self.wheel_dir = None
