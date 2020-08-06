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


from unittest import mock
from datetime import datetime, timedelta, timezone
from operator import itemgetter

import pytest

from piwheels.master.db import Database, RewritePendingRow


UTC = timezone.utc


@pytest.fixture()
def db_intf(request, master_config, with_schema):
    intf = Database(master_config.dsn)
    def fin():
        intf._conn.close()
    request.addfinalizer(fin)
    return intf


def test_init(master_config, db, with_schema):
    try:
        intf = Database(master_config.dsn)
    finally:
        intf._conn.close()


def test_init_wrong_version(master_config, db, with_schema):
    with db.begin():
        db.execute("UPDATE configuration SET version = '0.0'")
    with pytest.raises(RuntimeError):
        Database(master_config.dsn)


def test_add_new_package(db_intf, db, with_schema):
    assert db.execute("SELECT * FROM packages").first() is None
    assert db_intf.add_new_package('foo')
    assert db.execute("SELECT COUNT(*) FROM packages").first() == (1, )
    assert db.execute("SELECT package, skip FROM packages").first() == ('foo', '')
    assert not db_intf.add_new_package('foo')
    assert db.execute("SELECT COUNT(*) FROM packages").first() == (1, )
    assert db.execute("SELECT package FROM packages").first() == ('foo',)
    assert db_intf.add_new_package('bar', 'skipped')
    assert db.execute("SELECT COUNT(*) FROM packages").first() == (2, )
    assert db.execute("SELECT package, skip FROM packages "
                      "WHERE package = 'bar'").first() == ('bar', 'skipped')


def test_add_new_package_version(db_intf, db, with_package):
    assert db.execute("SELECT * FROM versions").first() is None
    assert db_intf.add_new_package_version(with_package, '0.1')
    assert db.execute(
        "SELECT COUNT(*) FROM versions").first() == (1,)
    assert db.execute(
        "SELECT package, version "
        "FROM versions").first() == (with_package, '0.1')
    assert not db_intf.add_new_package_version(with_package, '0.1')
    assert db.execute(
        "SELECT COUNT(*) FROM versions").first() == (1,)
    assert db.execute(
        "SELECT package, version "
        "FROM versions").first() == (with_package, '0.1')


def test_get_package_description(db_intf, db, with_package):
    assert db_intf.get_package_description(with_package) == ''
    db_intf.add_new_package('bar', description='blah blah')
    assert db_intf.get_package_description('bar') == 'blah blah'


def test_set_package_description(db_intf, db, with_package):
    assert db.execute(
        "SELECT description FROM packages "
        "WHERE package = 'foo'").first() == ('',)
    db_intf.set_package_description(with_package, 'a package')
    assert db.execute(
        "SELECT description FROM packages "
        "WHERE package = 'foo'").first() == ('a package',)


def test_skip_package(db_intf, db, with_package):
    assert db.execute(
        "SELECT skip FROM packages "
        "WHERE package = 'foo'").first() == ('',)
    db_intf.skip_package('foo', 'manual override')
    assert db.execute(
        "SELECT skip FROM packages "
        "WHERE package = 'foo'").first() == ('manual override',)


def test_skip_package_version(db_intf, db, with_package_version):
    assert db.execute(
        "SELECT skip FROM versions "
        "WHERE package = 'foo' "
        "AND version = '0.1'").first() == ('',)
    db_intf.skip_package_version('foo', '0.1', 'binary only')
    assert db.execute(
        "SELECT skip FROM packages "
        "WHERE package = 'foo'").first() == ('',)
    assert db.execute(
        "SELECT skip FROM versions "
        "WHERE package = 'foo' "
        "AND version = '0.1'").first() == ('binary only',)


def test_delete_package(db_intf, db, with_package):
    assert db.execute(
        "SELECT count(*) FROM packages "
        "WHERE package = 'foo'").first() == (1,)
    db_intf.delete_package('foo')
    assert db.execute(
        "SELECT count(*) FROM packages "
        "WHERE package = 'foo'").first() == (0,)


def test_delete_version(db_intf, db, with_package_version):
    assert db.execute(
        "SELECT count(*) FROM versions "
        "WHERE package = 'foo' AND version = '0.1'").first() == (1,)
    db_intf.delete_version('foo', '0.1')
    assert db.execute(
        "SELECT count(*) FROM versions "
        "WHERE package = 'foo' AND version = '0.1'").first() == (0,)


def test_yank_version(db_intf, db, with_package_version):
    assert db.execute(
        "SELECT yanked FROM versions "
        "WHERE package = 'foo' AND version = '0.1'").first() == (False,)
    db_intf.yank_version('foo', '0.1')
    assert db.execute(
        "SELECT yanked FROM versions "
        "WHERE package = 'foo' AND version = '0.1'").first() == (True,)


