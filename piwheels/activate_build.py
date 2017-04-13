from db import PiWheelsDatabase
from auth import dbname, user, host, password


db = PiWheelsDatabase(dbname, user, host, password)

db.activate_build()
