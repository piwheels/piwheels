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
import logging
import hashlib
from queue import Queue
from pathlib import Path
from unittest import mock
from threading import Thread

import pytest

from conftest import find_messages
from piwheels import __version__
from piwheels.audit import *


@pytest.fixture()
def output(tmpdir):
    return Path(str(tmpdir))


@pytest.fixture()
def simple(output):
    (output / 'simple').mkdir()
    return output / 'simple'


@pytest.fixture()
def missing(simple):
    return simple / 'missing.txt'


@pytest.fixture()
def extra(simple):
    return simple / 'extra.txt'


@pytest.fixture()
def broken(simple):
    return simple / 'broken.txt'


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--extraneous' in out
    assert '--missing' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_report(output, simple, caplog, missing, extra):
    class Config:
        pass
    config = Config()
    with missing.open('w') as missing_f, extra.open('w') as extra_f:
        config.missing = missing_f
        config.extraneous = extra_f
        config.broken = None
        report_missing(config, 'package', output / 'foo' / 'foo-0.1.whl')
        assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
        assert missing_f.tell()
        caplog.clear()
        report_broken(config, 'package', output / 'foo' / 'foo-0.1.whl')
        assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1


def test_index_parser():
    data = """\
<html><body>
<a name="start"></a>
<a href="foo-0.1-py3-none-any.whl#sha256=abcdefghijkl">foo-0.1-py3-none-any.whl</a>
<a class="yanked" href="foo-0.2-py3-none-any.whl#sha256=abcdefghijkl">foo-0.2-py3-none-any.whl</a>
<a href="foo-0.2.1-py3-none-any.whl#sha256=abcdefghijkl">foo-0.2.1-py3-none-any.whl</a>
<a class="prerelease" href="foo-0.3b-py3-none-any.whl#sha256=abcdefghijkl">foo-0.3b-py3-none-any.whl</a>
<a href="foo-0.3-py3-none-any.whl#sha256=abcdefghijkl">foo-0.3-py3-none-any.whl</a>
<a href="foo-0.4-py3-none-any.whl#sha256=abcdefghijkl">foo-0.4-py3-none-any.whl</a>
<a name="end"></a>
</body></html>"""
    queue = Queue()
    parser = IndexParser(queue)
    for i in range(0, len(data), 16):
        # Deliberately feed in chunks to make sure the parser handles this
        # correctly
        parser.feed(data[i:i + 16])
    assert queue.get(block=False) == (
        'foo-0.1-py3-none-any.whl#sha256=abcdefghijkl', 'foo-0.1-py3-none-any.whl')
    assert queue.get(block=False) == (
        'foo-0.2-py3-none-any.whl#sha256=abcdefghijkl', 'foo-0.2-py3-none-any.whl')
    assert queue.get(block=False) == (
        'foo-0.2.1-py3-none-any.whl#sha256=abcdefghijkl', 'foo-0.2.1-py3-none-any.whl')
    assert queue.get(block=False) == (
        'foo-0.3b-py3-none-any.whl#sha256=abcdefghijkl', 'foo-0.3b-py3-none-any.whl')
    assert queue.get(block=False) == (
        'foo-0.3-py3-none-any.whl#sha256=abcdefghijkl', 'foo-0.3-py3-none-any.whl')
    assert queue.get(block=False) == (
        'foo-0.4-py3-none-any.whl#sha256=abcdefghijkl', 'foo-0.4-py3-none-any.whl')


