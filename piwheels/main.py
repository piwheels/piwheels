import better_exceptions

from piwheels import PiWheelsBuilder


def main(packages):
    for package in packages:
        builder = PiWheelsBuilder(package)
        builder.build_wheel()
        builder.log_build()


if __name__ == '__main__':
    from db import PiWheelsDatabase
    from auth import dbname, user, host, password

    db = PiWheelsDatabase(dbname, user, host, password)
    #packages = db.get_unattempted_packages()
    packages = ['gpiozero', 'pigpio', 'rpi.gpio']
    main(packages)
