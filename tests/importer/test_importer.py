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
import pickle
import zipfile
from unittest import mock
from pathlib import Path

import zmq
import pytest

from piwheels import __version__
from piwheels.importer import *


@pytest.fixture()
def mock_wheel(request, tmpdir):
    filename = str(tmpdir.join('foo-0.1-cp34-cp34m-linux_armv7l.whl'))
    with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_STORED) as arc:
        arc.writestr('foo/__init__.py', b'\x00' * 123456)
        arc.writestr('foo-0.1.dist-info/METADATA', """\
Metadata-Version: 2.0
Name: foo
Version: 0.1
Summary: A test package
Home-page: http://foo.com/
Author: Some foo
Author-email: foo@foo.com
License: BSD
Platform: any
Classifier: Development Status :: 5 - Production/Stable
Classifier: Intended Audience :: Developers
Classifier: License :: OSI Approved :: BSD License
Classifier: Operating System :: OS Independent
Classifier: Programming Language :: Python

""")
    return filename


def find_message(records, message):
    return any(record.message == message for record in records)


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--package' in out
    assert '--package-version' in out
    assert '--abi' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_abort(mock_wheel):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        assert main([mock_wheel]) == 2


def test_auto_package_version(mock_wheel, caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        main([mock_wheel])
    assert find_message(caplog.records, 'Package:  foo')
    assert find_message(caplog.records, 'Version:  0.1')


def test_manual_package_version(mock_wheel, caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        main(['--package', 'bar', '--package-version', '0.2', mock_wheel])
    assert find_message(caplog.records, 'Package:  bar')
    assert find_message(caplog.records, 'Version:  0.2')
