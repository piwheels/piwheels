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
import logging
from unittest import mock
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Thread, Event
from time import sleep

import pytest
from sqlalchemy import create_engine, text
from voluptuous import Schema, ExactSequence, Extra, Any

from piwheels import const, transport, protocols
from piwheels.states import (
    BuildState, FileState, DownloadState, SearchState, ProjectState, JSONState,
    PageState
)
from piwheels.protocols import NoData
from piwheels.initdb import get_script, parse_statements
from piwheels.master.the_oracle import TheOracle
from piwheels.master.seraph import Seraph


UTC = timezone.utc


# The database tests all assume that a database (default: piwheels_test)
# exists, along with two users. An ordinary unprivileged user (default:
# piwheels) which will be used as if it were the piwheels user on the
# production database, and a postgres superuser (default: postgres) which will
# be used to set up structures in the test database and remove them between
# each test. The environment variables listed below can be used to configure
# the names of these entities for use by the test suite.

PIWHEELS_TESTDB = os.environ.get('PIWHEELS_TESTDB', 'piwheels_test')
PIWHEELS_HOST = os.environ.get('PIWHEELS_HOST', '')
PIWHEELS_USER = os.environ.get('PIWHEELS_USER', 'piwheels')
PIWHEELS_PASS = os.environ.get('PIWHEELS_PASS', 'piwheels')
PIWHEELS_SUPERUSER = os.environ.get('PIWHEELS_SUPERUSER', 'postgres')
PIWHEELS_SUPERPASS = os.environ.get('PIWHEELS_SUPERPASS', '')


def find_message(records, **kwargs):
    for record in records:
        if all(getattr(record, key) == value for key, value in kwargs.items()):
            return record


@pytest.fixture()
def file_content(request):
    return b'\x01\x02\x03\x04\x05\x06\x07\x08' * 15432  # 123456 bytes


@pytest.fixture()
def file_state(request, file_content):
    h = sha256()
    h.update(file_content)
    return FileState(
        'foo-0.1-cp34-cp34m-linux_armv7l.whl', len(file_content),
        h.hexdigest().lower(), 'foo', '0.1', 'cp34', 'cp34m', 'linux_armv7l',
        {'apt': ['libc6']})


@pytest.fixture()
def file_state_hacked(request, file_content):
    h = sha256()
    h.update(file_content)
    return FileState(
        'foo-0.1-cp34-cp34m-linux_armv6l.whl', len(file_content),
        h.hexdigest().lower(), 'foo', '0.1', 'cp34', 'cp34m', 'linux_armv6l',
        {'apt': ['libc6']}, transferred=True)


@pytest.fixture()
def file_states_deps(request, file_content):
    h = sha256()
    h.update(file_content)
    return [
        FileState(
            'foo-0.1-cp34-cp34m-linux_armv7l.whl', len(file_content),
            h.hexdigest().lower(), 'foo', '0.1', 'cp34', 'cp34m', 'linux_armv7l',
            {'apt': ['libc', 'libfoo4']}),
        FileState(
            'foo-0.1-cp35-cp35m-linux_armv7l.whl', len(file_content),
            h.hexdigest().lower(), 'foo', '0.1', 'cp35', 'cp35m', 'linux_armv7l',
            {'apt': ['libc', 'libfoo5']}),
    ]


@pytest.fixture()
def file_state_universal(request, file_content):
    h = sha256()
    h.update(file_content)
    return FileState(
        'foo-0.1-py2.py3-none-any.whl', len(file_content),
        h.hexdigest().lower(), 'foo', '0.1', 'py2.py3', 'none', 'any', {})


@pytest.fixture()
def build_state(request, file_state):
    return BuildState(
        1, file_state.package_tag, file_state.package_version_tag,
        file_state.abi_tag, True, timedelta(seconds=300), 'Built successfully',
        {file_state.filename: file_state})


