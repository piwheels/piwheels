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
from datetime import datetime

import pytest

from piwheels.master.db import Database


@pytest.fixture()
def db_intf(request, master_config, with_schema):
    return Database(master_config.dsn)


def test_init(master_config, db, with_schema):
    Database(master_config.dsn)


def test_init_wrong_version(master_config, db, with_schema):
    with db.begin():
        db.execute("UPDATE configuration SET version = '0.0'")
    with pytest.raises(RuntimeError):
        Database(master_config.dsn)


def test_add_new_package(db_intf, db, with_schema):
    with db.begin():
        assert db.execute("SELECT * FROM packages").first() is None
    assert db_intf.add_new_package('foo')
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM packages").first() == (1, )
        assert db.execute("SELECT package FROM packages").first() == ('foo',)
    assert not db_intf.add_new_package('foo')
    with db.begin():
        assert db.execute("SELECT COUNT(*) FROM packages").first() == (1, )
        assert db.execute("SELECT package FROM packages").first() == ('foo',)


def test_add_new_package_version(db_intf, db, with_package):
    with db.begin():
        assert db.execute("SELECT * FROM versions").first() is None
    assert db_intf.add_new_package_version(with_package, '0.1')
    with db.begin():
        assert db.execute(
            "SELECT COUNT(*) FROM versions").first() == (1,)
        assert db.execute(
            "SELECT package, version "
            "FROM versions").first() == (with_package, '0.1')
    assert not db_intf.add_new_package_version(with_package, '0.1')
    with db.begin():
        assert db.execute(
            "SELECT COUNT(*) FROM versions").first() == (1,)
        assert db.execute(
            "SELECT package, version "
            "FROM versions").first() == (with_package, '0.1')


def test_skip_package(db_intf, db, with_package):
    with db.begin():
        assert db.execute(
            "SELECT skip FROM packages "
            "WHERE package = 'foo'").first() == (False,)
    db_intf.skip_package('foo')
    with db.begin():
        assert db.execute(
            "SELECT skip FROM packages "
            "WHERE package = 'foo'").first() == (True,)


def test_skip_package_version(db_intf, db, with_package_version):
    with db.begin():
        assert db.execute(
            "SELECT skip FROM versions "
            "WHERE package = 'foo' "
            "AND version = '0.1'").first() == (False,)
    db_intf.skip_package_version('foo', '0.1')
    with db.begin():
        assert db.execute(
            "SELECT skip FROM packages "
            "WHERE package = 'foo'").first() == (False,)
        assert db.execute(
            "SELECT skip FROM versions "
            "WHERE package = 'foo' "
            "AND version = '0.1'").first() == (True,)


def test_test_package_version(db_intf, db, with_package):
    assert not db_intf.test_package_version(with_package, '0.1')
    db_intf.add_new_package_version(with_package, '0.1')
    assert db_intf.test_package_version(with_package, '0.1')


def test_log_download(db_intf, db, with_files, download_state):
    assert db.execute(
        "SELECT COUNT(*) FROM downloads").first() == (0,)
    db_intf.log_download(download_state)
    assert db.execute(
        "SELECT COUNT(*) FROM downloads").first() == (1,)
    assert db.execute(
        "SELECT filename FROM downloads").first() == (download_state.filename,)
