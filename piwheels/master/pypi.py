import logging
import xmlrpc.client as xmlrpclib

import requests


def get_all_packages():
    """
    Returns a sorted list of all packages on PyPI using the xmlrpc interface
    """
    logging.info('Querying PyPI package list')
    client = xmlrpclib.ServerProxy('https://pypi.python.org/pypi')
    return client.list_packages()


def get_package_info(package):
    """
    Returns information about a given package from the PyPI JSON API
    """
    url = 'https://pypi.python.org/pypi/{}/json'.format(package)
    try:
        return requests.get(url).json()
    except:
        return None


def get_package_versions(package):
    """
    Returns all versions with source code for a given package released on PyPI
    """
    package_info = get_package_info(package)
    try:
        return [
            release
            for release, release_files in package_info['releases'].items()
            if 'sdist' in [release_file['packagetype'] for release_file in release_files]
        ]
    except TypeError:
        return []