@pytest.fixture()
def build_state_hacked(request, file_state, file_state_hacked):
    return BuildState(
        1, file_state.package_tag, file_state.package_version_tag,
        file_state.abi_tag, True, timedelta(seconds=300), 'Built successfully', {
            file_state.filename: file_state,
            file_state_hacked.filename: file_state_hacked,
        })


@pytest.fixture()
def download_state(request, file_state):
    return DownloadState(
        file_state.filename, '123.4.5.6',
        datetime(2018, 1, 1, 0, 0, 0, tzinfo=UTC), 'armv7l',
        'Raspbian', '9', 'Linux', '', 'CPython', '3.5',
        'pip', None, None)


@pytest.fixture()
def search_state(request):
    return SearchState(
        'markupsafe',
        '2a00:1098:0:80:1000:3b:1:1',
        datetime(2019, 3, 18, 14, 24, 56, tzinfo=UTC),
        'armv7l', 'Raspbian GNU/Linux', '9', 'Linux', '4.14.79-v7+',
        'CPython', '3.5.3', 'pip', '9.0.1', None,
    )


@pytest.fixture()
def project_state(request):
    return ProjectState(
        'pyjokes',
        '2a00:1098:0:82:1000:3b:1:1',
        datetime(2019, 10, 11, 5, 26, 56, tzinfo=UTC),
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:15.0) Gecko/20100101 Firefox/15.0.1',
    )


@pytest.fixture()
def json_state(request):
    return JSONState(
        'gpiozero',
        '2a00:1098:0:80:1000:3b:1:1',
        datetime(2020, 6, 15, 21, 20, 16, tzinfo=UTC),
        'wget',
    )


@pytest.fixture()
def page_state(request):
    return PageState(
        'home',
        '2a00:1098:0:82:1000:3b:1:1',
        datetime(2019, 10, 11, 6, 11, 29, tzinfo=UTC),
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:15.0) Gecko/20100101 Firefox/15.0.1',
    )


@pytest.fixture(scope='session')
def db_url(request):
    return 'postgresql://{username}:{password}@{host}/{db}'.format(
        username=PIWHEELS_USER,
        password=PIWHEELS_PASS,
        host=PIWHEELS_HOST,
        db=PIWHEELS_TESTDB
    )


@pytest.fixture(scope='session')
def db_super_url(request):
    return 'postgresql://{username}:{password}@{host}/{db}'.format(
        username=PIWHEELS_SUPERUSER,
        password=PIWHEELS_SUPERPASS,
        host=PIWHEELS_HOST,
        db=PIWHEELS_TESTDB
    )


@pytest.fixture(scope='session')
def db_engine(request, db_super_url):
    engine = create_engine(db_super_url)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(request, db_engine):
    conn = db_engine.connect()
    conn.execute("SET SESSION synchronous_commit TO OFF")  # it's only a test
    yield conn
    conn.close()


@pytest.fixture(scope='function')
def with_clean_db(request, db):
    with db.begin():
        # Wipe the public schema and re-create it with standard defaults
        db.execute("DROP SCHEMA public CASCADE")
        db.execute("CREATE SCHEMA public AUTHORIZATION postgres")
        db.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
        db.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
    return 'clean'


@pytest.fixture(scope='function')
def with_schema(request, db, with_clean_db):
    with db.begin():
        # Create the piwheels structures from the create_*.sql script
        for stmt in parse_statements(get_script()):
            stmt = stmt.format(username=PIWHEELS_USER, dbname=PIWHEELS_TESTDB)
            db.execute(text(stmt))
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
            build_state.duration,
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
        for tool, dependencies in file_state.dependencies.items():
            for dependency in dependencies:
                db.execute(
                    "INSERT INTO dependencies "
                    "VALUES (%s, %s, %s)",
                    file_state.filename, tool, dependency)
        db.execute(
            "INSERT INTO files "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            file_state_hacked.filename, with_build.build_id,
            file_state_hacked.filesize, file_state_hacked.filehash,
            file_state_hacked.package_tag,
            file_state_hacked.package_version_tag,
            file_state_hacked.py_version_tag, file_state_hacked.abi_tag,
            file_state_hacked.platform_tag)
        for tool, dependencies in file_state_hacked.dependencies.items():
            for dependency in dependencies:
                db.execute(
                    "INSERT INTO dependencies "
                    "VALUES (%s, %s, %s)",
                    file_state_hacked.filename, tool, dependency)
    return [file_state, file_state_hacked]


