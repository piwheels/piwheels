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

from piwheels import const
from piwheels.master.the_scribe import TheScribe, AtomicReplaceFile


FilesRow = namedtuple('FilesRow', ('filename', 'filehash'))
ProjVersRow = namedtuple('ProjVersRow', (
    'version', 'skipped', 'builds_succeeded', 'builds_failed'))
ProjFilesRow = namedtuple('ProjFilesRow', (
    'version', 'abi_tag', 'filename', 'filesize', 'filehash'))


@pytest.fixture()
def scribe_queue(request, zmq_context):
    queue = zmq_context.socket(zmq.PUSH)
    queue.hwm = 10
    queue.bind(const.SCRIBE_QUEUE)
    yield queue
    queue.close()


@pytest.fixture()
def task(request, zmq_context, master_config, db_queue, scribe_queue):
    task = TheScribe(master_config)
    yield task
    task.close()


def wait_for_file(path, timeout=1):
    # Eurgh ... no built-in efficient file polling in the stdlib?
    start = time()
    while not path.exists():
        sleep(0.01)
        if time() - start > timeout:
            assert False, 'timed out waiting for %s' % path


class ContainsParser(HTMLParser):
    def __init__(self, find_tag, find_attrs):
        super().__init__(convert_charrefs=True)
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


def test_atomic_write_success(tmpdir):
    with AtomicReplaceFile(str(tmpdir.join('foo'))) as f:
        f.write(b'\x00' * 4096)
        temp_name = f.name
    assert os.path.exists(str(tmpdir.join('foo')))
    assert not os.path.exists(temp_name)


def test_atomic_write_failed(tmpdir):
    with pytest.raises(IOError):
        with AtomicReplaceFile(str(tmpdir.join('foo'))) as f:
            f.write(b'\x00' * 4096)
            temp_name = f.name
            raise IOError("Something went wrong")
        assert not os.path.exists(str(tmpdir.join('foo')))
        assert not os.path.exists(temp_name)


