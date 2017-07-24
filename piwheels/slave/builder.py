import pip
from glob import glob
from time import time
from pathlib import Path

from .tools import PiWheelsHandler

wc = pip.commands.WheelCommand()
handler = PiWheelsHandler()
pip.logger.addHandler(handler)

class PiWheelsBuilder:
    """
    PiWheels builder class

    Builds Python wheels of a given version of a given package
    """
    def __init__(self, root_logger, package, version):
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
        wheel_dir = Path(wheel_dir) / self.package
        try:
            wheel_dir.mkdir()
        except FileExistsError:
            pass

        _wheel_dir = '--wheel-dir={}'.format(wheel_dir)
        _no_deps = '--no-deps'
        _no_cache = '--no-cache-dir'
        _package_spec = '{}=={}'.format(self.package, self.version)
        start_time = time()
        self.status = not wc.main((_wheel_dir, _no_deps, _no_cache, _package_spec))
        self.build_time = time() - start_time
        self.output = '\n'.join(handler.log)

        if self.status:
            wheel_file = wheel_dir.glob('*.whl')[0]
            self.filename = wheel_file.name
            self.filesize = wheel_file.stat().st_size
            wheel_tags = wheel_file.name[:-4].split('-')
            self.package_version_tag = wheel_tags[-4]
            self.py_version_tag = wheel_tags[-3]
            self.abi_tag = wheel_tags[-2]
            self.platform_tag = wheel_tags[-1]

