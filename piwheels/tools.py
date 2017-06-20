import logging
import subprocess
import xmlrpc.client as xmlrpclib
import requests


class PiWheelsHandler(logging.Handler):
    """
    Custom logging handler appends all messages to a list
    """
    def emit(self, record):
        msg = self.format(record)
        self.log.append(msg)

    def reset(self):
        self.log = []


def list_pypi_packages():
    """
    Returns a sorted list of all packages on PyPI using the xmlrpc interface
    """
    client = xmlrpclib.ServerProxy('https://pypi.python.org/pypi')
    return sorted(client.list_packages())

def get_package_info(package):
    """
    Returns information about a given package from the PyPI JSON API
    """
    url = 'https://pypi.python.org/pypi/{}/json'.format(package)
    r = requests.get(url)
    try:
        return r.json()
    except:
        return None

def get_package_versions(package):
    """
    Returns all versions for a given package released on PyPI
    """
    package_info = get_package_info(package)
    return sorted(package_info['releases'].keys())

def bash_dush(path):
    du = subprocess.Popen(['du', '-sh', path], stdout=subprocess.PIPE)
    output = du.communicate()[0].split()
    return output[0].decode('UTF-8') + 'B'

def bash_dfh(path='/'):
    df = subprocess.Popen(['df', '-h', path], stdout=subprocess.PIPE)
    output = df.communicate()[0].split()
    return output[11].decode('UTF-8')

def get_wheels_lis(db, package):
    lis = ''
    wheels = list(db.get_package_wheels(package))
    if wheels[0] is None:
        return 'None available'
    for wheel in wheels:
        lis += '<li><a href="{0}">{0}</a></li>'.format(wheel)
    return '<ul>{}</ul>'.format(lis)

def get_package_output(db, package):
    html = ''
    builds = db.get_package_output(package)
    for build_timestamp, status, output in builds:
        status_msg = 'success' if status else 'fail'
        html += '{} ({})\n{}\n\n'.format(build_timestamp, status_msg, output)
    return html

def get_install_instructions(package):
    url = 'http://piwheels.bennuttall.com'
    return """
    <h2>Install</h2>
    <pre>pip install {} -i {}</pre>
    """.format(package, url)
