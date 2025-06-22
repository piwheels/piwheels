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
import gzip
import json
from unittest import mock
from pathlib import Path
from threading import Event
from datetime import datetime, timedelta, timezone

import pytest
from pkg_resources import resource_listdir
from bs4 import BeautifulSoup

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


def make_bs(html_file: Path) -> BeautifulSoup:
    "Create a BeautifulSoup object from an HTML file."
    return BeautifulSoup(html_file.read_text(encoding='utf-8'), 'html.parser')


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
    dir = root / 'simple'
    assert dir.exists() and dir.is_dir()
    index = dir / 'index.html'
    assert index.exists()
    bs = make_bs(index)
    links = bs.find_all('a', href='foo')
    assert len(links) == 1
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


def test_write_pkg_index(db_queue, task, scribe_queue, master_config, project_data):
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
    simple_bs = make_bs(simple)
    assert simple_bs.find('a', href='foo') is not None
    assert simple_index.exists() and simple_index.is_file()
    simple_index_bs = make_bs(simple_index)
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            a = simple_index_bs.find('a', href=f"/simple/foo/{filename}#sha256={file_data['hash']}")
            assert a is not None
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    project_json = root / 'project' / 'foo' / 'json' / 'index.json'
    assert project_json.exists() and project_json.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_new_pkg_index(db_queue, task, scribe_queue, master_config, project_data):
    db_queue.expect('ALLPKGS')
    db_queue.send('OK', set())
    task.once()
    root = Path(master_config.output_path)
    simple = root / 'simple' / 'index.html'
    assert simple.exists() and simple.is_file()
    simple_index_bs = make_bs(simple)
    a = simple_index_bs.find('a', href='foo')
    assert a is None
    scribe_queue.send_msg('BOTH', 'foo')
    db_queue.expect('PROJDATA', 'foo')
    db_queue.send('OK', project_data)
    db_queue.expect('GETPKGNAMES', 'foo')
    db_queue.send('OK', [])
    task.poll(0)
    db_queue.check()
    assert simple.exists() and simple.is_file()
    simple_index = root / 'simple' / 'foo' / 'index.html'
    assert simple_index.exists() and simple_index.is_file()
    simple_index_bs = make_bs(simple_index)
    a = simple_index_bs.find_all('a', href='foo')
    found_links = {a['href'] for a in simple_index_bs.find_all('a')}
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            link = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert link in found_links
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_yanked_files(db_queue, task, scribe_queue, master_config, project_data):
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
    simple_bs = make_bs(simple)
    assert simple_bs.find('a', href='foo') is not None
    assert simple_index.exists() and simple_index.is_file()
    simple_index_bs = make_bs(simple_index)
    found_links = {a['href']: a for a in simple_index_bs.find_all('a')}
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            link = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert link in found_links
            a = found_links[link]
            assert 'data-yanked' in a.attrs
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    project_json = root / 'project' / 'foo' / 'json' / 'index.json'
    assert project_json.exists() and project_json.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_requires_python(db_queue, task, scribe_queue, master_config, project_data):
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
    assert simple_index.exists() and simple_index.is_file()
    simple_bs = make_bs(simple)
    assert simple_bs.find('a', href='foo') is not None
    simple_index_bs = make_bs(simple_index)
    found_links = {a['href']: a for a in simple_index_bs.find_all('a')}
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            link = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert link in found_links
            assert 'data-requires-python' in found_links[link].attrs
            assert found_links[link]['data-requires-python'] == '>=3'
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
    simple_bs = make_bs(simple)
    assert simple_bs.find('a', href='foo') is not None
    assert simple_index.exists() and simple_index.is_file()
    simple_index_bs = make_bs(simple_index)
    found_links = {a['href']: a for a in simple_index_bs.find_all('a')}
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            link = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert link in found_links
            a = found_links[link]
            assert 'data-yanked' in a.attrs
            assert 'data-requires-python' in a.attrs
            assert a['data-requires-python'] == '>=3'
    project = root / 'project' / 'foo' / 'index.html'
    assert project.exists() and project.is_file()
    project_json = root / 'project' / 'foo' / 'json' / 'index.json'
    assert project_json.exists() and project_json.is_file()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_aliases(db_queue, task, scribe_queue, master_config, project_data):
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
    simple_bs = make_bs(simple)
    assert simple_bs.find('a', href='foo') is not None
    assert simple_index.exists() and simple_index.is_file()
    simple_index_bs = make_bs(simple_index)
    found_links = {a['href'] for a in simple_index_bs.find_all('a')}
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            link = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert link in found_links
    canonical = root / 'project' / 'foo'
    alias = root / 'project' / 'Foo'
    assert (canonical / 'index.html').exists()
    assert alias.exists() and alias.is_symlink()
    assert canonical.resolve() == alias.resolve()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_index_with_existing_alias(db_queue, task, scribe_queue, master_config, project_data):
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
    simple_bs = make_bs(simple)
    assert simple_bs.find('a', href='foo') is not None
    assert simple_index.exists() and simple_index.is_file()
    simple_index_bs = make_bs(simple_index)
    found_links = {a['href'] for a in simple_index_bs.find_all('a')}
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            link = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert link in found_links
    canonical = root / 'project' / 'foo'
    alias = root / 'project' / 'Foo'
    assert (canonical / 'index.html').exists()
    assert alias.exists() and alias.is_symlink()
    assert canonical.resolve() == alias.resolve()
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_no_files(db_queue, task, scribe_queue, master_config, project_data):
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
    
    proj_bs = make_bs(project_page)
    h2 = proj_bs.find('h2', id='package')
    assert h2 is not None and h2.text == 'foo'
    p = proj_bs.find('p', id='description')
    assert p is not None and p.text == 'Some description'
    pip_deps_ul = proj_bs.find('ul', id='pipdeps')
    assert pip_deps_ul is not None
    pip_deps_li = pip_deps_ul.find_all('li')
    assert len(pip_deps_li) == 1 and pip_deps_li[0].text == 'None'

    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1']['files']) == 0
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_no_deps(db_queue, task, scribe_queue, master_config, project_data):
    project_data['description'] = 'Some description'
    for release in project_data['releases'].values():
        for filedata in release['files'].values():
            filedata['apt_dependencies'] = set()
            filedata['pip_dependencies'] = set()
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

    proj_bs = make_bs(project_page)
    h2 = proj_bs.find('h2', id='package')
    assert h2 is not None and h2.text == 'foo'
    p = proj_bs.find('p', id='description')
    assert p is not None and p.text == 'Some description'
    pip_deps_ul = proj_bs.find('ul', id='pipdeps')
    assert pip_deps_ul is not None
    pip_deps_li = pip_deps_ul.find_all('li')
    assert len(pip_deps_li) == 1
    assert pip_deps_li[0].text == 'None'

    releases_table = proj_bs.find('table', id='releases-table')
    file_links = {}
    for tr in releases_table.find_all('tr', class_='files-info'):
        ul = tr.find('ul', class_='files')
        for li in ul.find_all('li'):
            filename = li.find('a').text
            file_links[filename] = {
                'href': li.find('a')['href'],
                'apt_deps': li.get('data-aptdependencies', ''),
                'pip_deps': li.get('data-pipdependencies', ''),
            }
    assert releases_table is not None
    for release in project_data['releases'].values():
        for filename, file_data in reversed(release['files'].items()):
            assert filename in file_links
            file_link = file_links[filename]
            assert file_link['href'] == f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert file_link['apt_deps'] == ''
            assert file_link['pip_deps'] == ''
    install_pre = proj_bs.find('pre', id='install-command')
    assert install_pre is not None and install_pre.text == 'pip3 install foo'
    assert 'apt install' not in install_pre.text

    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1']['files']) == 2
    for version, release in project_data['releases'].items():
        for filename, file_data in reversed(release['files'].items()):
            file = data['releases'][version]['files'][filename]
            assert file['apt_dependencies'] == []
            assert file['pip_dependencies'] == []
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_with_deps(db_queue, task, scribe_queue, master_config, project_data):
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
    
    proj_bs = make_bs(project_page)
    h2 = proj_bs.find('h2', id='package')
    assert h2 is not None and h2.text == 'foo'
    p = proj_bs.find('p', id='description')
    assert p is not None and p.text == 'Some description'
    pip_deps_ul = proj_bs.find('ul', id='pipdeps')
    assert pip_deps_ul is not None
    pip_deps_li = pip_deps_ul.find_all('li')
    assert len(pip_deps_li) == 1
    assert pip_deps_li[0].text == 'bar'
    pip_dep_link = pip_deps_li[0].find('a')
    assert pip_dep_link is not None and pip_dep_link['href'] == '/project/bar/'

    releases_table = proj_bs.find('table', id='releases-table')
    file_links = {}
    for tr in releases_table.find_all('tr', class_='files-info'):
        ul = tr.find('ul', class_='files')
        for li in ul.find_all('li'):
            filename = li.find('a').text
            file_links[filename] = {
                'href': li.find('a')['href'],
                'apt_deps': li.get('data-aptdependencies', 'libfoo'),
                'pip_deps': li.get('data-pipdependencies', 'bar'),
            }
    assert releases_table is not None
    for release in project_data['releases'].values():
        for filename, file_data in reversed(release['files'].items()):
            assert filename in file_links
            file_link = file_links[filename]
            assert file_link['href'] == f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert file_link['apt_deps'] == 'libfoo'
            assert file_link['pip_deps'] == 'bar'
    install_pre = proj_bs.find('pre', id='install-command')
    assert install_pre is not None
    assert 'sudo apt install libfoo' in install_pre.text
    assert 'pip3 install foo' in install_pre.text

    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1']['files']) == 2
    for version, release in project_data['releases'].items():
        for filename, file_data in reversed(release['files'].items()):
            file = data['releases'][version]['files'][filename]
            assert file['apt_dependencies'] == ['libfoo']
            assert file['pip_dependencies'] == ['bar']
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_yanked(db_queue, task, scribe_queue, master_config, project_data):
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
    proj_bs = make_bs(project_page)
    h2 = proj_bs.find('h2', id='package')
    assert h2 is not None and h2.text == 'foo'
    p = proj_bs.find('p', id='description')
    assert p is not None and p.text == 'Some description'
    yanked = proj_bs.find('span', class_='yanked')
    assert yanked is not None and yanked.text == 'yanked'
    found_file_links = {}
    for files_ul in proj_bs.find_all('ul', class_='files'):
        for li in files_ul.find_all('li'):
            a = li.find('a')
            filename = a.text
            found_file_links[filename] = {
                'href': a['href'],
            }
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert filename in found_file_links
            file_link = found_file_links[filename]
            expected_href = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert file_link['href'] == expected_href
    install_pre = proj_bs.find('pre', id='install-command')
    assert install_pre is not None and install_pre.text == 'pip3 install foo'
    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1']['files']) == 2
    assert data['releases']['0.1']['yanked']
    assert not data['releases']['0.1']['prerelease']
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_prerelease(db_queue, task, scribe_queue, master_config, project_data):
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
    proj_bs = make_bs(project_page)
    h2 = proj_bs.find('h2', id='package')
    assert h2 is not None and h2.text == 'foo'
    desc = proj_bs.find('p', id='description')
    assert desc is not None and desc.text == 'Some description'
    releases_table = proj_bs.find('table', id='releases-table')
    prerelease_span = releases_table.find('span', class_='prerelease')
    assert prerelease_span is not None and prerelease_span.text == 'pre-release'
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            url = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            links = proj_bs.find('a', href=url)
            assert links is not None
            
    install_pre = proj_bs.find('pre', id='install-command')
    assert install_pre is not None
    assert install_pre.text == 'pip3 install foo'

    assert project_json_file.exists() and project_json_file.is_file()
    with open(str(project_json_file.absolute())) as f:
        data = json.load(f)
    assert data['package'] == 'foo'
    assert len(data['releases']) == 1
    assert len(data['releases']['0.1a']['files']) == 2
    assert not data['releases']['0.1a']['yanked']
    assert data['releases']['0.1a']['prerelease']
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_write_pkg_project_yanked_prerelease(db_queue, task, scribe_queue, master_config, project_data):
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
    proj_bs = make_bs(project_page)
    h2 = proj_bs.find('h2', id='package')
    assert h2 is not None and h2.text == 'foo'
    desc = proj_bs.find('p', id='description')
    assert desc is not None and desc.text == 'Some description'
    
    releases_table = proj_bs.find('table', id='releases-table')
    prerelease_span = releases_table.find('span', class_='prerelease')
    assert prerelease_span is not None and prerelease_span.text == 'pre-release'
    yanked_span = releases_table.find('span', class_='yanked')
    assert yanked_span is not None and yanked_span.text == 'yanked'

    found_file_links = {}
    for files_ul in proj_bs.find_all('ul', class_='files'):
        for li in files_ul.find_all('li'):
            a = li.find('a')
            filename = a.text
            found_file_links[filename] = a['href']
    for release in project_data['releases'].values():
        for filename, file_data in release['files'].items():
            assert filename in found_file_links
            expected_href = f"/simple/foo/{filename}#sha256={file_data['hash']}"
            assert found_file_links[filename] == expected_href
    
    install_pre = proj_bs.find('pre', id='install-command')
    assert install_pre is not None
    assert install_pre.text == 'pip3 install foo'

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


def test_delete_package_with_aliases(db_queue, task, scribe_queue, master_config):
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


def test_delete_version(db_queue, task, scribe_queue, master_config, project_data):
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
    proj_bs = make_bs(project_page)
    install_pre = proj_bs.find('pre', id='install-command')
    assert install_pre is not None and install_pre.text == 'pip3 install foo'
    
    releases_table = proj_bs.find('table', id='releases-table')
    file_links = {}
    for tr in releases_table.find_all('tr', class_='files-info'):
        ul = tr.find('ul', class_='files')
        for li in ul.find_all('li'):
            a = li.find('a')
            filename = a.text
            file_links[filename] = a['href']
    for filename, file_data in project_data['releases']['0.1']['files'].items():
        assert filename not in file_links
    for filename, file_data in project_data['releases']['0.2']['files'].items():
        link = f"/simple/foo/{filename}#sha256={file_data['hash']}"
        assert filename in file_links
        assert file_links[filename] == link
    assert scribe_queue.recv_msg() == ('DONE', None)


def test_delete_version_missing_file(db_queue, task, scribe_queue, master_config, project_data):
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
