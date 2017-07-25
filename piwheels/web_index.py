from math import floor, ceil

from db import PiWheelsDatabase
from tools import bash_dfh

db = PiWheelsDatabase()

total_packages = db.get_total_packages()
total_package_versions = db.get_total_package_versions()
total_package_versions_processed = db.get_total_package_versions_processed()
successful_builds = db.get_total_successful_builds()
failed_builds = total_package_versions_processed - successful_builds
last_package = db.get_last_package_processed()
total_build_time_seconds = db.get_total_build_time()
build_time_days, build_time_hours = divmod(total_build_time_seconds / 60 / 60, 24)
build_time_hours = floor(build_time_hours)
builds_in_last_day = db.get_builds_processed_in_interval('1 day')
package_versions_remaining = total_package_versions - total_package_versions_processed
estimated_completion_time_days, remainder = divmod(package_versions_remaining, builds_in_last_day)
estimated_completion_time_hours = ceil(remainder / builds_in_last_day * 24)

data = {
    'total_packages': total_packages,
    'total_package_versions': total_package_versions,
    'total_package_versions_processed': total_package_versions_processed,
    'package_versions_processed_pc': floor(total_package_versions_processed / total_package_versions * 100),
    'successful_builds': successful_builds,
    'success_pc': round(successful_builds / total_package_versions_processed * 100),
    'failed_builds': failed_builds,
    'failed_pc': round(failed_builds / total_package_versions_processed * 100),
    'last_package_name': last_package['package'],
    'last_package_time': last_package['build_datetime'],
    'build_time_days': build_time_days,
    'build_time_hours': build_time_hours,
    'builds_in_last_hour': db.get_builds_processed_in_interval('1 hour'),
    'builds_in_last_day': builds_in_last_day,
    'builds_in_last_day_pc': round(builds_in_last_day / total_package_versions * 100),
    'estimated_completion_time_days': estimated_completion_time_days,
    'estimated_completion_time_hours': estimated_completion_time_hours,
    'total_wheel_usage': db.get_total_wheel_filesize() // 1024**3,
    'disk_usage': bash_dfh('/'),
}

html = """
<h1>piwheels</h1>
Python package repository providing wheels (pre-built binaries) for Raspberry Pi

<h2>Stats</h2>
<strong>Total packages</strong>: {total_packages:,}<br>
<strong>Package versions processed</strong>: {total_package_versions_processed:,} / {total_package_versions:,} ({package_versions_processed_pc}%)<br>
<strong>Successfully built</strong>: {successful_builds:,} ({success_pc}%)<br>
<strong>Failed</strong>: {failed_builds:,} ({failed_pc}%)<br>
<strong>Last package processed</strong>: <a href="/{last_package_name}/">{last_package_name}</a> ({last_package_time})<br>
<strong>Total time spent building</strong>: {build_time_days} days {build_time_hours} hours<br>
<strong>Builds processed in the last hour</strong>: {builds_in_last_hour:,}<br>
<strong>Builds processed in the last day</strong>: {builds_in_last_day:,} ({builds_in_last_day_pc}% of total)<br>
<strong>Estimated time to completion</strong>: {estimated_completion_time_days:,} days {estimated_completion_time_hours:,} hours<br>
<strong>Total disk usage from wheels</strong>: {total_wheel_usage}GB<br>
<strong>System disk usage</strong>: {disk_usage}

<h2>About</h2>
Read more about this project on GitHub: <a href="https://github.com/bennuttall/piwheels">github.com/bennuttall/piwheels</a>
""".format(**data)

with open('/home/piwheels/www/index.html', 'w') as f:
    f.write(html)
