from db import PiWheelsDatabase
from tools import list_pypi_packages, get_package_info, get_package_versions
from piwheels import PiWheelsBuilder

from gpiozero import PingServer
import pytest

db = PiWheelsDatabase()

# Test checking build status
assert db.build_active()
db.deactivate_build()
assert not db.build_active()
db.activate_build()
assert db.build_active()

# Test adding a package to the database
build_queue = db.build_queue_generator()
assert db.get_build_queue() == []
with pytest.raises(StopIteration):
    next(build_queue)
db.add_new_package('abc')
assert db.get_total_number_of_packages() == 1
assert db.get_build_queue() == []
assert db.get_package_versions('abc') == []

# Test adding a package version to the database
db.add_new_package_version('abc', '0.0.1')
assert db.get_total_number_of_package_versions() == 1
assert db.get_build_queue() == [['abc', '0.0.1']]
build_queue = db.build_queue_generator()
assert next(build_queue) == ['abc', '0.0.1']
assert next(build_queue) == ['abc', '0.0.1']  # should still be next in queue as it's not yet been built
assert db.get_package_versions('abc') == ['0.0.1']

db.add_new_package_version('abc', '0.0.2')
assert db.get_total_number_of_packages() == 1
assert db.get_total_number_of_package_versions() == 2
assert db.get_build_queue() == [['abc', '0.0.1'], ['abc', '0.0.2']]
assert next(build_queue) == ['abc', '0.0.1']  # should still be next in queue as it's not yet been built
assert db.get_package_versions('abc') == ['0.0.1', '0.0.2']

# Test logging builds
db.log_build('abc', '0.0.1', False, 'output', None, None, None, None, None, None, None)
assert next(build_queue) == ['abc', '0.0.2']
db.log_build('abc', '0.0.2', True, 'output', 'HELLO', 12345, 1.2345, '0.0.2', 'py3', 'none', 'any')
with pytest.raises(StopIteration):
    next(build_queue)

# Test adding another package
assert list(db.get_all_packages()) == ['abc']
db.add_new_package('def')
assert list(db.get_all_packages()) == ['abc', 'def']
db.add_new_package_version('def', '1.0')
assert db.get_total_number_of_packages() == 2
assert db.get_total_number_of_package_versions() == 3
assert db.get_build_queue() == [['def', '1.0']]

build_queue = db.build_queue_generator()
assert next(build_queue) == ['def', '1.0']

pypi_server = PingServer('pypi.python.org')

if pypi_server.is_active:
    # Test PyPI information functions
    packages = list_pypi_packages()
    assert len(packages) > 0

    gpiozero_info = get_package_info('gpiozero')
    assert 'releases' in gpiozero_info
    assert '1.0.0' in gpiozero_info['releases']

    gpiozero_versions = get_package_versions('gpiozero')
    assert '1.0.0' in gpiozero_versions

    # Test wheel building
    db.add_new_package('gpiozero')
    db.add_new_package_version('gpiozero', '1.0.0')
    builder = PiWheelsBuilder('gpiozero', '1.0.0')
    builder.build_wheel()
    builder.log_build()
    assert db.get_last_package_processed()[0] == 'gpiozero'
else:
    print('Failed connection to {}: Skipping PyPI tests'.format(pypi_server.host))
