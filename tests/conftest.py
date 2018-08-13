# The piwheels project
#   Copyright (c) 2017 Ben Nuttall <https://github.com/bennuttall>
#   Copyright (c) 2017 Dave Jones <dave@waveform.org.uk>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


import os
from unittest import mock
from datetime import datetime, timedelta
from hashlib import sha256

import zmq
import pytest
from sqlalchemy import create_engine

from piwheels import const
from piwheels.master.states import BuildState, FileState, DownloadState
from piwheels.initdb import get_script, parse_statements


# The database tests all assume that a database (default: piwheels_test)
# exists, along with two users. An ordinary unprivileged user (default:
# piwheels) which will be used as if it were the piwheels user on the
# production database, and a postgres superuser (default: postgres) which will
# be used to set up structures in the test database and remove them between
# each test. The environment variables listed below can be used to configure
# the names of these entities for use by the test suite.

PIWHEELS_TESTDB = os.environ.get('PIWHEELS_TESTDB', 'piwheels_test')
PIWHEELS_USER = os.environ.get('PIWHEELS_USER', 'piwheels')
PIWHEELS_PASS = os.environ.get('PIWHEELS_PASS', 'piwheels')
PIWHEELS_SUPERUSER = os.environ.get('PIWHEELS_SUPERUSER', 'postgres')
PIWHEELS_SUPERPASS = os.environ.get('PIWHEELS_SUPERPASS', '')


@pytest.fixture()
def file_content(request):
    return b'\x01\x02\x03\x04\x05\x06\x07\x08' * 15432  # 123456 bytes


@pytest.fixture()
def file_state(request, file_content):
    h = sha256()
    h.update(file_content)
    return FileState(
        'foo-0.1-cp34-cp34m-linux_armv7l.whl', len(file_content),
        h.hexdigest().lower(), 'foo', '0.1', 'cp34', 'cp34m', 'linux_armv7l')


@pytest.fixture()
def file_state_hacked(request, file_content):
    h = sha256()
    h.update(file_content)
    return FileState(
        'foo-0.1-cp34-cp34m-linux_armv6l.whl', len(file_content),
        h.hexdigest().lower(), 'foo', '0.1', 'cp34', 'cp34m', 'linux_armv6l')


@pytest.fixture()
def file_state_universal(request, file_content):
    h = sha256()
    h.update(file_content)
    return FileState(
        'foo-0.1-py2.py3-none-any.whl', len(file_content),
        h.hexdigest().lower(), 'foo', '0.1', 'py2.py3', 'none', 'any')


@pytest.fixture()
def build_state(request, file_state):
    return BuildState(
        1, file_state.package_tag, file_state.package_version_tag,
        file_state.abi_tag, True, 300, 'Built successfully',
        {file_state.filename: file_state})


@pytest.fixture()
def build_state_hacked(request, file_state, file_state_hacked):
    return BuildState(
        1, file_state.package_tag, file_state.package_version_tag,
        file_state.abi_tag, True, 300, 'Built successfully', {
            file_state.filename: file_state,
            file_state_hacked.filename: file_state_hacked,
        })


@pytest.fixture()
def download_state(request, file_state):
    return DownloadState(
        file_state.filename, '123.4.5.6', datetime(2018, 1, 1, 0, 0, 0),
        'armv7l', 'Raspbian', '9', 'Linux', '', 'CPython', '3.5')


@pytest.fixture(scope='session')
def db_engine(request):
    url = 'postgres://{username}:{password}@/{db}'.format(
        username=PIWHEELS_SUPERUSER,
        password=PIWHEELS_SUPERPASS,
        db=PIWHEELS_TESTDB
    )
    engine = create_engine(url)
    def fin():
        engine.dispose()
    request.addfinalizer(fin)
    return engine


@pytest.fixture()
def db(request, db_engine):
    conn = db_engine.connect()
    def fin():
        conn.close()
    request.addfinalizer(fin)
    conn.execute("SET SESSION synchronous_commit TO OFF")  # it's only a test
    return conn


@pytest.fixture(scope='function')
def with_schema(request, db):
    with db.begin():
        # Wipe the public schema and re-create it with standard defaults
        db.execute("DROP SCHEMA public CASCADE")
        db.execute("CREATE SCHEMA public AUTHORIZATION postgres")
        db.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
        db.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
        for stmt in parse_statements(get_script()):
            stmt = stmt.format(username=PIWHEELS_USER)
            db.execute(stmt)
    return 'schema'


