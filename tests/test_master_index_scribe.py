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


import json
from unittest import mock
from pathlib import Path
from time import time, sleep
from collections import namedtuple
from html.parser import HTMLParser
from threading import Event

import zmq
import pytest
from pkg_resources import resource_listdir

from piwheels.master.index_scribe import IndexScribe


Row = namedtuple('Row', ('filename', 'filehash'))


@pytest.fixture()
def index_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PUSH)
    def fin():
        queue.close()
    request.addfinalizer(fin)
    queue.hwm = 10
    queue.connect(master_config.index_queue)
    return queue


@pytest.fixture()
def task(request, zmq_context, master_config, db_queue):
    task = IndexScribe(master_config)
    def fin():
        task.quit()
        task.join(2)
        if task.is_alive():
            raise RuntimeError('failed to kill seraph task')
    request.addfinalizer(fin)
    return task


def wait_for_file(path, timeout=1):
    # Eurgh ... no built-in efficient file polling in the stdlib?
    start = time()
    while not path.exists():
        sleep(0.01)
        if time() - start > timeout:
            assert False, 'timed out waiting for %s' % path


class ContainsParser(HTMLParser):
    def __init__(self, find_tag, find_attrs):
        super().__init__()
        self.found = False
        self.find_tag = find_tag
        self.find_attrs = set(find_attrs)

    def handle_starttag(self, tag, attrs):
        if tag == self.find_tag and self.find_attrs <= set(attrs):
            self.found = True


def contains_elem(path, tag, attrs):
    parser = ContainsParser(tag, attrs)
    with path.open('r', encoding='utf-8') as f:
        while True:
            chunk = f.read(8192)
            if chunk == '':
                break
            parser.feed(chunk)
            if parser.found:
                return True
    return False


def test_scribe_first_start(db_queue, task, master_config):
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo'}])
    root = Path(master_config.output_path)
    wait_for_file(root / 'simple' / 'index.html')
    assert contains_elem(root / 'simple' / 'index.html', 'a', [('href', 'foo')])
    assert (root / 'simple').exists() and (root / 'simple').is_dir()
    for filename in resource_listdir('piwheels.master.index_scribe', 'static'):
        if filename != 'index.html':
            assert (root / filename).exists() and (root / filename).is_file()


def test_scribe_second_start(db_queue, task, master_config):
    # Make sure stuff still works even when the files and directories already
    # exist
    root = Path(master_config.output_path)
    (root / 'index.html').touch()
    (root / 'simple').mkdir()
    (root / 'simple' / 'index.html').touch()
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo'}])
    wait_for_file(root / 'simple' / 'index.html')
    assert (root / 'simple').exists() and (root / 'simple').is_dir()
    for filename in resource_listdir('piwheels.master.index_scribe', 'static'):
        if filename != 'index.html':
            assert (root / filename).exists() and (root / filename).is_file()


def test_write_root_index_fails(master_control_queue, db_queue, task,
                                index_queue):
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', None])
    # Check the task died and killed the master on the way out
    task.join(1)
    assert not task.is_alive()
    assert master_control_queue.recv_pyobj() == ['QUIT']


def test_bad_request(db_queue, task, index_queue, master_config):
    e = Event()
    task.logger = mock.Mock()
    task.logger.error.side_effect = lambda *args: e.set()
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo'}])
    index_queue.send_pyobj(['FOO'])
    assert e.wait(1)
    assert task.logger.error.call_args('invalid index_queue message: %s', 'FOO')


def test_write_homepage(db_queue, task, index_queue, master_config):
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo'}])
    index_queue.send_pyobj(['HOME', {
        'packages_built': 123,
        'files_count': 234,
        'downloads_last_month': 345
    }])
    root = Path(master_config.output_path)
    wait_for_file(root / 'index.html')


