from db import PiWheelsDatabase
from auth import dbname, user, host, password
import better_exceptions
from tools import list_pypi_packages, bash_dush, bash_dfh

db = PiWheelsDatabase(dbname, user, host, password)

total_packages = len(list_pypi_packages())

summary = db.get_package_summary()
last_package = db.get_last_package_built()
total_built = summary['total']
successful_builds = summary['success']
failed_builds = summary['fail']
total_build_time = db.get_total_build_time()
longest_build = db.get_longest_build()
longest_build_time = longest_build['build_time']
longest_build_package = longest_build['package']
dush = bash_dush('/var/www/html/')
dfh = bash_dfh('/')

html = """
<h1>piwheels</h1>
Python package repository providing wheels (pre-built binaries) for Raspberry Pi

<h2>Stats</h2>
<strong>Packages attempted</strong>: {0:,} / {1:,} ({2:,}%)<br>
<strong>Successfully built</strong>: {3:,}<br>
<strong>Failed</strong>: {4:,}<br>
<strong>Success rate</strong>: {5}%<br>
<strong>Last package built</strong>: <a href="/{6}/">{6}</a><br>
<strong>Total time spent building</strong>: {7} hours<br>
<strong>Longest time spent building a package</strong>: {8} minutes (<a href="/{9}/">{9}</a>)<br>
<strong>Total disk usage from wheels</strong>: {10}<br>
<strong>System disk usage</strong>: {11}

<h2>About</h2>
Read more about this project on GitHub: <a href="https://github.com/bennuttall/piwheels">github.com/bennuttall/piwheels</a>
""".format(
    total_built,
    total_packages,
    round(total_built / total_packages * 100),
    successful_builds,
    failed_builds,
    round(successful_builds / total_built * 100),
    last_package,
    round(total_build_time / 60 / 60),
    round(longest_build_time / 60),
    longest_build_package,
    dush,
    dfh,
)
with open('/var/www/html/index.html', 'w') as f:
    f.write(html)