@pytest.fixture()
def with_build_abis(request, db, with_schema):
    with db.begin():
        db.execute(
            "INSERT INTO build_abis VALUES ('cp34m'), ('cp35m')")
    return {'cp34m', 'cp35m'}


@pytest.fixture()
def with_package(request, db, with_build_abis, build_state):
    with db.begin():
        db.execute(
            "INSERT INTO packages(package) VALUES (%s)", build_state.package)
    return build_state.package


@pytest.fixture()
def with_package_version(request, db, with_package, build_state):
    with db.begin():
        db.execute(
            "INSERT INTO versions(package, version) "
            "VALUES (%s, %s)", build_state.package, build_state.version)
    return (build_state.package, build_state.version)


@pytest.fixture()
def with_build(request, db, with_package_version, build_state):
    with db.begin():
        build_id = db.execute(
            "INSERT INTO builds"
            "(package, version, built_by, built_at, duration, status, abi_tag) "
            "VALUES "
            "(%s, %s, %s, TIMESTAMP '2018-01-01 00:00:00', %s, true, %s) "
            "RETURNING (build_id)",
            build_state.package,
            build_state.version,
            build_state.slave_id,
            timedelta(seconds=build_state.duration),
            build_state.abi_tag).first()[0]
        db.execute(
            "INSERT INTO output VALUES (%s, 'Built successfully')", build_id)
    build_state.logged(build_id)
    return build_state


@pytest.fixture()
def with_files(request, db, with_build, file_state, file_state_hacked):
    with db.begin():
        db.execute(
            "INSERT INTO files "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            file_state.filename, with_build.build_id,
            file_state.filesize, file_state.filehash, file_state.package_tag,
            file_state.package_version_tag, file_state.py_version_tag,
            file_state.abi_tag, file_state.platform_tag)
        db.execute(
            "INSERT INTO files "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            file_state_hacked.filename, with_build.build_id,
            file_state_hacked.filesize, file_state_hacked.filehash,
            file_state_hacked.package_tag,
            file_state_hacked.package_version_tag,
            file_state_hacked.py_version_tag, file_state_hacked.abi_tag,
            file_state_hacked.platform_tag)
    return [file_state, file_state_hacked]


@pytest.fixture()
def with_downloads(request, db, with_files, download_state):
    dl = download_state
    with db.begin():
        db.execute(
            "INSERT INTO downloads "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            dl.filename, dl.host, dl.timestamp,
            dl.arch, dl.distro_name, dl.distro_version,
            dl.os_name, dl.os_version,
            dl.py_name, dl.py_version)
        db.execute(
            "INSERT INTO downloads "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            dl.filename, dl.host, dl.timestamp + timedelta(minutes=5),
            dl.arch, dl.distro_name, dl.distro_version,
            dl.os_name, dl.os_version,
            dl.py_name, dl.py_version)


@pytest.fixture(scope='session')
def master_config(request):
    config = mock.Mock()
    config.dsn = 'postgres://{username}:{password}@/{db}'.format(
        username=PIWHEELS_USER,
        password=PIWHEELS_PASS,
        db=PIWHEELS_TESTDB
    )
    config.index_queue = 'inproc://tests-indexes'
    config.status_queue = 'inproc://tests-status'
    config.control_queue = 'inproc://tests-control'
    config.builds_queue = 'inproc://tests-builds'
    config.db_queue = 'inproc://tests-db'
    config.fs_queue = 'inproc://tests-fs'
    config.slave_queue = 'inproc://tests-slave-driver'
    config.file_queue = 'inproc://tests-file-juggler'
    config.import_queue = 'inproc://tests-imports'
    config.log_queue = 'inproc://tests-logger'
    return config


@pytest.fixture(scope='function')
def zmq_context(request):
    context = zmq.Context.instance()
    def fin():
        context.destroy(linger=1000)
        context.term()
    request.addfinalizer(fin)
    return context


@pytest.fixture(scope='function')
def master_control_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PULL)
    def fin():
        queue.close()
    request.addfinalizer(fin)
    queue.hwm = 10
    queue.bind(master_config.control_queue)
    return queue


@pytest.fixture(scope='function')
def master_status_queue(request, zmq_context):
    queue = zmq_context.socket(zmq.PULL)
    def fin():
        queue.close()
    request.addfinalizer(fin)
    queue.hwm = 10
    queue.bind(const.INT_STATUS_QUEUE)
    return queue
