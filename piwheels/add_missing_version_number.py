import better_exceptions

from db import PiWheelsDatabase
from auth import dbname, user, host, password
from tools import get_package_info

db = PiWheelsDatabase(dbname, user, host, password)

packages = db.get_all_packages()

for package in packages:
    print(package)
    package_info = get_package_info(package)
    if package_info:
        version = package_info['info']['version']
    else:
        version = ''
    db.update_package_version(package, version)
