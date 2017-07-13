from math import floor

from db import PiWheelsDatabase
from tools import bash_dush, bash_dfh

db = PiWheelsDatabase()

total_packages = db.get_total_packages()
total_packages_processed = db.get_total_packages_processed()
total_package_versions = db.get_total_package_versions()
total_package_versions_processed = db.get_total_package_versions_processed()
successful_builds = db.get_total_successful_builds()
failed_builds = total_package_versions_processed - successful_builds
last_package = db.get_last_package_processed()
total_build_time = db.get_total_build_time()

data = {
    'total_packages': total_packages,
    'total_packages_processed': total_packages_processed,
    'packages_processed_pc': floor(total_packages_processed / total_packages * 100),
    'total_package_versions': total_package_versions,
    'total_package_versions_processed': total_package_versions_processed,
    'package_versions_processed_pc': floor(total_package_versions_processed / total_package_versions * 100),
    'successful_builds': successful_builds,
    'success_pc': round(successful_builds / total_package_versions_processed * 100),
    'failed_builds': failed_builds,
    'failed_pc': round(failed_builds / total_package_versions_processed * 100),
    'last_package_name': last_package['package'],
    'last_package_time': last_package['build_datetime'],
    'total_build_time': round(total_build_time / 60 / 60),
    'builds_in_last_hour': db.get_builds_processed_in_last_hour(),
    'dush': bash_dush('/home/piwheels/www/'),
    'dfh': bash_dfh('/'),
}

html = """
<h1>piwheels</h1>
Python package repository providing wheels (pre-built binaries) for Raspberry Pi

<h2>Stats</h2>
<strong>Packages processed</strong>: {total_packages_processed:,} / {total_packages:,} ({packages_processed_pc:,}%)<br>
<strong>Package versions processed</strong>: {total_package_versions_processed:,} / {total_package_versions:,} ({package_versions_processed_pc:,}%)<br>
<strong>Successfully built</strong>: {successful_builds:,} ({success_pc}%)<br>
<strong>Failed</strong>: {failed_builds:,} ({failed_pc}%)<br>
<strong>Last package processed</strong>: <a href="/{last_package_name}/">{last_package_name}</a> ({last_package_time})<br>
<strong>Total time spent building</strong>: {total_build_time} hours<br>
<strong>Builds processed in the last hour</strong>: {builds_in_last_hour}<br>
<strong>Total disk usage from wheels</strong>: {dush}<br>
<strong>System disk usage</strong>: {dfh}

<h2>About</h2>
Read more about this project on GitHub: <a href="https://github.com/bennuttall/piwheels">github.com/bennuttall/piwheels</a>
""".format(**data)

with open('/home/piwheels/www/index.html', 'w') as f:
    f.write(html)