def test_unyank_version(db_intf, db, with_package_version):
    db_intf.yank_version('foo', '0.1')
    assert db.execute(
        "SELECT yanked FROM versions "
        "WHERE package = 'foo' AND version = '0.1'").first() == (True,)
    db_intf.unyank_version('foo', '0.1')
    assert db.execute(
        "SELECT yanked FROM versions "
        "WHERE package = 'foo' AND version = '0.1'").first() == (False,)


def test_test_package(db_intf, db, with_build_abis):
    assert not db_intf.test_package('foo')
    db_intf.add_new_package('foo')
    assert db_intf.test_package('foo')


def test_package_marked_deleted(db_intf, db, with_package):
    assert not db_intf.package_marked_deleted(with_package)
    db_intf.skip_package(with_package, 'deleted')
    assert db_intf.package_marked_deleted(with_package)


def test_test_package_version(db_intf, db, with_package):
    assert not db_intf.test_package_version(with_package, '0.1')
    db_intf.add_new_package_version(with_package, '0.1')
    assert db_intf.test_package_version(with_package, '0.1')


def test_get_versions_deleted(db_intf, db, with_package_version):
    assert not db_intf.get_versions_deleted('foo')
    db_intf.skip_package_version('foo', '0.1', 'deleted')
    assert db_intf.get_versions_deleted('foo') == {'0.1'}


def test_log_download(db_intf, db, with_files, download_state):
    assert db.execute(
        "SELECT COUNT(*) FROM downloads").first() == (0,)
    db_intf.log_download(download_state)
    assert db.execute(
        "SELECT COUNT(*) FROM downloads").first() == (1,)
    assert db.execute(
        "SELECT filename FROM downloads").first() == (download_state.filename,)


def test_log_search(db_intf, db, with_files, search_state):
    assert db.execute(
        "SELECT COUNT(*) FROM searches").first() == (0,)
    db_intf.log_search(search_state)
    assert db.execute(
        "SELECT COUNT(*) FROM searches").first() == (1,)
    assert db.execute(
        "SELECT package FROM searches").first() == (search_state.package,)


def test_log_project_page_hit(db_intf, db, with_files, project_state):
    assert db.execute(
        "SELECT COUNT(*) FROM project_page_hits").first() == (0,)
    db_intf.log_project(project_state)
    assert db.execute(
        "SELECT COUNT(*) FROM project_page_hits").first() == (1,)
    assert db.execute(
        "SELECT package FROM project_page_hits").first() == (project_state.package,)


def test_log_project_json_download(db_intf, db, with_files, json_state):
    assert db.execute(
        "SELECT COUNT(*) FROM project_json_downloads").first() == (0,)
    db_intf.log_json(json_state)
    assert db.execute(
        "SELECT COUNT(*) FROM project_json_downloads").first() == (1,)
    assert db.execute(
        "SELECT package FROM project_json_downloads").first() == (json_state.package,)


def test_log_web_page_hit(db_intf, db, with_files, page_state):
    assert db.execute(
        "SELECT COUNT(*) FROM web_page_hits").first() == (0,)
    db_intf.log_page(page_state)
    assert db.execute(
        "SELECT COUNT(*) FROM web_page_hits").first() == (1,)
    assert db.execute(
        "SELECT page FROM web_page_hits").first() == (page_state.page,)


def test_log_build(db_intf, db, with_package_version, build_state):
    for file_state in build_state.files.values():
        break
    assert db.execute(
        "SELECT COUNT(*) FROM builds").first() == (0,)
    assert db.execute(
        "SELECT COUNT(*) FROM output").first() == (0,)
    assert db.execute(
        "SELECT COUNT(*) FROM files").first() == (0,)
    db_intf.log_build(build_state)
    assert db.execute(
        "SELECT COUNT(*) FROM builds").first() == (1,)
    assert db.execute(
        "SELECT COUNT(*) FROM output").first() == (1,)
    assert db.execute(
        "SELECT COUNT(*) FROM files").first() == (len(build_state.files),)
    assert db.execute(
        "SELECT build_id, package, version "
        "FROM builds").first() == (
            build_state.build_id,
            build_state.package,
            build_state.version)
    assert db.execute(
        "SELECT build_id, output FROM output").first() == (
            build_state.build_id,
            build_state.output)
    assert db.execute(
        "SELECT build_id, filename, filesize, filehash "
        "FROM files "
        "WHERE filename = %s", file_state.filename).first() == (
            build_state.build_id,
            file_state.filename,
            file_state.filesize,
            file_state.filehash)


