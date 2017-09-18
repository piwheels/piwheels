import os
import tempfile
import hashlib
import resource
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
        tags = path.stem.split('-')
        self.package_tag = tags[0]
        self.package_version_tag = tags[1]
        self.platform_tag = tags[-1]
        self.abi_tag = tags[-2]
        self.py_version_tag = tags[-3]
        self.build_tag = tags[2] if len(tags) == 6 else None

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
        with tempfile.NamedTemporaryFile('w+', dir=self.wheel_dir.name,
                                         suffix='.log', encoding='utf-8') as log_file:
            env = os.environ.copy()
            # Force git to fail if it needs to prompt for anything (a disturbing
            # minority of packages try to run git clone during their setup.py)
            env['GIT_ALLOW_PROTOCOL'] = 'file'
            args = [
                'pip3', 'wheel',
                '--wheel-dir={}'.format(self.wheel_dir.name),
                '--log={}'.format(log_file.name),
                '--no-deps',                    # don't build dependencies
                '--no-cache-dir',               # disable the cache directory
                '--exists-action=w',            # if paths already exist, wipe them
                '--disable-pip-version-check',  # don't bother checking for new pip
                '{}=={}'.format(self.package, self.version),
            ]
            # Limit the data segment of this process (and all children) to
            # 1Gb in size. This doesn't guarantee that stuff can't grow until
            # it crashes (after, multiple children can violate the limit
            # together while obeying it individually), but it should reduce the
            # incidence of huge C++ compiles killing the build slaves
            resource.setrlimit(resource.RLIMIT_DATA, (1024**3, 1024**3))
            start = time()
            try:
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
                    raise
            except Exception as e:
                error = str(e)
            else:
                error = None
            self.duration = time() - start
            self.status = proc.returncode == 0
            if error is not None:
                log_file.seek(0, os.SEEK_END)
                log_file.write('\n' + error)
            log_file.seek(0)
            self.output = log_file.read()

            if self.status:
                for path in Path(self.wheel_dir.name).glob('*.whl'):
                    self.files.append(PiWheelsPackage(path))
            return self.status

    def clean(self):
        if self.wheel_dir:
            self.wheel_dir.cleanup()
            self.wheel_dir = None
