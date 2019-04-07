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


import io
import gzip
from unittest import mock
from datetime import datetime, timezone

import pytest

from piwheels import __version__, protocols, transport
from piwheels.logger import main


UTC = timezone.utc


@pytest.fixture()
def log_sample():
    log = r"""\
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:24:56 +0000] "GET /simple/markupsafe/ HTTP/1.1" 200 2655 "-" "pip/9.0.1 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"3.5.3\"},\"installer\":{\"name\":\"pip\",\"version\":\"9.0.1\"},\"openssl_version\":\"OpenSSL 1.1.0j  20 Nov 2018\",\"python\":\"3.5.3\",\"system\":{\"name\":\"Linux\",\"release\":\"4.14.79-v7+\"}}"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:24:56 +0000] "GET /simple/certifi/ HTTP/1.1" 200 2222 "-" "pip/19.0.3 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"2.7.13\"},\"installer\":{\"name\":\"pip\",\"version\":\"19.0.3\"},\"openssl_version\":\"OpenSSL 1.1.0j  20 Nov 2018\",\"python\":\"2.7.13\",\"setuptools_version\":\"40.8.0\",\"system\":{\"name\":\"Linux\",\"release\":\"4.14.98-v7+\"}}"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:24:56 +0000] "GET /simple/markupsafe/MarkupSafe-1.1.1-cp35-cp35m-linux_armv7l.whl HTTP/1.1" 200 32003 "-" "pip/9.0.1 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"3.5.3\"},\"installer\":{\"name\":\"pip\",\"version\":\"9.0.1\"},\"openssl_version\":\"OpenSSL 1.1.0j  20 Nov 2018\",\"python\":\"3.5.3\",\"system\":{\"name\":\"Linux\",\"release\":\"4.14.79-v7+\"}}"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:24:56 +0000] "GET /simple/asn1crypto/ HTTP/1.1" 200 1811 "-" "pip/9.0.1 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"2.7.13\"},\"installer\":{\"name\":\"pip\",\"version\":\"9.0.1\"},\"openssl_version\":\"OpenSSL 1.1.0j  20 Nov 2018\",\"python\":\"2.7.13\",\"system\":{\"name\":\"Linux\",\"release\":\"4.14.79-v7+\"}}"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:24:57 +0000] "GET /simple/backports-abc/ HTTP/1.1" 200 794 "-" "pip/19.0.3 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"2.7.13\"},\"installer\":{\"name\":\"pip\",\"version\":\"19.0.3\"},\"openssl_version\":\"OpenSSL 1.1.0j  20 Nov 2018\",\"python\":\"2.7.13\",\"setuptools_version\":\"40.8.0\",\"system\":{\"name\":\"Linux\",\"release\":\"4.14.98-v7+\"}}"
2a00:1098:0:82:1000:3b:1:1 - - [18/Mar/2019:14:24:58 +0000] "GET /simple/pip/ HTTP/1.1" 200 7973 "-" "pip/19.0.3 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"3.5.3\"},\"installer\":{\"name\":\"pip\",\"version\":\"19.0.3\"},\"openssl_version\":\"OpenSSL 1.1.0j  20 Nov 2018\",\"python\":\"3.5.3\",\"setuptools_version\":\"33.1.1\",\"system\":{\"name\":\"Linux\",\"release\":\"4.14.98-v7+\"}}"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:26:04 +0000] "GET /simple/pyyaml/PyYAML-3.13-cp35-cp35m-linux_armv7l.whl HTTP/1.1" 200 42641 "-" "pip/19.0.3 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"3.5.3\"},\"installer\":{\"name\":\"pip\",\"version\":\"19.0.3\"},\"openssl_version\":\"OpenSSL 1.1.0j  20 Nov 2018\",\"python\":\"3.5.3\",\"setuptools_version\":\"33.1.1\",\"system\":{\"name\":\"Linux\",\"release\":\"4.19.27-v7+\"}}"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:26:05 +0000] "GET /simple/pip/ HTTP/1.1" 200 7973 "-" "pip/18.0 {\"cpu\":\"armv6l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"2.7.13\"},\"installer\":{\"name\":\"pip\",\"version\":\"18.0\"},\"openssl_version\":\"OpenSSL 1.1.0f  25 May 2017\",\"python\":\"2.7.13\",\"setuptools_version\":\"40.0.0\",\"system\":{\"name\":\"Linux\",\"release\":\"4.14.52+\"}}"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:26:06 +0000] "GET /simple/lxml/ HTTP/1.1" 200 8015 "-" "pip/19.0.3 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"3.6.8\"},\"installer\":{\"name\":\"pip\",\"version\":\"19.0.3\"},\"openssl_version\":\"OpenSSL 1.1.0j  20 Nov 2018\",\"python\":\"3.6.8\",\"setuptools_version\":\"40.8.0\",\"system\":{\"name\":\"Linux\",\"release\":\"4.9.93-linuxkit-aufs\"}}"
2a00:1098:0:82:1000:3b:1:1 - - [18/Mar/2019:14:26:06 +0000] "GET /simple/cffi/ HTTP/1.1" 200 10390 "-" "pip/9.0.1 {\"cpu\":\"armv7l\",\"distro\":{\"id\":\"stretch\",\"libc\":{\"lib\":\"glibc\",\"version\":\"2.24\"},\"name\":\"Raspbian GNU/Linux\",\"version\":\"9\"},\"implementation\":{\"name\":\"CPython\",\"version\":\"2.7.13\"},\"installer\":{\"name\":\"pip\",\"version\":\"9.0.1\"},\"openssl_version\":\"OpenSSL 1.1.0f  25 May 2017\",\"python\":\"2.7.13\",\"system\":{\"name\":\"Linux\",\"release\":\"4.14.79-v7+\"}}"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:26:26 +0000] "GET /simple/foo/foo-0.1-cp34-none-any.whl HTTP/1.1" 200 42641 "-" "pip/ancient no JSON UA"
2a00:1098:0:80:1000:3b:1:1 - - [18/Mar/2019:14:26:28 +0000] "GET /simple/foo/foo-0.2-cp34-none-any.whl HTTP/1.1" 200 42641 "-" "pip/evil {invalid JSON}"
"""
    downloads = [
        [
            'MarkupSafe-1.1.1-cp35-cp35m-linux_armv7l.whl',
            '2a00:1098:0:80:1000:3b:1:1',
            datetime(2019, 3, 18, 14, 24, 56, tzinfo=UTC),
            'armv7l',
            'Raspbian GNU/Linux', '9',
            'Linux', '4.14.79-v7+',
            'CPython', '3.5.3',
        ],
        [
            'PyYAML-3.13-cp35-cp35m-linux_armv7l.whl',
            '2a00:1098:0:80:1000:3b:1:1',
            datetime(2019, 3, 18, 14, 26, 4, tzinfo=UTC),
            'armv7l',
            'Raspbian GNU/Linux', '9',
            'Linux', '4.19.27-v7+',
            'CPython', '3.5.3',
        ],
        [
            'foo-0.1-cp34-none-any.whl',
            '2a00:1098:0:80:1000:3b:1:1',
            datetime(2019, 3, 18, 14, 26, 26, tzinfo=UTC),
            None,
            None, None,
            None, None,
            'CPython', None,
        ],
        [
            'foo-0.2-cp34-none-any.whl',
            '2a00:1098:0:80:1000:3b:1:1',
            datetime(2019, 3, 18, 14, 26, 28, tzinfo=UTC),
            None,
            None, None,
            None, None,
            'CPython', None,
        ]
    ]
    return log, downloads