@pytest.fixture()
def with_preinstalled_apt(request, db, with_build_abis):
    with db.begin():
        db.execute(
            "INSERT INTO preinstalled_apt_packages "
            "VALUES "
            "('cp34m', 'libc'), ('cp35m', 'libc')"
        )


@pytest.fixture()
def with_deps(request, db, file_states_deps, with_build, with_preinstalled_apt):
    with db.begin():
        for file_state in file_states_deps:
            db.execute(
                "INSERT INTO files "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                file_state.filename, with_build.build_id,
                file_state.filesize, file_state.filehash, file_state.package_tag,
                file_state.package_version_tag, file_state.py_version_tag,
                file_state.abi_tag, file_state.platform_tag)
            for tool, dependencies in file_state.dependencies.items():
                for dependency in dependencies:
                    db.execute(
                        "INSERT INTO dependencies "
                        "VALUES (%s, %s, %s)",
                        file_state.filename, tool, dependency)
        return file_states_deps


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


@pytest.fixture(scope='function')
def master_config(request, tmpdir):
    config = mock.Mock()
    config.dev_mode = False
    config.debug = []
    config.pypi_xmlrpc = 'https://pypi.org/pypi'
    config.pypi_simple = 'https://pypi.org/simple'
    config.pypi_json = 'https://pypi.org/pypi'
    config.dsn = 'postgresql://{username}:{password}@{host}/{db}'.format(
        username=PIWHEELS_USER,
        password=PIWHEELS_PASS,
        host=PIWHEELS_HOST,
        db=PIWHEELS_TESTDB
    )
    config.output_path = str(tmpdir)
    config.web_queue = 'inproc://tests-web'
    config.status_queue = 'inproc://tests-status'
    config.control_queue = 'inproc://tests-control'
    config.builds_queue = 'inproc://tests-builds'
    config.db_queue = 'inproc://tests-db'
    config.fs_queue = 'inproc://tests-fs'
    config.slave_queue = 'inproc://tests-slave-driver'
    config.file_queue = 'inproc://tests-file-juggler'
    config.import_queue = 'inproc://tests-imports'
    config.log_queue = 'inproc://tests-logger'
    config.stats_queue = 'inproc://tests-stats'
    return config


@pytest.fixture(scope='function')
def dev_mode(request, master_config):
    master_config.dev_mode = True
    return master_config


@pytest.fixture(scope='session')
def zmq_context(request):
    context = transport.Context()
    old_recv_msg = transport.Socket.recv_msg
    old_recv_addr_msg = transport.Socket.recv_addr_msg
    # Monkey-patch Socket so it times out on receive after 2 seconds, because
    # no receive in the test suite should ever take longer than that
    def recv_msg(self, flags=0):
        if not flags:
            if not self._socket.poll(2000, transport.POLLIN):
                raise IOError('timed out on receive')
        return old_recv_msg(self, flags)
    def recv_addr_msg(self, flags=0):
        if not flags:
            if not self._socket.poll(2000, transport.POLLIN):
                raise IOError('timed out on receive')
        return old_recv_addr_msg(self, flags)
    transport.Socket.recv_msg = recv_msg
    transport.Socket.recv_addr_msg = recv_addr_msg
    yield context
    transport.Socket.recv_msg = old_recv_msg
    transport.Socket.recv_addr_msg = old_recv_addr_msg
    context.close()


