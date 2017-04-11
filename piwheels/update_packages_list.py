from db import PiWheelsDatabase
from auth import dbname, user, host, password
import better_exceptions
from tools import list_pypi_packages, bash_dush, bash_dfh

db = PiWheelsDatabase(dbname, user, host, password)

pypi_packages = set(list_pypi_packages())
known_packages = set(db.get_all_packages())
missing_packages = pypi_packages.difference(known_packages)

for package in missing_packages:
    db.add_new_package(package)