def test_log_build_failed(db_intf, db, with_package_version, build_state):
    build_state._status = False
    build_state._files = {}
    build_state._output = 'Build failed'
    assert db.execute(
        "SELECT COUNT(*) FROM builds").first() == (0,)
    assert db.execute(
        "SELECT COUNT(*) FROM output").first() == (0,)
    assert db.execute(
        "SELECT COUNT(*) FROM files").first() == (0,)
    db_intf.log_build(build_state)
    assert db.execute(
        "SELECT COUNT(*) FROM builds").first() == (1,)
    assert db.execute(
        "SELECT COUNT(*) FROM output").first() == (1,)
    assert db.execute(
        "SELECT COUNT(*) FROM files").first() == (0,)
    assert db.execute(
        "SELECT build_id, package, version "
        "FROM builds").first() == (
            build_state.build_id,
            build_state.package,
            build_state.version)
    assert db.execute(
        "SELECT build_id, output FROM output").first() == (
            build_state.build_id,
            build_state.output)


def test_get_build_abis(db_intf, with_build_abis):
    assert db_intf.get_build_abis() == with_build_abis


def test_get_pypi_serial(db_intf, with_schema):
    assert db_intf.get_pypi_serial() == 0


def test_set_pypi_serial(db_intf, with_schema):
    assert db_intf.get_pypi_serial() == 0
    db_intf.set_pypi_serial(50000)
    assert db_intf.get_pypi_serial() == 50000


def test_get_all_packages(db_intf, with_package):
    assert db_intf.get_all_packages() == {'foo'}


def test_get_all_package_versions(db_intf, with_package_version):
    assert db_intf.get_all_package_versions() == {('foo', '0.1')}


def test_get_build_queue_full(db_intf, with_package_version):
    assert db_intf.get_build_queue() == {'cp34m': [('foo', '0.1')]}


def test_get_build_queue_partial(db_intf, with_build):
    assert db_intf.get_build_queue() == {'cp35m': [('foo', '0.1')]}


def test_get_statistics(db_intf, with_files):
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
    assert db_intf.get_statistics() == expected


@pytest.mark.xfail(reason="downloads_recent view needs fixing")
def test_get_downloads_recent(db_intf, with_downloads):
    assert db_intf.get_downloads_recent() == {'foo': 0}


def test_get_package_files(db_intf, with_files):
    assert db_intf.get_package_files('foo') == {
        s.filename: s.filehash
        for s in with_files
    }


def test_get_version_files(db_intf, with_files):
    assert db_intf.get_version_files('foo', '0.1') == {
        s.filename for s in with_files
    }


def test_get_version_skip(db_intf, with_package_version):
    assert db_intf.get_version_skip('foo', '0.1') == ''


def test_get_project_versions(db_intf, with_files):
    assert list(db_intf.get_project_versions('foo')) == [
        ('0.1', '', 'cp34m', '', False),
    ]


def test_get_project_files(db_intf, with_files, build_state_hacked):
    assert sorted(db_intf.get_project_files('foo'), key=itemgetter(2)) == sorted([
        ('0.1', 'cp34m', f.filename, f.filesize, f.filehash, False)
        for f in build_state_hacked.files.values()
    ], key=itemgetter(2))


def test_get_file_apt_dependencies(db_intf, with_deps):
    assert db_intf.get_file_apt_dependencies('foo-0.1-cp34-cp34m-linux_armv7l.whl') == {
        'libfoo4',
    }
    assert db_intf.get_file_apt_dependencies('foo-0.1-cp35-cp35m-linux_armv7l.whl') == {
        'libfoo5',
    }


def test_delete_build(db_intf, db, with_files, build_state_hacked):
    assert db.execute(
        "SELECT COUNT(*) FROM builds").first() == (1,)
    assert db.execute(
        "SELECT COUNT(*) FROM output").first() == (1,)
    assert db.execute(
        "SELECT COUNT(*) FROM files").first() == (len(build_state_hacked.files),)
    db_intf.delete_build('foo', '0.1')
    assert db.execute(
        "SELECT COUNT(*) FROM builds").first() == (0,)
    assert db.execute(
        "SELECT COUNT(*) FROM output").first() == (0,)
    assert db.execute(
        "SELECT COUNT(*) FROM files").first() == (0,)


def test_store_rewrites_pending(db_intf, db, with_package):
    state = [
        RewritePendingRow('foo', datetime(2001, 1, 1, 12, 34, 56, tzinfo=UTC), 'PROJECT'),
    ]
    assert db.execute(
        "SELECT COUNT(*) FROM rewrites_pending").first() == (0,)
    db_intf.save_rewrites_pending(state)
    assert db.execute(
        "SELECT COUNT(*) FROM rewrites_pending").first() == (1,)
    assert db_intf.load_rewrites_pending() == state
