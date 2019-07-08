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


import sys
import logging
from unittest import mock

import pytest
import configargparse

from piwheels.terminal import (
    _CONSOLE,
    configure_parser,
    configure_logging,
    error_handler,
    yes_no_prompt,
    ErrorHandler,
)


def test_configure_parser():
    p = configure_parser('foo', log_params=False)
    assert p.description == 'foo'
    with pytest.raises(SystemExit):
        p.parse_args(['--version'])
    with pytest.raises(SystemExit):
        p.parse_args(['-h'])
    with pytest.raises(configargparse.ArgumentError):
        p.parse_args(['--log-file', 'foo.log'])
    c = p.parse_args([])
    assert c.configuration is None


def test_configure_parser_with_logging(tmpdir):
    p = configure_parser('foo', log_params=True)
    assert p.description == 'foo'
    with pytest.raises(SystemExit):
        p.parse_args(['--version'])
    with pytest.raises(SystemExit):
        p.parse_args(['-h'])
    c = p.parse_args(['--log-file', str(tmpdir.join('/foo.log'))])
    assert c.log_level == logging.WARNING
    assert c.log_file == str(tmpdir.join('/foo.log'))
    mock_logger = logging.getLogger('mock')
    with mock.patch('logging.getLogger') as m:
        m.return_value = mock_logger
        configure_logging(c.log_level, c.log_file)
        assert len(m.return_value.handlers) == 2
        assert m.return_value.handlers[0] is _CONSOLE
        assert m.return_value.handlers[0].level == logging.WARNING
        assert isinstance(m.return_value.handlers[1], logging.FileHandler)
        assert m.return_value.handlers[1].baseFilename == str(tmpdir.join('/foo.log'))
        assert m.return_value.handlers[1].level == logging.INFO
        assert m.return_value.level == logging.INFO


def test_error_handler():
    with mock.patch('piwheels.terminal.logging') as logging:
        assert error_handler(SystemExit, 0, None) == 0
        assert error_handler(KeyboardInterrupt, 'Ctrl+C pressed', None) == 2
        assert logging.critical.call_count == 0
        assert error_handler(configargparse.ArgumentError, 'foo', None) == 2
        assert logging.critical.call_args_list == [
            mock.call('foo'),
            mock.call('Try the --help option for more information.'),
        ]
        logging.reset_mock()
        assert error_handler(IOError, 'File not found', None) == 1
        assert logging.critical.call_args == mock.call('File not found')
        logging.reset_mock()
        with mock.patch('traceback.format_exception') as fmt_exc:
            fmt_exc.side_effect = lambda t, v, tb: [v]
            assert error_handler(ValueError, 'Foo%bar', None) == 1
            assert logging.critical.call_args == mock.call('Foo%%bar')


def test_configure_error_handler():
    e = ErrorHandler()
    l = len(e)
    assert RuntimeError not in e
    try:
        raise RuntimeError('Error communicating with master')
    except RuntimeError:
        assert e(*sys.exc_info()) == 1
    e[RuntimeError] = (None, 2)
    assert len(e) == l + 1
    assert e[RuntimeError] == (None, 2)
    try:
        raise RuntimeError('Error communicating with master')
    except RuntimeError:
        assert e(*sys.exc_info()) == 2


def test_yes_no_prompt(capsys):
    with mock.patch('builtins.input') as _input:
        _input.return_value = ''
        assert yes_no_prompt('Foo') == True
        assert _input.call_args == mock.call('Foo [Y/n] ')
        out, err = capsys.readouterr()
        assert out == '\n'
        _input.side_effect = ['foo', 'NO']
        assert yes_no_prompt('Bar') == False
        out, err = capsys.readouterr()
        assert out == '\nInvalid response\n'
