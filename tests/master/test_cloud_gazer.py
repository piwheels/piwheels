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

from piwheels import const, protocols, transport
from piwheels.master.cloud_gazer import CloudGazer


UTC = timezone.utc


def dt(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)


@pytest.fixture()
def pypi_proxy(request, zmq_context):
    q = Queue()
    proxy_patcher = mock.patch('xmlrpc.client.ServerProxy')
    proxy_mock = proxy_patcher.start()
    proxy_mock().changelog_since_serial.side_effect = lambda serial: q.get()
    yield q
    proxy_patcher.stop()


@pytest.fixture()
def web_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(transport.PULL, protocol=protocols.the_scribe)
    queue.hwm = 1
    queue.bind(master_config.web_queue)
    yield queue
    queue.close()


@pytest.fixture(scope='function')
def task(request, db_queue, web_queue, master_config):
    task = CloudGazer(master_config)
    yield task
    task.close()
    db_queue.check()


def test_init(pypi_proxy, db_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 1)
    task.once()
    db_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 1


def test_new_pkg(pypi_proxy, db_queue, task, pypi_json):
    assert task.skip_default == ''
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 0)
    task.once()
    db_queue.check()
    pypi_proxy.put([
        ('foo', '0.2', 1531327388, 'create', 0),
        ('foo', '0.2', 1531327388, 'add source file foo-0.2.tar.gz', 1),
    ])
    db_queue.expect('NEWVER', ['foo', '0.2', dt('2018-07-11 16:43:08'), ''])
    db_queue.send('OK', True)
    db_queue.expect('PROJDESC', ['foo', 'some description'])
    db_queue.send('OK', None)
    db_queue.expect('SETPYPI', 1)
    db_queue.send('OK', None)
    task.loop()
    db_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 1


def test_dev_mode(dev_mode, pypi_proxy, db_queue, task, pypi_json):
    assert task.skip_default == 'development mode'
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', set())
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 0)
    task.once()
    db_queue.check()
    pypi_proxy.put([
        ('foo', '0.2', 1531327388, 'create', 0),
        ('foo', '0.2', 1531327388, 'add source file foo-0.2.tar.gz', 1),
    ])
    db_queue.expect('NEWPKG', ['foo', 'development mode'])
    db_queue.send('OK', True)
    db_queue.expect('NEWVER', ['foo', '0.2', dt('2018-07-11 16:43:08'), ''])
    db_queue.send('OK', True)
    db_queue.expect('PROJDESC', ['foo', 'some description'])
    db_queue.send('OK', True)
    db_queue.expect('SETPYPI', 1)
    db_queue.send('OK', None)
    task.loop()
    db_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 1


def test_existing_ver(pypi_proxy, db_queue, task):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', set())
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 0)
    task.once()
    db_queue.check()
    pypi_proxy.put([
        ('foo', '0.2', 1531327388, 'create', 0),
        ('foo', '0.2', 1531327388, 'add cp34 file foo-0.2-cp34-cp34m-manylinux1_x86_64.whl', 1),
    ])
    db_queue.expect('NEWPKG', ['foo', ''])
    db_queue.send('OK', False)
    db_queue.expect('NEWVER', ['foo', '0.2', dt('2018-07-11 16:43:08'), 'binary only'])
    db_queue.send('OK', False)
    db_queue.expect('SETPYPI', 1)
    db_queue.send('OK', None)
    task.loop()
    db_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 1


def test_new_ver(pypi_proxy, db_queue, web_queue, task, pypi_json):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 2)
    task.once()
    db_queue.check()
    pypi_proxy.put([
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add source file bar-1.0.zip', 3),
        ('bar', '1.0', 1531327391, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 4),
        ('bar', '1.0', 1531327392, 'add cp34 file bar-0.1-cp34-cp34-manylinux1_x86_64.whl', 5),
        ('bar', '1.0', 1531327392, 'add cp35 file bar-0.1-cp35-cp35-manylinux1_x86_64.whl', 6),
    ])
    db_queue.expect('NEWPKG', ['bar', ''])
    db_queue.send('OK', True)
    db_queue.expect('NEWVER', ['bar', '1.0', dt('2018-07-11 16:43:09'), ''])
    db_queue.send('OK', True)
    db_queue.expect('PROJDESC', ['bar', 'some description'])
    db_queue.send('OK', True)
    db_queue.expect('SETPYPI', 6)
    db_queue.send('OK', None)
    task.loop()
    db_queue.check()
    assert task.packages == {"foo", "bar"}
    assert task.serial == 6
    assert web_queue.recv_msg() == ('PKGBOTH', 'bar')


