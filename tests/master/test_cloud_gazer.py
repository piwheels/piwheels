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
from queue import Queue
from datetime import datetime, timezone

from conftest import MockTask
from piwheels import const, protocols, transport
from piwheels.master.cloud_gazer import CloudGazer


UTC = timezone.utc


def dt(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)


@pytest.fixture()
def mock_events(request):
    with mock.patch('piwheels.master.cloud_gazer.PyPIEvents') as pypi_events:
        pypi_events().serial = 0
        source = []
        def events_iter():
            for index, event in enumerate(source, start=pypi_events().serial + 1):
                pypi_events().serial = index
                yield event
        pypi_events().__iter__.side_effect = events_iter
        yield source


@pytest.fixture()
def skip_queue(request, zmq_context, master_config):
    task = MockTask(zmq_context, transport.REP, const.SKIP_QUEUE,
                    reversed(protocols.cloud_gazer))
    yield task
    task.close()


@pytest.fixture(scope='function')
def task(request, db_queue, web_queue, skip_queue, master_config):
    task = CloudGazer(master_config)
    yield task
    task.close()
    db_queue.check()


def test_init(mock_events, db_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 1)
    task.once()
    db_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 1


def test_new_pkg(mock_events, db_queue, web_queue, task):
    assert task.skip_default == ''
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 0)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('foo', None, dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.2', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
    ]
    db_queue.expect('NEWVER', ['foo', '0.2', dt('2018-07-11 16:43:08'), ''])
    db_queue.send('OK', True)
    db_queue.expect('SETDESC', ['foo', 'package foo'])
    db_queue.send('OK', None)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 2)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 2