def test_missing_simple_index(output, simple, caplog, missing, extra):
    main(['-o', str(output), '-m', str(missing), '-e', str(extra)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
    assert missing.read_text() == str(simple / 'index.html') + '\n'
    assert extra.read_text() == ''


def test_missing_package_dir(output, simple, caplog, missing, extra):
    (simple / 'index.html').write_text("""\
<html>
<body>
<a href="foo">foo</a>
</body>
</html>""")
    package_dir = simple / 'foo'
    main(['-o', str(output), '-m', str(missing), '-e', str(extra)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
    assert missing.read_text() == str(package_dir) + '\n'
    assert extra.read_text() == ''


def test_missing_package_index(output, simple, caplog, missing, extra):
    (simple / 'index.html').write_text("""\
<html>
<body>
<a href="foo">foo</a>
</body>
</html>""")
    package_dir = simple / 'foo'
    package_dir.mkdir()
    main(['-o', str(output), '-m', str(missing), '-e', str(extra)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
    assert missing.read_text() == str(package_dir / 'index.html') + '\n'
    assert extra.read_text() == ''


def test_missing_wheel_file(output, simple, caplog, missing, extra):
    (simple / 'index.html').write_text("""\
<html>
<body>
<a href="foo">foo</a>
</body>
</html>""")
    package_dir = simple / 'foo'
    package_dir.mkdir()
    (package_dir / 'index.html').write_text("""\
<html>
<body>
<a href="foo-0.1-py3-none-any.whl#sha256=abcdefghijkl">foo-0.1-py3-none-any.whl</a>
</body>
</html>""")
    main(['-o', str(output), '-m', str(missing), '-e', str(extra)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
    assert missing.read_text() == str(package_dir / 'foo-0.1-py3-none-any.whl') + '\n'
    assert extra.read_text() == ''


def test_unchecked_wheel_file(output, simple, caplog, missing, extra):
    (simple / 'index.html').write_text("""\
<html>
<body>
<a href="foo">foo</a>
</body>
</html>""")
    package_dir = simple / 'foo'
    package_dir.mkdir()
    (package_dir / 'index.html').write_text("""\
<html>
<body>
<a href="foo-0.1-py3-none-any.whl#sha256=abcdefghijkl">foo-0.1-py3-none-any.whl</a>
</body>
</html>""")
    (package_dir / 'foo-0.1-py3-none-any.whl').touch()
    main(['-o', str(output), '-m', str(missing), '-e', str(extra)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 0
    assert missing.read_text() == ''
    assert extra.read_text() == ''


def test_extraneous_wheel_file(output, simple, caplog, missing, extra):
    (simple / 'index.html').write_text("""\
<html>
<body>
<a href="foo">foo</a>
</body>
</html>""")
    package_dir = simple / 'foo'
    package_dir.mkdir()
    (package_dir / 'index.html').write_text("""\
<html>
<body>
<a href="foo-0.1-py3-none-any.whl#sha256=abcdefghijkl">foo-0.1-py3-none-any.whl</a>
</body>
</html>""")
    (package_dir / 'foo-0.1-py3-none-any.whl').touch()
    (package_dir / 'foo-0.2-py3-none-any.whl').touch()
    main(['-o', str(output), '-m', str(missing), '-e', str(extra)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
    assert missing.read_text() == ''
    assert extra.read_text() == str(package_dir / 'foo-0.2-py3-none-any.whl') + '\n'


def test_invalid_wheel_hash(output, simple, caplog, missing, extra, broken):
    (simple / 'index.html').write_text("""\
<html>
<body>
<a href="foo">foo</a>
</body>
</html>""")
    package_dir = simple / 'foo'
    package_dir.mkdir()
    (package_dir / 'index.html').write_text("""\
<html>
<body>
<a href="foo-0.1-py3-none-any.whl#sha512=0123456789abcdef">foo-0.1-py3-none-any.whl</a>
</body>
</html>""")
    (package_dir / 'foo-0.1-py3-none-any.whl').touch()
    main(['-o', str(output), '-m', str(missing), '-e', str(extra), '-b', str(broken)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
    assert missing.read_text() == ''
    assert extra.read_text() == ''
    assert broken.read_text() == str(package_dir / 'foo-0.1-py3-none-any.whl') + '\n'


def test_invalid_wheel_file(output, simple, caplog, missing, extra, broken):
    (simple / 'index.html').write_text("""\
<html>
<body>
<a href="foo">foo</a>
</body>
</html>""")
    package_dir = simple / 'foo'
    package_dir.mkdir()
    (package_dir / 'index.html').write_text("""\
<html>
<body>
<a href="foo-0.1-py3-none-any.whl#sha256=0123456789abcdef">foo-0.1-py3-none-any.whl</a>
</body>
</html>""")
    (package_dir / 'foo-0.1-py3-none-any.whl').touch()
    main(['-o', str(output), '-m', str(missing), '-e', str(extra), '-b', str(broken)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
    assert missing.read_text() == ''
    assert extra.read_text() == ''
    assert broken.read_text() == str(package_dir / 'foo-0.1-py3-none-any.whl') + '\n'


def test_good_wheel_file(output, simple, caplog, missing, extra, broken):
    sha256 = hashlib.sha256()
    (simple / 'index.html').write_text("""\
<html>
<body>
<a href="foo">foo</a>
</body>
</html>""")
    package_dir = simple / 'foo'
    package_dir.mkdir()
    (package_dir / 'foo-0.1-py3-none-any.whl').write_bytes(b'\x00' * 10000)
    sha256.update(b'\x00' * 10000)
    (package_dir / 'index.html').write_text("""\
<html>
<body>
<a href="foo-0.1-py3-none-any.whl#sha256={hash}">foo-0.1-py3-none-any.whl</a>
</body>
</html>""".format(hash=sha256.hexdigest()))
    main(['-o', str(output), '-m', str(missing), '-e', str(extra), '-b', str(broken)])
    assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 0
    assert missing.read_text() == ''
    assert extra.read_text() == ''
    assert broken.read_text() == ''
