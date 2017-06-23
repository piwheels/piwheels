from db import PiWheelsDatabase
from time import sleep

db = PiWheelsDatabase()

while True:
    db.update_package_list()
    db.update_package_version_list()
    sleep(60)
