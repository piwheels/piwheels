from math import floor

from db import PiWheelsDatabase
from auth import dbname, user, host, password
import better_exceptions
from tools import bash_dush, bash_dfh

db = PiWheelsDatabase(dbname, user, host, password)

total_processed = db.get_total_number_of_packages_processed()
total_packages = db.get_total_number_of_packages()
successful_builds = db.get_total_number_of_packages_successfully_built()
failed_builds = total_processed - successful_builds
last_package = db.get_last_package_processed()
total_build_time = db.get_total_build_time()

data = {
    'total_processed': total_processed,
    'total_packages': total_packages,
    'processed_pc': floor(total_processed / total_packages * 100),
    'successful_builds': successful_builds,
    'success_pc': round(successful_builds / total_processed * 100),
    'failed_builds': failed_builds,
    'failed_pc': round(failed_builds / total_processed * 100),
    'last_package_name': last_package['package'],
    'last_package_time': last_package['build_datetime'],
    'total_build_time': round(total_build_time / 60 / 60),
    'packages_requiring_update': len(list(db.get_packages_with_update_available())),
    'packages_in_last_hour': db.get_number_of_packages_processed_in_last_hour(),
    'dush': bash_dush('/var/www/html/'),
    'dfh': bash_dfh('/'),
}

html = """
<h1>piwheels</h1>
Python package repository providing wheels (pre-built binaries) for Raspberry Pi

<h2>Stats</h2>
<strong>Packages processed</strong>: {total_processed:,} / {total_packages:,} ({processed_pc:,}%)<br>
<strong>Successfully built</strong>: {successful_builds:,} ({success_pc}%)<br>
<strong>Failed</strong>: {failed_builds:,} ({failed_pc}%)<br>
<strong>Last package processed</strong>: <a href="/{last_package_name}/">{last_package_name}</a> ({last_package_time})<br>
<strong>Total time spent building</strong>: {total_build_time} hours<br>
<strong>Packages requiring an update</strong>: {packages_requiring_update:,}<br>
<strong>Packages processed in the last hour</strong>: {packages_in_last_hour}<br>
<strong>Total disk usage from wheels</strong>: {dush}<br>
<strong>System disk usage</strong>: {dfh}

<h2>About</h2>
Read more about this project on GitHub: <a href="https://github.com/bennuttall/piwheels">github.com/bennuttall/piwheels</a>
""".format(**data)

with open('/var/www/html/index.html', 'w') as f:
    f.write(html)
