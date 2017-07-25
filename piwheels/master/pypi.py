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
    Returns all versions for a given package released on PyPI
    """
    package_info = get_package_info(package)
    try:
        return package_info['releases'].keys()
    except TypeError:
        return []

