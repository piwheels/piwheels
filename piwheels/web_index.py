from db import PiWheelsDatabase
from auth import dbname, user, host, password

db = PiWheelsDatabase(dbname, user, host, password)

summary = db.get_package_summary()
last_package = db.get_last_package_built()

html = """
<h1>piwheels</h1>
Python package repository providing wheels (pre-built binaries) for Raspberry Pi

<h2>Stats</h2>
Packages attempted: {0:,}<br>
Successfully built: {1:,}<br>
Failed: {2:,}<br>
Success rate: {3}%<br>
Last package built: <a href="/{4}/">{4}</a>

<h2>About</h2>
Read more about this project on GitHub: <a href="https://github.com/bennuttall/piwheels">github.com/bennuttall/piwheels</a>
""".format(
    summary['total'],
    summary['success'],
    summary['fail'],
    round(summary['success'] / summary['total'] * 100),
    last_package
)
with open('/var/www/html/index.html', 'w') as f:
    f.write(html)
