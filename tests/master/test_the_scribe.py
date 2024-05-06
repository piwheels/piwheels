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
import io
import gzip
import json
import cbor2 as cbor
from unittest import mock
from pathlib import Path
from time import time, sleep
from collections import namedtuple, OrderedDict
from html.parser import HTMLParser
from threading import Event
from datetime import datetime, timedelta, timezone

import pytest
from pkg_resources import resource_listdir

from piwheels import const, protocols, transport
from piwheels.states import MasterStats
from piwheels.master.the_scribe import TheScribe, AtomicReplaceFile


UTC = timezone.utc


@pytest.fixture()
def task(request, zmq_context, master_config, db_queue):
    task = TheScribe(master_config)
    yield task
    task.close()


@pytest.fixture()
def scribe_queue(request, zmq_context):
    queue = zmq_context.socket(
        transport.REQ, protocol=reversed(protocols.the_scribe))
    queue.hwm = 10
    queue.connect(const.SCRIBE_QUEUE)
    yield queue
    queue.close()


@pytest.fixture()
def stats_data(request):
    return MasterStats(**{
        'timestamp':             datetime(2018, 1, 1, 12, 30, 40, tzinfo=UTC),
        'packages_built':        123,
        'builds_last_hour':      {},
        'builds_time':           timedelta(0),
        'builds_size':           0,
        'builds_pending':        {},
        'new_last_hour':         0,
        'files_count':           234,
        'downloads_last_hour':   12,
        'downloads_last_month':  345,
        'downloads_all':         123456,
        'disk_size':             0,
        'disk_free':             0,
        'mem_size':              0,
        'mem_free':              0,
        'swap_size':             0,
        'swap_free':             0,
        'cpu_temp':              0.0,
        'load_average':          0.0,
    })


class ContainsParser(HTMLParser):
    def __init__(self, tag, attrs=None, content=None):
        super().__init__(convert_charrefs=True)
        self.state = 'not found'
        self.tag = tag
        self.attrs = set() if attrs is None else set(attrs)
        self.content = content
        self.compare = None

    def handle_starttag(self, tag, attrs):
        if tag == self.tag and self.attrs <= set(attrs) and self.state != 'found':
            if self.content is None:
                self.state = 'found'
            else:
                self.state = 'in tag'
                self.compare = ''

    def handle_data(self, data):
        if self.state == 'in tag':
            self.compare += data

    def handle_endtag(self, tag):
        # Yes, this isn't sufficient to deal with nested equivalent tags but
        # it's only meant to be a simple matcher
        if tag == self.tag and self.state == 'in tag':
            if self.content == self.compare:
                self.state = 'found'

    @property
    def found(self):
        return self.state == 'found'


def contains_elem(path, tag, attrs=None, content=None):
    parser = ContainsParser(tag, attrs, content)
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
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
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
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    db_queue.check()
    assert (root / 'simple').exists() and (root / 'simple').is_dir()
    for filename in resource_listdir('piwheels.master.the_scribe', 'static'):
        if filename not in {'index.html', 'project.html', 'stats.html'}:
            assert (root / filename).exists() and (root / filename).is_file()


def test_bad_request(db_queue, task, scribe_queue, master_config):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    scribe_queue.send(b'FOO')
    e = Event()
    task.logger = mock.Mock()
    task.logger.error.side_effect = lambda *args: e.set()
    task.once()
    task.poll(0)
    db_queue.check()
    assert e.wait(1)
    assert task.logger.error.call_args('invalid scribe_queue message: %s', 'FOO')


def test_write_homepage(db_queue, task, scribe_queue, master_config, stats_data):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    scribe_queue.send_msg('HOME', stats_data.as_message())
    task.once()
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    assert (root / 'index.html').exists() and (root / 'index.html').is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_log(db_queue, task, scribe_queue, master_config):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('LOG', (1, 'foo bar baz'))
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    logs = root / 'logs'
    assert logs.exists()
    log_file = logs / '0000' / '0000' / '0001.txt.gz'
    assert log_file.exists() and log_file.is_file()
    with log_file.open('rb') as f:
        with gzip.open(f, 'rt', encoding='utf-8') as arc:
            assert arc.read() == 'foo bar baz'