def test_scribe_first_start(db_queue, task, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo'}])
    task.once()
    db_queue.check()
    root = Path(master_config.output_path)
    assert (root / 'simple' / 'index.html').exists()
    assert contains_elem(root / 'simple' / 'index.html', 'a', [('href', 'foo')])
    assert (root / 'simple').exists() and (root / 'simple').is_dir()
    for filename in resource_listdir('piwheels.master.the_scribe', 'static'):
        if filename not in {'index.html', 'project.html', 'stats.html'}:
            assert (root / filename).exists() and (root / filename).is_file()


def test_scribe_second_start(db_queue, task, master_config):
    # Make sure stuff still works even when the files and directories already
    # exist
    root = Path(master_config.output_path)
    (root / 'index.html').touch()
    (root / 'stats.html').touch()
    (root / 'simple').mkdir()
    (root / 'simple' / 'index.html').touch()
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo'}])
    task.once()
    db_queue.check()
    assert (root / 'simple').exists() and (root / 'simple').is_dir()
    for filename in resource_listdir('piwheels.master.the_scribe', 'static'):
        if filename not in {'index.html', 'project.html', 'stats.html'}:
            assert (root / filename).exists() and (root / filename).is_file()


def test_write_root_index_fails(db_queue, task, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', None])
    with pytest.raises(TypeError):
        task.once()
    db_queue.check()
    root = Path(master_config.output_path)
    assert not (root / 'simple' / 'index.html').exists()


def test_bad_request(db_queue, task, scribe_queue, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo'}])
    scribe_queue.send_pyobj(['FOO'])
    e = Event()
    task.logger = mock.Mock()
    task.logger.error.side_effect = lambda *args: e.set()
    task.once()
    task.poll()
    db_queue.check()
    assert e.wait(1)
    assert task.logger.error.call_args('invalid scribe_queue message: %s', 'FOO')


def test_write_homepage(db_queue, task, scribe_queue, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo'}])
    scribe_queue.send_pyobj(['HOME', {
        'packages_built': 123,
        'files_count': 234,
        'downloads_last_month': 345
    }])
    task.once()
    task.poll()
    db_queue.check()
    root = Path(master_config.output_path)
    assert (root / 'index.html').exists() and (root / 'index.html').is_file()


def test_write_homepage_fails(db_queue, task, scribe_queue, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo'}])
    scribe_queue.send_pyobj(['HOME', {}])
    task.once()
    with pytest.raises(NameError):
        task.poll()
    db_queue.check()
    root = Path(master_config.output_path)
    assert not (root / 'index.html').exists()


def test_write_pkg_index(db_queue, task, scribe_queue, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo'}])
    scribe_queue.send_pyobj(['PKGBOTH', 'foo'])
    db_queue.expect(['PKGFILES', 'foo'])
    db_queue.send(['OK', [
        FilesRow('foo-0.1-cp34-cp34m-linux_armv7l.whl', '123456123456'),
        FilesRow('foo-0.1-cp34-cp34m-linux_armv6l.whl', '123456123456'),
    ]])
    db_queue.expect(['PROJVERS', 'foo'])
    db_queue.send(['OK', [
        ProjVersRow('0.1', False, 2, 0),
    ]])
    db_queue.expect(['PROJFILES', 'foo'])
    db_queue.send(['OK', [
        ProjFilesRow('0.1', 'cp34m', 'foo-0.1-cp34-cp34m-linux_armv6l.whl',
                     123456, '123456123456'),
        ProjFilesRow('0.1', 'cp34m', 'foo-0.1-cp34-cp34m-linux_armv7l.whl',
                     123456, '123456123456'),
    ]])
    task.once()
    task.poll()
    db_queue.check()
    root = Path(master_config.output_path)
    index = root / 'simple' / 'foo' / 'index.html'
    assert index.exists() and index.is_file()
    assert contains_elem(
        index, 'a', [('href', 'foo-0.1-cp34-cp34m-linux_armv7l.whl#sha256=123456123456')]
    )
    assert contains_elem(
        index, 'a', [('href', 'foo-0.1-cp34-cp34m-linux_armv7l.whl#sha256=123456123456')]
    )


def test_write_pkg_index_fails(db_queue, task, scribe_queue, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo'}])
    scribe_queue.send_pyobj(['PKGBOTH', 'foo'])
    db_queue.expect(['PKGFILES', 'foo'])
    db_queue.send(['OK', [
        # Send ordinary tuples (method expects rows with attributes named
        # after columns)
        ('foo-0.1-cp34-cp34m-linux_armv7l.whl', '123456123456'),
        ('foo-0.1-cp34-cp34m-linux_armv6l.whl', '123456123456'),
    ]])
    task.once()
    with pytest.raises(AttributeError):
        task.poll()
    db_queue.check()
    root = Path(master_config.output_path)
    index = root / 'simple' / 'foo' / 'index.html'
    assert not index.exists()


def test_write_new_pkg_index(db_queue, task, scribe_queue, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo'}])
    scribe_queue.send_pyobj(['PKGBOTH', 'bar'])
    db_queue.expect(['PKGFILES', 'bar'])
    db_queue.send(['OK', [
        FilesRow('bar-1.0-cp34-cp34m-linux_armv7l.whl', '123456abcdef'),
        FilesRow('bar-1.0-cp34-cp34m-linux_armv6l.whl', '123456abcdef'),
    ]])
    db_queue.expect(['PROJVERS', 'bar'])
    db_queue.send(['OK', [
        ProjVersRow('1.0', False, 2, 1),
    ]])
    db_queue.expect(['PROJFILES', 'bar'])
    db_queue.send(['OK', [
        ProjFilesRow('1.0', 'cp34m', 'foo-0.1-cp34-cp34m-linux_armv6l.whl',
                     123456, '123456abcdef'),
        ProjFilesRow('1.0', 'cp34m', 'foo-0.1-cp34-cp34m-linux_armv7l.whl',
                     123456, '123456abcdef'),
    ]])
    task.once()
    task.poll()
    db_queue.check()
    root = Path(master_config.output_path)
    root_index = root / 'simple' / 'index.html'
    pkg_index = root / 'simple' / 'bar' / 'index.html'
    assert root_index.exists() and root_index.is_file()
    assert contains_elem(root_index, 'a', [('href', 'bar')])
    assert pkg_index.exists() and pkg_index.is_file()
    assert contains_elem(
        pkg_index, 'a', [('href', 'bar-1.0-cp34-cp34m-linux_armv7l.whl#sha256=123456abcdef')]
    )
    assert contains_elem(
        pkg_index, 'a', [('href', 'bar-1.0-cp34-cp34m-linux_armv7l.whl#sha256=123456abcdef')]
    )


def test_write_search_index(db_queue, task, scribe_queue, master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo', 'bar'}])
    search_index = [
        ('foo', 10),
        ('bar', 1),
    ]
    scribe_queue.send_pyobj(['SEARCH', search_index])
    task.once()
    task.poll()
    db_queue.check()
    root = Path(master_config.output_path)
    packages_json = root / 'packages.json'
    assert packages_json.exists() and packages_json.is_file()
    assert json.load(packages_json.open('r')) == [list(i) for i in search_index]


def test_write_search_index_fails(db_queue, task, scribe_queue,
                                  master_config):
    db_queue.expect(['ALLPKGS'])
    db_queue.send(['OK', {'foo', 'bar'}])
    search_index = [
        ('foo', 10),
        ('bar', 1 + 2j),  # complex download counts :)
    ]
    scribe_queue.send_pyobj(['SEARCH', search_index])
    task.once()
    with pytest.raises(TypeError):
        task.poll()
    db_queue.check()
    root = Path(master_config.output_path)
    packages_json = root / 'packages.json'
    assert not packages_json.exists()