def test_dev_mode(dev_mode, mock_events, db_queue, web_queue, task):
    assert task.skip_default == 'development mode'
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', set())
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 0)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('foo', None, dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.2', dt('2018-07-11 16:43:08'), 'source', 'package foo'),
    ]
    db_queue.expect('NEWPKG', ['foo', 'development mode', 'package foo'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('NEWVER', ['foo', '0.2', dt('2018-07-11 16:43:08'), ''])
    db_queue.send('OK', True)
    db_queue.expect('SETDESC', ['foo', 'package foo'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 2)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 2


def test_existing_ver(mock_events, db_queue, web_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', set())
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 0)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('foo', None, dt('2018-07-11 16:43:08'), 'create', 'package foo'),
        ('foo', '0.2', dt('2018-07-11 16:43:08'), 'create', 'package foo'),
    ]
    db_queue.expect('NEWPKG', ['foo', '', 'package foo'])
    db_queue.send('OK', False)
    db_queue.expect('SETDESC', ['foo', 'package foo'])
    db_queue.send('OK', None)
    db_queue.expect('NEWVER', ['foo', '0.2', dt('2018-07-11 16:43:08'), 'binary only'])
    db_queue.send('OK', False)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 2)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 2


def test_new_ver(mock_events, db_queue, web_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 2)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('bar', None, dt('2018-07-11 16:43:07'), 'create', 'some description'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'source', 'some description'),
    ]
    db_queue.expect('NEWPKG', ['bar', '', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    db_queue.expect('NEWVER', ['bar', '1.0', dt('2018-07-11 16:43:09'), ''])
    db_queue.send('OK', True)
    db_queue.expect('SETDESC', ['bar', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 4)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo", "bar"}
    assert task.serial == 4


def test_remove_ver(mock_events, db_queue, web_queue, skip_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 2)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('bar', None, dt('2018-07-11 16:43:09'), 'create', 'some description'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'source', 'some description'),
        ('bar', '1.0', dt('2018-07-11 16:43:11'), 'remove', None),
    ]
    db_queue.expect('NEWPKG', ['bar', '', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    db_queue.expect('NEWVER', ['bar', '1.0', dt('2018-07-11 16:43:09'), ''])
    db_queue.send('OK', True)
    db_queue.expect('SETDESC', ['bar', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    db_queue.expect('SKIPVER', ['bar', '1.0', 'deleted'])
    db_queue.send('OK', True)
    web_queue.expect('DELVER', ['bar', '1.0'])
    web_queue.send('DONE')
    skip_queue.expect('DELVER', ['bar', '1.0'])
    skip_queue.send('OK')
    db_queue.expect('DELVER', ['bar', '1.0'])
    db_queue.send('OK', None)
    db_queue.expect('SETPYPI', 5)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo", "bar"}
    assert task.serial == 5


def test_remove_pkg(mock_events, db_queue, web_queue, skip_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 2)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('bar', None, dt('2018-07-11 16:43:09'), 'create', 'some description'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'source', 'some description'),
        ('bar', None, dt('2018-07-11 16:43:11'), 'remove', None),
    ]
    db_queue.expect('NEWPKG', ['bar', '', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    db_queue.expect('NEWVER', ['bar', '1.0', dt('2018-07-11 16:43:09'), ''])
    db_queue.send('OK', True)
    db_queue.expect('SETDESC', ['bar', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    db_queue.expect('SKIPPKG', ['bar', 'deleted'])
    db_queue.send('OK', True)
    web_queue.expect('DELPKG', 'bar')
    web_queue.send('DONE')
    skip_queue.expect('DELPKG', 'bar')
    skip_queue.send('OK')
    db_queue.expect('DELPKG', 'bar')
    db_queue.send('OK', None)
    db_queue.expect('SETPYPI', 5)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 5


def test_remove_pkg_no_insert(mock_events, db_queue, web_queue, skip_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 3)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('bar', None, dt('2018-07-11 16:43:09'), 'remove', None),
    ]
    db_queue.expect('SKIPPKG', ['bar', 'deleted'])
    db_queue.send('OK', True)
    web_queue.expect('DELPKG', 'bar')
    web_queue.send('DONE')
    skip_queue.expect('DELPKG', 'bar')
    skip_queue.send('OK')
    db_queue.expect('DELPKG', 'bar')
    db_queue.send('OK', None)
    db_queue.expect('SETPYPI', 4)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 4


def test_remove_pkg_before_insert(mock_events, db_queue, web_queue, skip_queue,
                                  task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 2)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('bar', None, dt('2018-07-11 16:43:08'), 'remove', None),
        ('bar', None, dt('2018-07-11 16:43:09'), 'create', 'some description'),
        ('bar', '1.0', dt('2018-07-11 16:43:09'), 'source', 'some description'),
    ]
    db_queue.expect('SKIPPKG', ['bar', 'deleted'])
    db_queue.send('OK', True)
    web_queue.expect('DELPKG', 'bar')
    web_queue.send('DONE')
    skip_queue.expect('DELPKG', 'bar')
    skip_queue.send('OK')
    db_queue.expect('DELPKG', 'bar')
    db_queue.send('OK', None)
    db_queue.expect('NEWPKG', ['bar', '', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    db_queue.expect('NEWVER', ['bar', '1.0', dt('2018-07-11 16:43:09'), ''])
    db_queue.send('OK', True)
    db_queue.expect('SETDESC', ['bar', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'bar')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 5)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo", "bar"}
    assert task.serial == 5


def test_enable_ver(mock_events, db_queue, web_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 3)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('foo', '1.0', dt('2018-07-11 16:43:09'), 'create', 'some description'),
        ('foo', '1.0', dt('2018-07-11 16:43:11'), 'source', 'some description'),
    ]
    db_queue.expect('NEWVER', ['foo', '1.0', dt('2018-07-11 16:43:09'), 'binary only'])
    db_queue.send('OK', True)
    db_queue.expect('SETDESC', ['foo', 'some description'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('NEWVER', ['foo', '1.0', dt('2018-07-11 16:43:11'), ''])
    db_queue.send('OK', False)
    db_queue.expect('GETSKIP', ['foo', '1.0'])
    db_queue.send('OK', 'binary only')
    db_queue.expect('SKIPVER', ['foo', '1.0', ''])
    db_queue.send('OK', None)
    web_queue.expect('PROJECT', 'foo')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 5)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 5


def test_yank_ver(mock_events, db_queue, web_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 3)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('foo', '1.0', dt('2018-07-11 16:43:11'), 'yank', None),
    ]
    db_queue.expect('YANKVER', ['foo', '1.0'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 4)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 4


def test_unyank_ver(mock_events, db_queue, web_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 3)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('foo', '1.0', dt('2018-07-11 16:43:11'), 'unyank', None),
    ]
    db_queue.expect('UNYANKVER', ['foo', '1.0'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 4)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 4


def test_yank_unyank_ver(mock_events, db_queue, web_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 3)
    task.once()
    db_queue.check()
    mock_events[:] = [
        ('foo', '1.0', dt('2018-07-11 16:43:11'), 'yank', None),
        ('foo', '1.0', dt('2018-07-11 16:43:12'), 'unyank', None),
    ]
    db_queue.expect('YANKVER', ['foo', '1.0'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('UNYANKVER', ['foo', '1.0'])
    db_queue.send('OK', True)
    web_queue.expect('BOTH', 'foo')
    web_queue.send('DONE')
    db_queue.expect('SETPYPI', 5)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()
    web_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 5
