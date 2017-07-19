from piwheels import PiWheelsBuilder
from db import PiWheelsDatabase
from datetime import datetime
from time import sleep

db = PiWheelsDatabase()

while True:
    for package, version in db.build_queue_generator():
        if db.build_active():
            dt = datetime.now()
            print('package {0} version {1} started at {2:%a} {2:%d} {2:%b} {2:%H}:{2:%M}'.format(
                package, version, dt
            ))
            builder = PiWheelsBuilder(package, version)
            builder.build_wheel('/home/piwheels/www')
            builder.log_build()
        else:
            print("The build is currently inactive")
            break
    sleep(60)
