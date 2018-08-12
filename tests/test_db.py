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

import pytest

from piwheels.master.db import *


def test_init(master_config, db_schema):
    db = Database(master_config.dsn)


def test_init_wrong_version(master_config, db_schema):
    conn = db_schema
    with conn.begin():
        conn.execute("UPDATE configuration SET version = '0.0'")
    with pytest.raises(RuntimeError):
        Database(master_config.dsn)


def test_add_new_package(master_config, db_schema):
    conn = db_schema
    with conn.begin():
        assert conn.execute("SELECT * FROM packages").first() is None
    db = Database(master_config.dsn)
    assert db.add_new_package('foo')
    with conn.begin():
        assert conn.execute("SELECT COUNT(*) FROM packages").first()[0] == 1
        assert conn.execute("SELECT package FROM packages").first() == ('foo',)
    assert not db.add_new_package('foo')
    with conn.begin():
        assert conn.execute("SELECT COUNT(*) FROM packages").first()[0] == 1
        assert conn.execute("SELECT package FROM packages").first() == ('foo',)


def test_add_new_package_version(master_config, db_schema):
    conn = db_schema
    with conn.begin():
        assert conn.execute("SELECT * FROM versions").first() is None
    db = Database(master_config.dsn)
    db.add_new_package('foo')
    assert db.add_new_package_version('foo', '0.1')
    with conn.begin():
        assert conn.execute(
            "SELECT COUNT(*) FROM versions").first()[0] == 1
        assert conn.execute(
            "SELECT package, version FROM versions").first() == ('foo', '0.1')
    assert not db.add_new_package_version('foo', '0.1')
    with conn.begin():
        assert conn.execute(
            "SELECT COUNT(*) FROM versions").first()[0] == 1
        assert conn.execute(
            "SELECT package, version FROM versions").first() == ('foo', '0.1')


def test_skip_package(master_config, db_schema):
    conn = db_schema
    with conn.begin():
        assert conn.execute("SELECT * FROM packages").first() is None
    db = Database(master_config.dsn)
    db.add_new_package('foo')
    with conn.begin():
        assert conn.execute(
            "SELECT skip FROM packages "
            "WHERE package = 'foo'").first() == (False,)
    db.skip_package('foo')
    with conn.begin():
        assert conn.execute(
            "SELECT skip FROM packages "
            "WHERE package = 'foo'").first() == (True,)


def test_skip_package_version(master_config, db_schema):
    conn = db_schema
    with conn.begin():
        assert conn.execute("SELECT * FROM packages").first() is None
    db = Database(master_config.dsn)
    db.add_new_package('foo')
    db.add_new_package_version('foo', 0.1)
    with conn.begin():
        assert conn.execute(
            "SELECT skip FROM versions "
            "WHERE package = 'foo' "
            "AND version = '0.1'").first() == (False,)
    db.skip_package_version('foo', '0.1')
    with conn.begin():
        assert conn.execute(
            "SELECT skip FROM packages "
            "WHERE package = 'foo'").first() == (False,)
        assert conn.execute(
            "SELECT skip FROM versions "
            "WHERE package = 'foo' "
            "AND version = '0.1'").first() == (True,)