@pytest.fixture()
def logger_queue_name(request, tmpdir):
    yield 'ipc://' + str(tmpdir.join('logger-queue'))


@pytest.fixture()
def logger_queue(request, mock_context, logger_queue_name, tmpdir):
    queue = mock_context.socket(transport.PULL, protocol=protocols.lumberjack)
    queue.hwm = 1
    queue.bind(logger_queue_name)
    yield queue
    queue.close()


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--drop' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_parse_stdin(logger_queue_name, logger_queue, log_sample):
    log, downloads = log_sample
    with mock.patch('sys.stdin', io.StringIO(log)):
        main(['--log-queue', logger_queue_name])
        for download in downloads:
            assert logger_queue.recv_msg() == ('LOG', download)


def test_parse_file(logger_queue_name, logger_queue, log_sample, tmpdir):
    log, downloads = log_sample
    with tmpdir.join('log.txt').open('w') as f:
        f.write(log)
    main(['--log-queue', logger_queue_name, str(tmpdir.join('log.txt'))])
    for download in downloads:
        assert logger_queue.recv_msg() == ('LOG', download)


def test_parse_compressed(logger_queue_name, logger_queue, log_sample, tmpdir):
    log, downloads = log_sample
    with tmpdir.join('log.gz').open('wb') as f:
        f.write(gzip.compress(log.encode('ascii')))
    main(['--log-queue', logger_queue_name, str(tmpdir.join('log.gz'))])
    for download in downloads:
        assert logger_queue.recv_msg() == ('LOG', download)
