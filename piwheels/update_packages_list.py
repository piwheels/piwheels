import better_exceptions

from db import PiWheelsDatabase
from auth import dbname, user, host, password
from tools import list_pypi_packages, get_package_info

db = PiWheelsDatabase(dbname, user, host, password)

pypi_packages = set(list_pypi_packages())
known_packages = set(db.get_all_packages())
missing_packages = pypi_packages.difference(known_packages)

print('{} missing packages: {}'.format(
    len(missing_packages),
    ' '.join(missing_packages)
))

for package in missing_packages:
    package_info = get_package_info(package)
    if package_info:
        version = package_info['info']['version']
    else:
        version = ''
    print('Adding {} v{}'.format(package, version))
    db.add_new_package(package, version)
