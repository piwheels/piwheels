import better_exceptions

from db import PiWheelsDatabase
from auth import dbname, user, host, password
from tools import list_pypi_packages, get_package_latest_version

db = PiWheelsDatabase(dbname, user, host, password)

pypi_packages = set(list_pypi_packages())
known_packages = set(db.get_all_packages())
missing_packages = pypi_packages.difference(known_packages)

print('{} missing packages: {}'.format(
    len(missing_packages),
    ' '.join(missing_packages)
))

for package in missing_packages:
    version = get_package_latest_version(package)
    print('Adding {} version {}'.format(package, version))
    db.add_new_package(package, version)

for package in known_packages:
    latest_version = get_package_latest_version(package)
    known_version = db.get_package_version(package)
    if latest_version != known_version:
        print('Updating {} from {} to {}'.format(
            package, known_version, latest_version
        ))
        db.update_package_version(package, latest_version)
