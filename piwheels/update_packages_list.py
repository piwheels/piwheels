from db import PiWheelsDatabase
from tools import list_pypi_packages, get_package_versions

db = PiWheelsDatabase()

while True:
    pypi_packages = set(list_pypi_packages())
    known_packages = set(db.get_all_packages())
    missing_packages = pypi_packages.difference(known_packages)

    print('{} missing packages: {}'.format(
        len(missing_packages), ' '.join(missing_packages)
    ))

    for package in missing_packages:
        print('Adding {}'.format(package))
        db.add_new_package(package)

    known_packages = db.get_all_packages()

    for package in known_packages:
        pypi_versions = set(get_package_versions())
        known_versions = set(get_package_versions())
        missing_versions = pypi_versions.difference(known_versions)
        print('package {} has {} missing packages: {}'.format(
            package, len(missing_versions), ' '.join(missing_versions)
        ))
        for version in missing_versions:
            print('Adding {} version {}'.format(package, version))
            db.add_new_package_version(package, version)
    sleep(60)
