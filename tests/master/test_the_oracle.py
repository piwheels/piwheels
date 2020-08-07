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


from datetime import datetime, timedelta, timezone
from operator import itemgetter

import cbor2
import pytest

from conftest import PIWHEELS_USER
from piwheels import const, transport
from piwheels.master.db import Database
from piwheels.master.seraph import Seraph
from piwheels.master.the_oracle import TheOracle, DbClient, RewritePendingRow


UTC = timezone.utc


@pytest.fixture(scope='function')
def task(request, zmq_context, master_config, db, with_schema):
    task = TheOracle(master_config)
    task.start()
    yield task
    task.quit()
    task.join(2)
    if task.is_alive():
        raise RuntimeError('failed to kill the_oracle task')
    task.close()


@pytest.fixture(scope='function')
def mock_seraph(request, zmq_context):
    queue = zmq_context.socket(transport.REP)
    queue.hwm = 10
    queue.bind(const.ORACLE_QUEUE)
    yield queue
    queue.close()


@pytest.fixture(scope='function')
def real_seraph(request, zmq_context, master_config):
    task = Seraph(master_config)
    task.front_queue.router_mandatory = True  # don't drop msgs during test
    task.back_queue.router_mandatory = True
    task.start()
    yield task
    task.quit()
    task.join(2)
    if task.is_alive():
        raise RuntimeError('failed to kill seraph task')


@pytest.fixture(scope='function')
def db_client(request, real_seraph, task, master_config):
    client = DbClient(master_config)
    return client


def test_oracle_init(mock_seraph, task):
    assert mock_seraph.recv() == b'READY'


def test_oracle_bad_request(mock_seraph, task):
    assert mock_seraph.recv() == b'READY'
    mock_seraph.send_multipart([b'foo', b'', cbor2.dumps('FOO')])
    address, empty, resp = mock_seraph.recv_multipart()
    assert cbor2.loads(resp) == ['ERROR', repr('')]


def test_oracle_badly_formed_request(mock_seraph, task):
    assert mock_seraph.recv() == b'READY'
    mock_seraph.send_multipart([b'foo', b'', b'', b'', b''])
    address, empty, resp = mock_seraph.recv_multipart()
    assert cbor2.loads(resp) == ['ERROR', repr('')]


def test_database_error(db, with_schema, db_client):
    with db.begin():
        db.execute("REVOKE EXECUTE ON FUNCTION get_statistics() FROM %s" % PIWHEELS_USER)
    with pytest.raises(IOError):
        db_client.get_statistics()


def test_get_all_packages(db, with_package, db_client):
    assert db_client.get_all_packages() == {'foo'}


def test_get_all_package_versions(db, with_package_version, db_client):
    assert db_client.get_all_package_versions() == {('foo', '0.1')}


