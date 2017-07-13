from piwheels import PiWheelsBuilder
from db import PiWheelsDatabase
from time import sleep

db = PiWheelsDatabase()

while True:
    for package, version in db.build_queue_generator():
        if db.build_active():
            builder = PiWheelsBuilder(package, version)
            builder.build_wheel('/home/piwheels/www')
            builder.log_build()
        else:
            print("The build is currently inactive")
            break
    sleep(60)