def test_remove_ver(pypi_proxy, db_queue, web_queue, task, pypi_json):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 2)
    task.once()
    db_queue.check()
    pypi_proxy.put([
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add source file bar-1.0.zip', 3),
        ('bar', '1.0', 1531327391, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 4),
        ('bar', '1.0', 1531327392, 'remove release', 5),
    ])
    db_queue.expect('NEWPKG', ['bar', ''])
    db_queue.send('OK', True)
    db_queue.expect('NEWVER', ['bar', '1.0', dt('2018-07-11 16:43:09'), ''])
    db_queue.send('OK', True)
    db_queue.expect('PROJDESC', ['bar', 'some description'])
    db_queue.send('OK', True)
    db_queue.expect('SKIPVER', ['bar', '1.0', 'deleted'])
    db_queue.send('OK', True)
    db_queue.expect('SETPYPI', 5)
    db_queue.send('OK', None)
    task.loop()
    db_queue.check()
    assert task.packages == {"foo", "bar"}
    assert task.serial == 5
    assert web_queue.recv_msg() == ('PKGBOTH', 'bar')


def test_remove_pkg(pypi_proxy, db_queue, web_queue, task, pypi_json):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 2)
    task.once()
    db_queue.check()
    pypi_proxy.put([
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add source file bar-1.0.zip', 3),
        ('bar', '1.0', 1531327391, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 4),
        ('bar', None, 1531327392, 'remove package', 5),
    ])
    db_queue.expect('NEWPKG', ['bar', ''])
    db_queue.send('OK', True)
    db_queue.expect('NEWVER', ['bar', '1.0', dt('2018-07-11 16:43:09'), ''])
    db_queue.send('OK', True)
    db_queue.expect('PROJDESC', ['bar', 'some description'])
    db_queue.send('OK', True)
    db_queue.expect('SKIPPKG', ['bar', 'deleted'])
    db_queue.send('OK', True)
    db_queue.expect('SETPYPI', 5)
    db_queue.send('OK', None)
    task.loop()
    db_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 5
    assert web_queue.recv_msg() == ('PKGBOTH', 'bar')


def test_enable_ver(pypi_proxy, db_queue, web_queue, task, pypi_json):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {"foo"})
    db_queue.expect('GETPYPI')
    db_queue.send('OK', 3)
    task.once()
    db_queue.check()
    pypi_proxy.put([
        ('foo', '1.0', 1531327389, 'add py2.py3 file foo-1.0-py2.py3-none-any.whl', 3),
        ('foo', '1.0', 1531327389, 'add cp34 file foo-0.1-cp34-cp34-manylinux1_x86_64.whl', 4),
        ('foo', '1.0', 1531327392, 'add source file foo-1.0.zip', 5),
        ('foo', '1.0', 1531327392, 'add cp35 file foo-0.1-cp35-cp35-manylinux1_x86_64.whl', 6),
    ])
    db_queue.expect('NEWVER', ['foo', '1.0', dt('2018-07-11 16:43:09'), 'binary only'])
    db_queue.send('OK', True)
    db_queue.expect('PROJDESC', ['foo', 'some description'])
    db_queue.send('OK', True)
    db_queue.expect('NEWVER', ['foo', '1.0', dt('2018-07-11 16:43:09'), ''])
    db_queue.send('OK', False)
    db_queue.expect('GETSKIP', ['foo', '1.0'])
    db_queue.send('OK', 'binary only')
    db_queue.expect('SKIPVER', ['foo', '1.0', ''])
    db_queue.send('OK', None)
    db_queue.expect('SETPYPI', 6)
    db_queue.send('OK', None)
    task.loop()
    db_queue.check()
    assert task.packages == {"foo"}
    assert task.serial == 6
    assert web_queue.recv_msg() == ('PKGPROJ', 'foo')