def test_write_homepage_fails(master_control_queue, db_queue, task,
                              index_queue):
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo'}])
    index_queue.send_pyobj(['HOME', {}])
    # Check the task died and killed the master on the way out
    task.join(1)
    assert not task.is_alive()
    assert master_control_queue.recv_pyobj() == ['QUIT']


def test_write_pkg_index(db_queue, task, index_queue, master_config):
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo'}])
    index_queue.send_pyobj(['PKG', 'foo'])
    assert db_queue.recv_pyobj() == ['PKGFILES', 'foo']
    db_queue.send_pyobj(['OK', [
        Row('foo-0.1-cp34-cp34m-linux_armv7l.whl', '123456123456'),
        Row('foo-0.1-cp34-cp34m-linux_armv6l.whl', '123456123456'),
    ]])
    root = Path(master_config.output_path)
    index = root / 'simple' / 'foo' / 'index.html'
    wait_for_file(index)
    assert contains_elem(
        index, 'a', [('href', 'foo-0.1-cp34-cp34m-linux_armv7l.whl#sha256=123456123456')]
    )
    assert contains_elem(
        index, 'a', [('href', 'foo-0.1-cp34-cp34m-linux_armv7l.whl#sha256=123456123456')]
    )


def test_write_pkg_index_fails(master_control_queue, db_queue, task,
                               index_queue):
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo'}])
    index_queue.send_pyobj(['PKG', 'foo'])
    assert db_queue.recv_pyobj() == ['PKGFILES', 'foo']
    db_queue.send_pyobj(['OK', [
        # Send an ordinary tuple (method expects rows with attributes named
        # after columns)
        ('foo-0.1-cp34-cp34m-linux_armv7l.whl', '123456123456'),
    ]])
    # Check the task died and killed the master on the way out
    task.join(1)
    assert not task.is_alive()
    assert master_control_queue.recv_pyobj() == ['QUIT']


def test_write_new_pkg_index(db_queue, task, index_queue, master_config):
    root = Path(master_config.output_path)
    root_index = root / 'simple' / 'index.html'
    pkg_index = root / 'simple' / 'bar' / 'index.html'
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo'}])
    wait_for_file(root_index)
    root_index.unlink()
    index_queue.send_pyobj(['PKG', 'bar'])
    assert db_queue.recv_pyobj() == ['PKGFILES', 'bar']
    db_queue.send_pyobj(['OK', [
        Row('bar-1.0-cp34-cp34m-linux_armv7l.whl', '123456abcdef'),
        Row('bar-1.0-cp34-cp34m-linux_armv6l.whl', '123456abcdef'),
    ]])
    wait_for_file(root_index)
    assert contains_elem(root_index, 'a', [('href', 'bar')])
    wait_for_file(pkg_index)
    assert contains_elem(
        pkg_index, 'a', [('href', 'bar-1.0-cp34-cp34m-linux_armv7l.whl#sha256=123456abcdef')]
    )
    assert contains_elem(
        pkg_index, 'a', [('href', 'bar-1.0-cp34-cp34m-linux_armv7l.whl#sha256=123456abcdef')]
    )


def test_write_search_index(db_queue, task, index_queue, master_config):
    root = Path(master_config.output_path)
    packages_json = root / 'packages.json'
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo', 'bar'}])
    search_index = [
        ('foo', 10),
        ('bar', 1),
    ]
    index_queue.send_pyobj(['SEARCH', search_index])
    wait_for_file(packages_json)
    assert json.load(packages_json.open('r')) == [list(i) for i in search_index]


def test_write_search_index_fails(master_control_queue, db_queue, task,
                                  index_queue):
    task.start()
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {'foo', '\0\0'}])
    search_index = [
        ('foo', 10),
        ('bar', 1 + 2j),  # complex download counts :)
    ]
    index_queue.send_pyobj(['SEARCH', search_index])
    # Check the task died and killed the master on the way out
    task.join(1)
    assert not task.is_alive()
    assert master_control_queue.recv_pyobj() == ['QUIT']