def test_write_pkg_index(db_queue, task, scribe_queue, master_config,
                         project_data):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('BOTH', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'index.html'
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert simple.exists() and simple.is_file()
    assert contains_elem(simple, 'a', [('href', 'foo')])
    assert simple_index.exists() and simple_index.is_file()
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                simple_index, 'a', [
                    ('href', '{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash']))
                ])
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    project_json = root / 'project' / 'foo' / 'json' / 'index.json'
    assert project_json.exists() and project_json.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_new_pkg_index(db_queue, task, scribe_queue, master_config,
                             project_data):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', set())
    task.once()
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'index.html'
    assert simple.exists() and simple.is_file()
    assert not contains_elem(simple, 'a', [('href', 'foo')])
    scribe_queue.send_msg('BOTH', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    assert simple.exists() and simple.is_file()
    assert contains_elem(simple, 'a', [('href', 'foo')])
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert simple_index.exists() and simple_index.is_file()
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                simple_index, 'a', [
                    ('href', '{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash']))
                ])
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_yanked_files(db_queue, task, scribe_queue,
                                           master_config, project_data):
    for release in project_data['releases']:
        project_data['releases'][release]['yanked'] = True
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('BOTH', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'index.html'
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert simple.exists() and simple.is_file()
    assert contains_elem(simple, 'a', [('href', 'foo')])
    assert simple_index.exists() and simple_index.is_file()
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                simple_index, 'a', [
                    ('href', '{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                    ('data-yanked', ''),
                ])
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    project_json = root / 'project' / 'foo' / 'json' / 'index.json'
    assert project_json.exists() and project_json.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_requires_python(db_queue, task, scribe_queue,
                                              master_config, project_data):
    for release in project_data['releases'].values():
        for filedata in release['files'].values():
            filedata['requires_python'] = '>=3'
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('BOTH', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'index.html'
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert simple.exists() and simple.is_file()
    assert contains_elem(simple, 'a', [('href', 'foo')])
    assert simple_index.exists() and simple_index.is_file()
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                simple_index, 'a', [
                    ('href', '{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                    ('data-requires-python', '>=3'),
                ])
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    project_json = root / 'project' / 'foo' / 'json' / 'index.json'
    assert project_json.exists() and project_json.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_yanked_files_and_requires_python(
    db_queue, task, scribe_queue, master_config, project_data
):
    for release in project_data['releases'].values():
        release['yanked'] = True
        for filedata in release['files'].values():
            filedata['requires_python'] = '>=3'
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('BOTH', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'index.html'
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert simple.exists() and simple.is_file()
    assert contains_elem(simple, 'a', [('href', 'foo')])
    assert simple_index.exists() and simple_index.is_file()
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                simple_index, 'a', [
                    ('href', '{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                    ('data-yanked', ''),
                    ('data-requires-python', '>=3'),
                ])
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    project_json = root / 'project' / 'foo' / 'json' / 'index.json'
    assert project_json.exists() and project_json.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_aliases(db_queue, task, scribe_queue,
                                      master_config, project_data):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('BOTH', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', ['Foo'])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'index.html'
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert simple.exists() and simple.is_file()
    assert contains_elem(simple, 'a', [('href', 'foo')])
    assert simple_index.exists() and simple_index.is_file()
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                simple_index, 'a', [
                    ('href', '{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                ])
    canonical = root / 'project' / 'foo'
    alias = root / 'project' / 'Foo'
    assert (canonical / 'index.html').exists()
    assert alias.exists() and alias.is_symlink()
    assert canonical.resolve() == alias.resolve()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_existing_alias(db_queue, task, scribe_queue,
                                             master_config, project_data):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    root = Path(master_config.output_path)
    (root / 'project' / 'foo').mkdir()
    (root / 'project' / 'Foo').symlink_to('foo')
    scribe_queue.send_msg('BOTH', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', ['Foo'])
    task.poll(0)
    db_queue.check()
    simple = root / 'simple' / 'index.html'
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert simple.exists() and simple.is_file()
    assert contains_elem(simple, 'a', [('href', 'foo')])
    assert simple_index.exists() and simple_index.is_file()
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                simple_index, 'a', [
                    ('href', '{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                ])
    canonical = root / 'project' / 'foo'
    alias = root / 'project' / 'Foo'
    assert (canonical / 'index.html').exists()
    assert alias.exists() and alias.is_symlink()
    assert canonical.resolve() == alias.resolve()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_no_files(db_queue, task, scribe_queue,
                                    master_config, project_data):
    project_data['description'] = 'Some description'
    for release in project_data['releases']:
        project_data['releases'][release]['files'].clear()
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('PROJECT', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    index = root / 'simple' / 'foo' / 'index.html'
    assert not index.exists()
    project = root / 'project' / 'foo'
    project_page = project / 'index.html'
    project_json = project / 'json'
    project_json_file = project_json / 'index.json'
    assert project_page.exists() and project_page.is_file()
    assert contains_elem(project_page, 'h2', content='foo')
    assert contains_elem(project_page, 'p', content='Some description')
    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1']['files']) == 0
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_no_deps(db_queue, task, scribe_queue, master_config,
                                   project_data):
    project_data['description'] = 'Some description'
    for release in project_data['releases'].values():
        for filedata in release['files'].values():
            filedata['apt_dependencies'] = set()
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('PROJECT', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert not simple_index.exists()
    project = root / 'project' / 'foo'
    project_page = project / 'index.html'
    project_json = project / 'json'
    project_json_file = project_json / 'index.json'
    assert project_page.exists() and project_page.is_file()
    assert contains_elem(project_page, 'h2', content='foo')
    assert contains_elem(project_page, 'p', content='Some description')
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                project_page, 'a', [
                    ('href', '/simple/foo/{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                ], filename)
    assert contains_elem(project_page, 'pre', content='pip3 install foo')
    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1']['files']) == 2
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_with_deps(db_queue, task, scribe_queue,
                                     master_config, project_data):
    project_data['description'] = 'Some description'
    for release in project_data['releases'].values():
        for filedata in release['files'].values():
            filedata['apt_dependencies'] = {'libfoo'}
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('PROJECT', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert not simple_index.exists()
    project = root / 'project' / 'foo'
    project_page = project / 'index.html'
    project_json = project / 'json'
    project_json_file = project_json / 'index.json'
    assert project_page.exists() and project_page.is_file()
    assert contains_elem(project_page, 'h2', content='foo')
    assert contains_elem(project_page, 'p', content='Some description')
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                project_page, 'a', [
                    ('href', '/simple/foo/{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                ], filename)
    assert contains_elem(
        project_page, 'pre',
        content='sudo apt install libfoo\npip3 install foo')
    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1']['files']) == 2
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_yanked(db_queue, task, scribe_queue, master_config,
                                  project_data):
    project_data['description'] = 'Some description'
    for release in project_data['releases'].values():
        release['yanked'] = True
        for filedata in release['files'].values():
            filedata['apt_dependencies'] = set()
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('PROJECT', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert not simple_index.exists()
    project = root / 'project' / 'foo'
    project_page = project / 'index.html'
    project_json = project / 'json'
    project_json_file = project_json / 'index.json'
    assert project_page.exists() and project_page.is_file()
    assert contains_elem(project_page, 'h2', content='foo')
    assert contains_elem(project_page, 'p', content='Some description')
    assert contains_elem(
        project_page, 'span',
        [('class', 'yanked')],
        'yanked'
    )
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                project_page, 'a', [
                    ('href', '/simple/foo/{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                ], filename)
    assert contains_elem(project_page, 'pre', content='pip3 install foo')
    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1']['files']) == 2
    assert data['releases']['0.1']['yanked']
    assert not data['releases']['0.1']['prerelease']
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_prerelease(db_queue, task, scribe_queue,
                                      master_config, project_data):
    project_data['description'] = 'Some description'
    project_data['releases']['0.1a'] = project_data['releases'].pop('0.1')
    for release in project_data['releases'].values():
        release['files'] = {
            filename.replace('-0.1-', '-0.1a-'): filedata
            for filename, filedata in release['files'].items()
        }
        for filedata in release['files'].values():
            filedata['apt_dependencies'] = set()
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('PROJECT', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert not simple_index.exists()
    project = root / 'project' / 'foo'
    project_page = project / 'index.html'
    project_json = project / 'json'
    project_json_file = project_json / 'index.json'
    assert project_page.exists() and project_page.is_file()
    assert contains_elem(project_page, 'h2', content='foo')
    assert contains_elem(project_page, 'p', content='Some description')
    assert contains_elem(
        project_page, 'span',
        [('class', 'prerelease')],
        'pre-release'
    )
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                project_page, 'a', [
                    ('href', '/simple/foo/{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                ], filename)
    assert contains_elem(project_page, 'pre', content='pip3 install foo')
    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1a']['files']) == 2
    assert not data['releases']['0.1a']['yanked']
    assert data['releases']['0.1a']['prerelease']
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_yanked_prerelease(db_queue, task, scribe_queue,
                                             master_config, project_data):
    project_data['description'] = 'Some description'
    project_data['releases']['0.1a'] = project_data['releases'].pop('0.1')
    for release in project_data['releases'].values():
        release['yanked'] = True
        release['files'] = {
            filename.replace('-0.1-', '-0.1a-'): filedata
            for filename, filedata in release['files'].items()
        }
        for filedata in release['files'].values():
            filedata['apt_dependencies'] = set()
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('PROJECT', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert not simple_index.exists()
    project = root / 'project' / 'foo'
    project_page = project / 'index.html'
    project_json = project / 'json'
    project_json_file = project_json / 'index.json'
    assert project_page.exists() and project_page.is_file()
    assert contains_elem(project_page, 'h2', content='foo')
    assert contains_elem(project_page, 'p', content='Some description')
    assert contains_elem(
        project_page, 'span',
        [('class', 'yanked')],
        'yanked'
    )
    assert contains_elem(
        project_page, 'span',
        [('class', 'prerelease')],
        'pre-release'
    )
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert contains_elem(
                project_page, 'a', [
                    ('href', '/simple/foo/{filename}#sha256={filehash}'.format(
                        filename=filename, filehash=file_data['hash'])),
                ], filename)
    assert contains_elem(project_page, 'pre', content='pip3 install foo')
    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1a']['files']) == 2
    assert data['releases']['0.1a']['yanked']
    assert data['releases']['0.1a']['prerelease']
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_search_index(db_queue, task, scribe_queue, master_config):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo', 'bar'})
    task.once()
    search_index = {
        'foo': (10, 100),
        'bar': (0, 1),
    }
    scribe_queue.send_msg('SEARCH', search_index)
    task.poll(0)
    db_queue.check()
    root = Path(master_config.output_path)
    packages_json = root / 'packages.json'
    assert packages_json.exists() and packages_json.is_file()
    assert search_index == {
        pkg: (count_recent, count_all)
        for pkg, count_recent, count_all in json.load(packages_json.open('r'))
    }
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_delete_package(db_queue, task, scribe_queue, master_config):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('DELPKG', 'foo')
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    db_queue.expect('PKGFILES', 'foo')
    db_queue.send('OK', {
        'foo-0.1-cp34-cp34m-linux_armv6l.whl': 'deadbeef',
        'foo-0.1-cp34-cp34m-linux_armv7l.whl': 'deadbeef',
    })
    root = Path(master_config.output_path)
    index = root / 'simple' / 'foo'
    index.mkdir(parents=True)
    project = root / 'project' / 'foo'
    project.mkdir(parents=True)
    project_json = project / 'json'
    project_json.mkdir(parents=True)
    (index / 'foo-0.1-cp34-cp34m-linux_armv6l.whl').touch()
    (index / 'foo-0.1-cp34-cp34m-linux_armv7l.whl').touch()
    (project / 'index.html').touch()
    (project_json / 'index.json').touch()
    task.poll(0)
    db_queue.check()
    assert not index.exists()
    assert not project_json.exists()
    assert not project.exists()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_delete_package_with_aliases(db_queue, task, scribe_queue,
                                     master_config):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('DELPKG', 'foo')
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', ['Foo'])
    db_queue.expect('PKGFILES', 'foo')
    db_queue.send('OK', {
        'foo-0.1-cp34-cp34m-linux_armv6l.whl': 'deadbeef',
        'foo-0.1-cp34-cp34m-linux_armv7l.whl': 'deadbeef',
    })
    root = Path(master_config.output_path)
    index = root / 'simple' / 'foo'
    index.mkdir(parents=True)
    project = root / 'project' / 'foo'
    project.mkdir(parents=True)
    project_json = project / 'json'
    project_json.mkdir(parents=True)
    (index / 'foo-0.1-cp34-cp34m-linux_armv6l.whl').touch()
    (index / 'foo-0.1-cp34-cp34m-linux_armv7l.whl').touch()
    (project / 'index.html').touch()
    (project_json / 'index.json').touch()
    alias = root / 'simple' / 'Foo'
    alias.symlink_to(index)
    task.poll(0)
    db_queue.check()
    assert not index.exists()
    assert not alias.exists()
    assert not project_json.exists()
    assert not project.exists()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_delete_package_fail(db_queue, task, scribe_queue, master_config):
    task.logger = mock.Mock()
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('DELPKG', 'foo')
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    db_queue.expect('PKGFILES', 'foo')
    db_queue.send('OK', {
        'foo-0.1-cp34-cp34m-linux_armv6l.whl': 'deadbeef',
        'foo-0.1-cp34-cp34m-linux_armv7l.whl': 'deadbeef',
    })
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'foo'
    simple.mkdir(parents=True)
    project = root / 'project' / 'foo'
    project.mkdir(parents=True)
    project_json = project / 'json'
    project_json.mkdir(parents=True)
    wheel_1 = simple / 'foo-0.1-cp34-cp34m-linux_armv6l.whl'
    wheel_2 = simple / 'foo-0.1-cp34-cp34m-linux_armv7l.whl'
    wheel_3 = simple / 'foo-0.2-cp34-cp34m-linux_armv7l.whl'
    simple_index = simple / 'index.html'
    project_page = project / 'index.html'
    project_json_file = project_json / 'index.json'
    for file in (wheel_1, wheel_2, wheel_3, simple_index, project_page, project_json_file):
        file.touch()
    task.poll(0)
    db_queue.check()
    assert not simple_index.exists()
    assert not wheel_1.exists()
    assert not wheel_2.exists()
    assert not project_json.exists()
    assert not project_page.exists()
    assert not project_json_file.exists()
    assert not project.exists()
    assert task.logger.error.call_count == 1
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_delete_package_missing_file(db_queue, task, scribe_queue, master_config):
    task.logger = mock.Mock()
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('DELPKG', 'foo')
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    db_queue.expect('PKGFILES', 'foo')
    db_queue.send('OK', {
        'foo-0.1-cp34-cp34m-linux_armv6l.whl': 'deadbeef',
        'foo-0.1-cp34-cp34m-linux_armv7l.whl': 'deadbeef',
    })
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'foo'
    simple.mkdir(parents=True)
    project = root / 'project' / 'foo'
    project.mkdir(parents=True)
    project_json = project / 'json'
    project_json.mkdir(parents=True)
    wheel_1 = simple / 'foo-0.1-cp34-cp34m-linux_armv6l.whl'
    wheel_2 = simple / 'foo-0.1-cp34-cp34m-linux_armv7l.whl'
    simple_index = simple / 'index.html'
    project_page = project / 'index.html'
    project_json_file = project_json / 'index.json'
    for file in (wheel_1, simple_index, project_page, project_json_file):
        file.touch()
    assert wheel_1.exists()
    assert not wheel_2.exists()
    task.poll(0)
    db_queue.check()
    assert not simple.exists()
    assert not wheel_1.exists()
    assert not wheel_2.exists()
    assert not project.exists()
    assert not project_json.exists()
    assert not project_page.exists()
    assert not project_json_file.exists()
    assert task.logger.error.call_count == 1
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_delete_version(db_queue, task, scribe_queue, master_config,
                        project_data):
    project_data['description'] = 'Some description'
    for release in project_data['releases'].values():
        for filedata in release['files'].values():
            filedata['apt_dependencies'] = set()
    project_data['releases']['0.2'] = project_data['releases']['0.1'].copy()
    project_data['releases']['0.2']['files'] = {
        filename.replace('-0.1-', '-0.2-'): filedata
        for filename, filedata in project_data['releases']['0.2']['files'].items()
    }
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('DELVER', ['foo', '0.1'])
    db_queue.expect('VERFILES', ['foo', '0.1'])
    db_queue.send('OK', {
        filename: filedata['hash']
        for filename, filedata in project_data['releases']['0.1']['files'].items()
    })
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'foo'
    simple.mkdir(parents=True)
    for release in project_data['releases'].values():
        for filename in release['files']:
            (simple / filename).touch()
    project = root / 'project' / 'foo'
    project.mkdir(parents=True)
    project_page = project / 'index.html'
    task.poll(0)
    db_queue.check()
    assert simple.exists()
    assert project.exists()
    assert project_page.exists()
    for filename in project_data['releases']['0.1']['files']:
        assert not (simple / filename).exists()
    for filename in project_data['releases']['0.2']['files']:
        assert (simple / filename).exists()
    assert contains_elem(project_page, 'pre', content='pip3 install foo')
    for filename, file_data in project_data['releases']['0.1']['files'].items():
        assert not contains_elem(
            project_page, 'a', [
                ('href', '/simple/foo/{filename}#sha256={filehash}'.format(
                    filename=filename, filehash=file_data['hash'])),
            ], filename)
    for filename, file_data in project_data['releases']['0.2']['files'].items():
        assert contains_elem(
            project_page, 'a', [
                ('href', '/simple/foo/{filename}#sha256={filehash}'.format(
                    filename=filename, filehash=file_data['hash'])),
            ], filename)
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_delete_version_missing_file(db_queue, task, scribe_queue,
                                     master_config, project_data):
    project_data['description'] = 'Some description'
    for release in project_data['releases'].values():
        for filedata in release['files'].values():
            filedata['apt_dependencies'] = set()
    project_data['releases']['0.2'] = project_data['releases']['0.1'].copy()
    project_data['releases']['0.2']['files'] = {
        filename.replace('-0.1-', '-0.2-'): filedata
        for filename, filedata in project_data['releases']['0.2']['files'].items()
    }
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {'foo'})
    task.once()
    scribe_queue.send_msg('DELVER', ['foo', '0.1'])
    db_queue.expect('VERFILES', ['foo', '0.1'])
    db_queue.send('OK', {
        filename: filedata['hash']
        for filename, filedata in project_data['releases']['0.1']['files'].items()
    })
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'foo'
    simple.mkdir(parents=True)
    for release in project_data['releases'].values():
        for filename in release['files']:
            # Skip creating one file
            if '-0.1-' in filename and 'linux_armv7l' in filename:
                continue
            (simple / filename).touch()
    assert 3 == sum(
        (simple / filename).exists()
        for release in project_data['releases'].values()
        for filename in release['files']
    )
    project = root / 'project' / 'foo'
    project.mkdir(parents=True)
    task.poll(0)
    db_queue.check()
    assert simple.exists()
    assert project.exists()
    for filename in project_data['releases']['0.1']['files']:
        assert not (simple / filename).exists()
    for filename in project_data['releases']['0.2']['files']:
        assert (simple / filename).exists()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_delete_package_null(db_queue, task, scribe_queue, master_config):
    # this should never happen, but just in case...
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', {''})
    task.once()
    scribe_queue.send_msg('DELPKG', '')
    root = Path(master_config.output_path)
    index = root / 'simple'
    project = root / 'project'
    with pytest.raises(RuntimeError):
        task.poll(0)
    db_queue.check()
    assert index.exists()
    assert project.exists()
