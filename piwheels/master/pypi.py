import logging
import xmlrpc.client as xmlrpclib

import requests

logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)


def get_all_packages(pypi_root='https://pypi.python.org/pypi'):
    """
    Returns a sorted list of all packages on PyPI using the xmlrpc interface
    """
    logging.info('Querying PyPI package list')
    client = xmlrpclib.ServerProxy(pypi_root)
    return client.list_packages()


def get_package_info(package, pypi_root='https://pypi.python.org/pypi'):
    """
    Returns information about a given package from the PyPI JSON API
    """
    url = '{pypi_root}/{package}/json'.format(**vars())
    try:
        return requests.get(url).json()
    except:
        return None


def get_package_versions(package, pypi_root='https://pypi.python.org/pypi'):
    """
    Returns all versions with source code for a given package released on PyPI
    """
    package_info = get_package_info(package, pypi_root)
    try:
        return [
            release
            for release, release_files in package_info['releases'].items()
            if 'sdist' in [release_file['packagetype'] for release_file in release_files]
        ]
    except TypeError:
        return []

