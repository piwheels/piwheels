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

import zmq
import pytest

from conftest import find_message, PIWHEELS_USER, PIWHEELS_SUPERUSER
from piwheels import __version__
from piwheels.initdb import main


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--dsn' in out
    assert '--user' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_bad_db():
    with pytest.raises(RuntimeError) as exc:
        # hopefully you don't have a database named this...
        main(['--dsn', 'postgres:///djskalfjsqklfjdsklfjklsd'])
        assert 'does not exist' in str(exc)


def test_not_a_superuser(db, with_clean_db, db_url):
    with pytest.raises(RuntimeError) as exc:
        main(['--dsn', db_url])
        assert 'not a cluster superuser' in str(exc)


def test_bad_user(db, with_clean_db, db_super_url):
    with pytest.raises(RuntimeError) as exc:
        # hopefully you don't have a user named this...
        main(['--dsn', db_super_url, '--user', 'fdjskalfjdsklfdsjk'])
        assert "doesn't exist as a cluster user" in str(exc)


def test_user_is_superuser(db, with_clean_db, db_super_url):
    with pytest.raises(RuntimeError) as exc:
        # hopefully you don't have a user named this...
        main(['--dsn', db_super_url, '--user', PIWHEELS_SUPERUSER])
        assert "is a cluster superuser; this is not recommended" in str(exc)


def test_new_abort(db, with_clean_db, db_super_url, caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        assert main(['--dsn', db_super_url, '--user', PIWHEELS_USER]) == 0
    assert find_message(caplog.records, 'Database appears to be uninitialized')


def test_current_version(db, with_schema, db_super_url, caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        assert main(['--dsn', db_super_url, '--user', PIWHEELS_USER]) == 0
    assert find_message(caplog.records, 'Database is the current version')


def test_too_ancient(db, with_schema, db_super_url, caplog):
    with db.begin():
        db.execute("DROP TABLE configuration")
        db.execute("DROP VIEW statistics")
        db.execute("DROP TABLE files CASCADE")
    with pytest.raises(RuntimeError) as exc:
        main(['--dsn', db_super_url, '--user', PIWHEELS_USER, '--yes'])
        assert 'Database version older than 0.4' in str(exc)


def test_no_path(db, with_schema, db_super_url, caplog):
    with mock.patch('piwheels.initdb.__version__', 'foo'):
        with pytest.raises(RuntimeError) as exc:
            main(['--dsn', db_super_url, '--user', PIWHEELS_USER, '--yes'])
            assert 'Unable to find upgrade path' in str(exc)
