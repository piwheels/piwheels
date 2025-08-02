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

import pytest

from conftest import find_messages
from piwheels.audit.report import report_missing, report_broken

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

# def test_report(output, simple, caplog, missing, extra):
#     class Config:
#         pass
#     config = Config()
#     with missing.open('w') as missing_f, extra.open('w') as extra_f:
#         config.missing = missing_f
#         config.extraneous = extra_f
#         config.broken = None
#         report_missing(config, 'package', output / 'foo' / 'foo-0.1.whl')
#         assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1
#         assert missing_f.tell()
#         caplog.clear()
#         report_broken(config, 'package', output / 'foo' / 'foo-0.1.whl')
#         assert len(list(find_messages(caplog.records, levelname='ERROR'))) == 1