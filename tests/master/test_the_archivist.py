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

from pathlib import Path
from unittest import mock

import pytest

from piwheels import const
from piwheels.master.the_archivist import TheArchivist


def make_file(base_simple, package, filename, content=b'wheel-bytes',
              metadata=True):
    pkg_dir = base_simple / package
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / filename).write_bytes(content)
    if metadata:
        (pkg_dir / (filename + '.metadata')).write_bytes(b'metadata-bytes')


@pytest.fixture()
def archivist_config(request, master_config, tmpdir):
    master_config.archive_dir = str(tmpdir.mkdir('archive'))
    master_config.archive_threshold = 10
    master_config.unarchive_threshold = 1
    master_config.archive_interval = 24
    return master_config


@pytest.fixture()
def task(request, archivist_config, with_schema):
    task = TheArchivist(archivist_config)
    # The web_queue (rebuild request) round-trip is exercised separately by
    # TheSecretary/TheScribe's own tests; here we only care that TheArchivist
    # asks for the right package to be rebuilt
    task.web_queue = mock.Mock()
    yield task
    task.close()


def test_do_archive_run_archives_unpopular_files(db, task, archivist_config,
                                                   with_files):
    master_simple = Path(archivist_config.output_path) / 'simple'
    archive_simple = Path(archivist_config.archive_dir) / 'simple'
    for state in with_files:
        make_file(master_simple, 'foo', state.filename)

    task.do_archive_run()

    for state in with_files:
        assert (archive_simple / 'foo' / state.filename).read_bytes() == \
            b'wheel-bytes'
        assert (archive_simple / 'foo' /
                (state.filename + '.metadata')).exists()
        assert not (master_simple / 'foo' / state.filename).exists()
    assert set(db.execute(
        "SELECT location FROM files WHERE package_tag = 'foo'"
    )) == {(const.ARCHIVE_LOCATION,)}
    task.web_queue.send_msg.assert_called_once_with('PROJECT', 'foo')
    task.web_queue.recv_msg.assert_called_once()


def test_do_archive_run_unarchives_popular_files(db, task, archivist_config,
                                                   with_files):
    master_simple = Path(archivist_config.output_path) / 'simple'
    archive_simple = Path(archivist_config.archive_dir) / 'simple'
    filenames = [s.filename for s in with_files]
    with db.begin():
        db.execute(
            "UPDATE files SET location = %s", const.ARCHIVE_LOCATION)
        for filename in filenames:
            db.execute(
                "INSERT INTO downloads "
                "(filename, accessed_by, accessed_at) "
                "VALUES (%s, '123.4.5.6', CURRENT_TIMESTAMP)", filename)
    for state in with_files:
        make_file(archive_simple, 'foo', state.filename)

    task.do_archive_run()

    for state in with_files:
        assert (master_simple / 'foo' / state.filename).read_bytes() == \
            b'wheel-bytes'
        assert not (archive_simple / 'foo' / state.filename).exists()
    assert set(db.execute(
        "SELECT location FROM files WHERE package_tag = 'foo'"
    )) == {(const.MASTER_LOCATION,)}
    task.web_queue.send_msg.assert_called_once_with('PROJECT', 'foo')


def test_do_archive_run_skips_missing_files(db, task, archivist_config,
                                             with_files):
    # None of the candidate files exist on disk; the run should not crash,
    # should not update the database, and should not request a rebuild
    task.do_archive_run()

    assert set(db.execute(
        "SELECT location FROM files WHERE package_tag = 'foo'"
    )) == {(const.MASTER_LOCATION,)}
    task.web_queue.send_msg.assert_not_called()
