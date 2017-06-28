from piwheels import PiWheelsBuilder
from db import PiWheelsDatabase

db = PiWheelsDatabase()

for package, version in db.get_build_queue():
    if db.build_active():
        builder = PiWheelsBuilder(package, version)
        builder.build_wheel()
        builder.log_build()
    else:
        print("The build is currently inactive")
        break
