import pip
import os
from time import time
from glob import glob
import better_exceptions

from db import PiWheelsDatabase
from auth import dbname, user, host, password
from tools import PiWheelsHandler

db = PiWheelsDatabase(dbname, user, host, password)

wc = pip.commands.WheelCommand()

wheels_dir = '/var/www/html'
temp_dir = '/tmp/piwheels'

def main(packages):
    handler = PiWheelsHandler()
    pip.logger.addHandler(handler)
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    for package in packages:
        handler.reset()
        module_dir = '{}/{}'.format(wheels_dir, package)
        if not os.path.exists(module_dir):
            os.makedirs(module_dir)

        wheel_dir = '--wheel-dir={}'.format(temp_dir)
        no_deps = '--no-deps'
        no_cache = '--no-cache-dir'
        start_time = time()
        status = not wc.main([wheel_dir, no_deps, no_cache, package])
        build_time = time() - start_time
        output = '\n'.join(handler.log)

        if status:
            temp_wheel_path = glob('{}/*'.format(temp_dir))[0]
            wheel_file = temp_wheel_path.split('/')[-1]
            final_wheel_path = '{}/{}/{}'.format(
                wheels_dir, package, wheel_file
            )
            os.rename(temp_wheel_path, final_wheel_path)
            filename = final_wheel_path.split('/')[-1]
            filesize = os.stat(final_wheel_path).st_size
            wheel_tags = final_wheel_path[:-4].split('-')[-4:]
            version, py_version_tag, abi_tag, platform_tag = wheel_tags

        db.log_build(
            package, status, output, filename, filesize, build_time, version,
            py_version_tag, abi_tag, platform_tag
        )

if __name__ == '__main__':
    packages = db.get_unattempted_packages()
    main(packages)
