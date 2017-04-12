import better_exceptions

from piwheels import PiWheelsBuilder
from db import PiWheelsDatabase
from auth import dbname, user, host, password

db = PiWheelsDatabase(dbname, user, host, password)


def main(packages):
    for package in packages:
        if db.build_active():
            builder = PiWheelsBuilder(package)
            builder.build_wheel()
            builder.log_build()
        else:
            print("The build is currently inactive")
            break


if __name__ == '__main__':
    packages = db.get_unattempted_packages()
    main(packages)
