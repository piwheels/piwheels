import os

from db import PiWheelsDatabase
from auth import dbname, user, host, password
from tools import get_wheels_lis, get_package_output, get_install_instructions


db = PiWheelsDatabase(dbname, user, host, password)

packages = db.get_all_packages()

for package in packages:
    print(package)
    package_dir = '/var/www/html/{}'.format(package)
    if not os.path.exists(package_dir):
        os.makedirs(package_dir)
    output_file = '{}/index.html'.format(package_dir)

    status = db.get_package_build_status(package)

    data = {
        'package': package,
        'status': 'Success' if status else 'Fail',
        'wheels_ul': get_wheels_lis(db, package),
        'output': get_package_output(db, package),
        'install': get_install_instructions(package) if status else '',
    }

    with open(output_file, 'w+') as f:
        text = """
        <h1>{package}</h1>
        See <a href="https://pypi.python.org/pypi/{package}/">{package}</a> on PyPI
        <h2>Build status</h2>
        {status}
        {install}
        <h2>Wheel files available</h2>
        {wheels_ul}
        <h2>Build log</h2>
        <pre>{output}</pre>
        """.format(**data)
        f.write(text)