@pytest.fixture()
def mock_context(request, zmq_context, tmpdir):
    with mock.patch('piwheels.transport.Context') as inst_mock:
        ctx_mock = mock.Mock(wraps=zmq_context)
        inst_mock.return_value = ctx_mock
        # Neuter the close() method
        ctx_mock.close = mock.Mock()
        # Override the socket() method so connect calls on the result get
        # re-directed to local IPC sockets
        def socket(socket_type, *args, **kwargs):
            sock = zmq_context.socket(socket_type, *args, **kwargs)
            def connect(addr):
                if addr.startswith('tcp://') and addr.endswith(':5555'):
                    addr = 'ipc://' + str(tmpdir.join('slave-driver-queue'))
                elif addr.startswith('tcp://') and addr.endswith(':5556'):
                    addr = 'ipc://' + str(tmpdir.join('file-juggler-queue'))
                return sock.connect(addr)
            sock_mock = mock.Mock(wraps=sock)
            sock_mock.connect = mock.Mock(side_effect=connect)
            return sock_mock
        ctx_mock.socket = mock.Mock(side_effect=socket)
        yield ctx_mock


@pytest.fixture()
def mock_systemd(request):
    with mock.patch('piwheels.systemd._SYSTEMD') as sysd_mock:
        sysd_mock._ready = Event()
        sysd_mock.ready.side_effect = sysd_mock._ready.set
        sysd_mock._reloading = Event()
        sysd_mock.reloading.side_effect = sysd_mock._reloading.set
        yield sysd_mock


@pytest.fixture(scope='function')
def master_control_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.PULL, protocol=protocols.master_control)
    queue.hwm = 1
    queue.bind(master_config.control_queue)
    yield queue
    queue.close()


@pytest.fixture(scope='function')
def master_status_queue(request, zmq_context):
    queue = zmq_context.socket(
        transport.PULL, protocol=reversed(protocols.monitor_stats))
    queue.hwm = 1
    queue.bind(const.INT_STATUS_QUEUE)
    yield queue
    queue.close()


class MockMessage:
    def __init__(self, action, message, data):
        assert action in ('send', 'recv')
        if action == 'recv' and data is NoData:
            data = None
        self.action = action
        self.expect = (message, data)
        self.actual = None

    def __repr__(self):
        if self.actual is None:
            return '%s: %r' % (
                ('TX', 'RX')[self.action == 'recv'], self.expect[0])
        else:
            return '%s: %s' % (
                ('!!', 'OK')[self.action == 'send' or self.expect == self.actual],
                self.actual)