def test_add_new_package(db, with_schema, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM packages").scalar() == 0
    db_client.add_new_package('foo', '', '')
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM packages").scalar() == 1
        assert db.execute(
            "SELECT package, skip, description FROM packages").first() == ('foo', '', '')
    db_client.add_new_package('bar', 'skipped', 'package bar')
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM packages").scalar() == 2
        assert db.execute(
            "SELECT package, skip, description FROM packages "
            "WHERE package = 'bar'").first() == ('bar', 'skipped', 'package bar')


def test_add_new_package_version(db, with_package, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM versions").scalar() == 0
    db_client.add_new_package_version(
        'foo', '0.1', datetime(2018, 7, 11, 16, 43, 8, tzinfo=UTC))
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM versions").scalar() == 1
        assert db.execute(
            "SELECT package, version, released, skip "
            "FROM versions").first() == (
                'foo', '0.1', datetime(2018, 7, 11, 16, 43, 8), '')


def test_set_package_description(db, with_package, db_client):
    with db.begin():
        assert db.execute(
            "SELECT package, description FROM packages").first() == ('foo', '')
    db_client.set_package_description('foo', 'a package')
    with db.begin():
        assert db.execute(
            "SELECT package, description FROM packages").first() == ('foo', 'a package')


def test_get_package_description(db, with_package, db_client):
    assert db_client.get_package_description('foo') == ''
    with db.begin():
        db.execute(
            "UPDATE packages SET description = 'a package' "
            "WHERE package = 'foo'")
    assert db_client.get_package_description('foo') == 'a package'


def test_skip_package(db, with_package, db_client):
    with db.begin():
        assert db.execute(
            "SELECT package, skip FROM packages").first() == ('foo', '')
    db_client.skip_package('foo', 'manual build')
    with db.begin():
        assert db.execute(
            "SELECT package, skip FROM packages").first() == ('foo', 'manual build')


def test_skip_package_version(db, with_package_version, db_client):
    with db.begin():
        assert db.execute(
            "SELECT package, version, skip "
            "FROM versions").first() == ('foo', '0.1', '')
    db_client.skip_package_version('foo', '0.1', 'binary only')
    with db.begin():
        assert db.execute(
            "SELECT package, version, skip "
            "FROM versions").first() == ('foo', '0.1', 'binary only')


def test_get_version_skip(db, with_package_version, db_client):
    assert not db_client.get_version_skip('foo', '0.1')


def test_get_version_skip(db, with_package_version, db_client):
    assert not db_client.get_version_skip('foo', '0.1')


def test_delete_package(db, with_package, db_client):
    with db.begin():
        assert db.execute(
            "SELECT count(*) "
            "FROM packages "
            "WHERE package = 'foo'").first() == (1,)
    db_client.delete_package('foo')
    with db.begin():
        assert db.execute(
            "SELECT count(*) "
            "FROM packages "
            "WHERE package = 'foo'").first() == (0,)


def test_delete_version(db, with_package_version, db_client):
    with db.begin():
        assert db.execute(
            "SELECT count(*) "
            "FROM versions "
            "WHERE package = 'foo'").first() == (1,)
    db_client.delete_version('foo', '0.1')
    with db.begin():
        assert db.execute(
            "SELECT count(*) "
            "FROM versions "
            "WHERE package = 'foo'").first() == (0,)


def test_yank_version(db, with_package_version, db_client):
    with db.begin():
        assert db.execute(
            "SELECT yanked "
            "FROM versions "
            "WHERE package = 'foo'").first() == (False,)
    db_client.yank_version('foo', '0.1')
    with db.begin():
        assert db.execute(
            "SELECT yanked "
            "FROM versions "
            "WHERE package = 'foo'").first() == (True,)


def test_unyank_version(db, with_package_version, db_client):
    db_client.yank_version('foo', '0.1')
    with db.begin():
        assert db.execute(
            "SELECT yanked "
            "FROM versions "
            "WHERE package = 'foo'").first() == (True,)
    db_client.unyank_version('foo', '0.1')
    with db.begin():
        assert db.execute(
            "SELECT yanked "
            "FROM versions "
            "WHERE package = 'foo'").first() == (False,)


def test_package_marked_deleted(db, with_package, db_client):
    with db.begin():
        assert db.execute(
            "SELECT skip "
            "FROM packages "
            "WHERE package = 'foo'").first() == ('',)
    db_client.skip_package('foo', 'deleted')
    with db.begin():
        assert db.execute(
            "SELECT skip "
            "FROM packages "
            "WHERE package = 'foo'").first() == ('deleted',)


def test_get_versions_deleted(db, with_package_version, db_client):
    with db.begin():
        assert db.execute(
            "SELECT skip "
            "FROM versions "
            "WHERE package = 'foo'").first() == ('',)
    db_client.skip_package_version('foo', '0.1', 'deleted')
    with db.begin():
        assert db.execute(
            "SELECT skip "
            "FROM versions "
            "WHERE package = 'foo'").first() == ('deleted',)


def test_test_package_version(db, with_package_version, db_client):
    assert db_client.test_package_version('foo', '0.1')
    assert not db_client.test_package_version('foo', '0.2')


def test_get_versions_deleted(db, with_package_version, db_client):
    assert db_client.get_versions_deleted('foo') == set()
    with db.begin():
        db.execute(
            "UPDATE versions SET skip = 'deleted' "
            "WHERE package = 'foo' AND version = '0.1'")
    assert db_client.get_versions_deleted('foo') == {'0.1'}


def test_log_download(db, with_files, download_state, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM downloads").scalar() == 0
    db_client.log_download(download_state)
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM downloads").scalar() == 1
        assert db.execute(
            "SELECT filename FROM downloads").scalar() == download_state.filename


def test_log_search(db, with_files, search_state, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM searches").scalar() == 0
    db_client.log_search(search_state)
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM searches").scalar() == 1
        assert db.execute(
            "SELECT package FROM searches").scalar() == search_state.package


def test_log_project_page_hit(db, with_files, project_state, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM project_page_hits").scalar() == 0
    db_client.log_project(project_state)
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM project_page_hits").scalar() == 1
        assert db.execute(
            "SELECT package FROM project_page_hits").scalar() == project_state.package


def test_log_project_json_download(db, with_files, json_state, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM project_json_downloads").scalar() == 0
    db_client.log_json(json_state)
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM project_json_downloads").scalar() == 1
        assert db.execute(
            "SELECT package FROM project_json_downloads").scalar() == json_state.package


def test_log_web_page_hit(db, with_files, page_state, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM web_page_hits").scalar() == 0
    db_client.log_page(page_state)
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM web_page_hits").scalar() == 1
        assert db.execute(
            "SELECT page FROM web_page_hits").scalar() == page_state.page


def test_log_build(db, with_package_version, build_state_hacked, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM builds").scalar() == 0
    db_client.log_build(build_state_hacked)
    assert build_state_hacked.build_id is not None
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM builds").scalar() == 1
        assert db.execute("SELECT COUNT(*) FROM files").scalar() == 2


def test_get_file_apt_dependencies(db, with_files, db_client):
    assert db_client.get_file_apt_dependencies('foo-0.1-cp34-cp34m-linux_armv7l.whl') == {
        'libc6',
    }


def test_get_project_versions(db, with_files, db_client):
    assert db_client.get_project_versions('foo') == [
        ('0.1', '', 'cp34m', '', False),
    ]


def test_get_project_files(db, with_files, build_state_hacked, db_client):
    assert sorted(db_client.get_project_files('foo'), key=itemgetter(2)) == sorted([
        ('0.1', 'cp34m', f.filename, f.filesize, f.filehash, False)
        for f in build_state_hacked.files.values()
    ], key=itemgetter(2))


def test_delete_build(db, with_build, db_client):
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM builds").scalar() == 1
    db_client.delete_build('foo', '0.2')
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM builds").scalar() == 1
    db_client.delete_build('foo', '0.1')
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM builds").scalar() == 0


def test_get_package_files(db, with_files, build_state_hacked, db_client):
    assert db_client.get_package_files('foo') == {
        r.filename: r.filehash
        for r in build_state_hacked.files.values()
    }


def test_get_version_files(db, with_files, build_state_hacked, db_client):
    assert db_client.get_version_files('foo', '0.1') == build_state_hacked.files.keys()


def test_test_package(db, with_package, db_client):
    assert db_client.test_package(with_package)
    assert not db_client.test_package('blah-blah')


def test_package_marked_deleted(db, with_package, db_client):
    assert not db_client.package_marked_deleted(with_package)
    with db.begin():
        db.execute(
            "UPDATE packages SET skip = 'deleted' "
            "WHERE package = 'foo'")
    assert db_client.package_marked_deleted(with_package)


def test_get_build_abis(db, with_build_abis, db_client):
    assert db_client.get_build_abis() == {'cp34m', 'cp35m'}


def test_get_pypi_serial(db, with_schema, db_client):
    assert db_client.get_pypi_serial() == 0


def test_set_pypi_serial(db, with_schema, db_client):
    assert db_client.get_pypi_serial() == 0
    db_client.set_pypi_serial(50000)
    assert db_client.get_pypi_serial() == 50000


def test_get_statistics(db_client, db, with_files):
    expected = {
        'packages_built': 1,
        'builds_last_hour': {'cp34m': 0, 'cp35m': 0},
        'builds_time': timedelta(minutes=5),
        'files_count': 2,
        'builds_size': 123456,
        'new_last_hour': 0,
        'downloads_last_hour': 0,
        'downloads_last_month': 0,
        'downloads_all': 0,
    }
    assert db_client.get_statistics() == expected
    # Run twice to cover caching of Statstics type
    assert db_client.get_statistics() == expected


@pytest.mark.xfail(reason="downloads_recent view needs fixing")
def test_get_downloads_recent(db_client, db, with_downloads):
    assert db_client.get_downloads_recent() == {'foo': 0}


def test_store_rewrites_pending(db_client, db, with_package):
    state = [
        ('foo', datetime(2001, 1, 1, 12, 34, 56, tzinfo=UTC), 'PROJECT'),
    ]
    db_client.save_rewrites_pending(state)
    assert db_client.load_rewrites_pending() == state


def test_bogus_request(db_client, db):
    with pytest.raises(IOError):
        db_client._execute('FOO')