class MockTask(Thread):
    """
    Helper class for testing tasks which interface with REQ/REP sockets. This
    spawns a thread which can be tasked with expecting certain inputs and to
    respond with certain outputs. Typically used to emulate DbClient and
    FsClient to downstream tasks.
    """
    ident = 0
    protocol = protocols.Protocol(recv={
        'QUIT':  NoData,
        'SEND':  ExactSequence([str, Extra]),
        'RECV':  ExactSequence([str, Extra]),
        'TEST':  Any(int, float),
        'RESET': NoData,
    }, send={
        'OK': NoData,
        'ERROR': str,
    })


    def __init__(self, ctx, sock_type, sock_addr, sock_protocol, debug=False):
        address = 'inproc://mock-%d' % MockTask.ident
        super().__init__(target=self.loop, args=(ctx, address))
        MockTask.ident += 1
        self.sock_type = sock_type
        self.sock_addr = sock_addr
        self.control = ctx.socket(
            transport.REQ, protocol=reversed(self.protocol))
        self.control.hwm = 1
        self.control.bind(address)
        self.sock = ctx.socket(sock_type, protocol=sock_protocol)
        self.sock.hwm = 1
        self.sock.bind(sock_addr)
        self.daemon = True
        self.debug = debug
        self.start()

    def __repr__(self):
        return '<MockTask sock_addr="%s">' % self.sock_addr

    def close(self):
        self.control.send_msg('QUIT')
        msg, data = self.control.recv_msg()
        if msg == 'ERROR':
            raise RuntimeError(data)
        self.join(10)
        self.control.close()
        self.control = None
        if self.is_alive():
            raise RuntimeError('failed to terminate mock task %r' % self)
        self.sock.close()
        self.sock = None

    def expect(self, message, data=NoData):
        self.control.send_msg('RECV', (message, data))
        assert self.control.recv_msg()[0] == 'OK'

    def send(self, message, data=NoData):
        self.control.send_msg('SEND', (message, data))
        assert self.control.recv_msg()[0] == 'OK'

    def check(self, timeout=1):
        self.control.send_msg('TEST', timeout)
        msg, data = self.control.recv_msg()
        if msg == 'ERROR':
            assert False, data

    def reset(self):
        self.control.send_msg('RESET')
        assert self.control.recv_msg()[0] == 'OK'

    def loop(self, ctx, address):
        pending = None
        tested = False
        queue = []
        done = []
        socks = {}

        def handle_queue():
            if self.sock in socks and queue[0].action == 'recv':
                queue[0].actual = self.sock.recv_msg()
                if self.debug:
                    print('%s << %s %r' % (
                        self.sock_addr, queue[0].actual[0], queue[0].actual[1]))
                done.append(queue.pop(0))
            elif queue[0].action == 'send':
                if self.debug:
                    print('%s >> %s %r' % (
                        self.sock_addr, queue[0].expect[0], queue[0].expect[1]))
                self.sock.send_msg(*queue[0].expect)
                queue[0].actual = queue[0].expect
                done.append(queue.pop(0))

        control = ctx.socket(transport.REP, protocol=self.protocol)
        control.hwm = 1
        control.connect(address)
        try:
            poller = transport.Poller()
            poller.register(control, transport.POLLIN)
            poller.register(self.sock, transport.POLLIN)
            while True:
                socks = poller.poll(0.1)
                if control in socks:
                    msg, data = control.recv_msg()
                    if msg == 'QUIT':
                        if tested or not queue:
                            control.send_msg('OK')
                        else:
                            control.send_msg(
                                'ERROR', 'forgot to call check()')
                        break
                    elif msg == 'SEND':
                        queue.append(MockMessage('send', *data))
                        control.send_msg('OK')
                    elif msg == 'RECV':
                        queue.append(MockMessage('recv', *data))
                        control.send_msg('OK')
                    elif msg == 'TEST':
                        tested = True
                        if pending is not None:
                            control.send_msg('ERROR', str(pending))
                        else:
                            try:
                                timeout = timedelta(seconds=data)
                                start = datetime.now(tz=UTC)
                                while queue and datetime.now(tz=UTC) - start < timeout:
                                    socks = dict(poller.poll(0.2))
                                    handle_queue()
                                if queue:
                                    assert False, 'Still waiting for %r' % queue[0]
                                else:
                                    assert not poller.poll(0)
                                for item in done:
                                    assert item.expect == item.actual
                            except Exception as exc:
                                control.send_msg('ERROR', str(exc))
                            else:
                                control.send_msg('OK')
                    elif msg == 'RESET':
                        queue = []
                        done = []
                        control.send_msg('OK')
                if queue:
                    try:
                        handle_queue()
                    except Exception as exc:
                        if self.debug:
                            print('%s EXC: %r' % (self.sock_addr, exc))
                        pending = exc
        finally:
            control.close()
            if self.debug:
                print('%s END' % self.sock_addr)


@pytest.fixture()
def db_queue(request, zmq_context, master_config):
    task = MockTask(zmq_context, transport.REP, master_config.db_queue,
                    protocols.the_oracle)
    yield task
    task.close()


@pytest.fixture()
def fs_queue(request, zmq_context, master_config):
    task = MockTask(zmq_context, transport.REP, master_config.fs_queue,
                    protocols.file_juggler_fs)
    yield task
    task.close()


@pytest.fixture()
def web_queue(request, zmq_context, master_config):
    task = MockTask(zmq_context, transport.REP, master_config.web_queue,
                    protocols.the_scribe)
    yield task
    task.close()
