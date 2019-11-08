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

"""
Defines :class:`TerminalApplication`, a base class for the console applications
in the piwheels suite.
"""

import sys
import locale
import logging
import traceback
from collections import OrderedDict, namedtuple

import configargparse
from configargparse import FileType  # pylint: disable=unused-import

from . import __version__

try:
    import argcomplete
except ImportError:
    argcomplete = None


# Use the user's default locale instead of C
locale.setlocale(locale.LC_ALL, '')

# Set up a console logging handler which just prints messages without any other
# adornments. This will be used for logging messages sent before we "properly"
# configure logging according to the user's preferences
_CONSOLE = logging.StreamHandler(sys.stderr)
_CONSOLE.setFormatter(logging.Formatter('%(message)s'))
_CONSOLE.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_CONSOLE)


class ArgParser(configargparse.ArgParser):
    """
    Overrides the default ArgParser to simply raise an exception in the case
    of usage error
    """
    # pylint: disable=method-hidden
    def error(self, message):
        raise configargparse.ArgumentError(None, message)


class WidthFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style='%', maxwidth=120,
                 ellipsis='...'):
        super().__init__(fmt, datefmt, style)
        self.maxwidth = maxwidth
        self.ellipsis = ellipsis

    def formatMessage(self, record):
        s = super().formatMessage(record)
        if len(s) > self.maxwidth:
            s = s[:self.maxwidth - len(self.ellipsis)] + self.ellipsis
        return s


def configure_parser(description, log_params=True):
    """
    Configure an argument parser with some common options and return it.
    """
    parser = ArgParser(
        description=description,
        add_config_file_help=False,
        add_env_var_help=False,
        default_config_files=[
            '/etc/piwheels.conf',
            '/usr/local/etc/piwheels.conf',
            '~/.config/piwheels/piwheels.conf'
        ],
        ignore_unknown_config_file_keys=True
    )
    parser.add_argument(
        '--version', action='version', version=__version__)
    parser.add_argument(
        '-c', '--configuration', metavar='FILE', default=None,
        is_config_file=True, help='Specify a configuration file to load')
    if log_params:
        parser.set_defaults(log_level=logging.WARNING)
        parser.add_argument(
            '-q', '--quiet', dest='log_level', action='store_const',
            const=logging.ERROR, help='Produce less console output')
        parser.add_argument(
            '-v', '--verbose', dest='log_level', action='store_const',
            const=logging.INFO, help='Produce more console output')
        arg = parser.add_argument(
            '-l', '--log-file', metavar='FILE',
            help='Log messages to the specified file')
        if argcomplete is not None:
            arg.completer = argcomplete.FilesCompleter(['*.log', '*.txt'])
    return parser


def configure_logging(log_level, log_filename=None, console_name=False):
    """
    Configures handlers for logging to the console and any specified log file.
    """
    _CONSOLE.setLevel(log_level)
    _CONSOLE.setFormatter(WidthFormatter(
        '%(name)s: %(message)s' if console_name else '%(message)s'))
    # Yes, this is redundant with the call above but Logger.addHandler checks
    # for (and ignores) dupes
    logging.getLogger().addHandler(_CONSOLE)
    if log_filename is not None:
        log_file = logging.FileHandler(log_filename)
        log_file.setFormatter(WidthFormatter(
            '%(asctime)s %(name)s %(levelname)s: %(message)s'))
        log_file.setLevel(min(logging.INFO, log_level))
        logging.getLogger().addHandler(log_file)
    logging.getLogger().setLevel(min(logging.INFO, log_level))


class ErrorAction(namedtuple('ErrorAction', ('message', 'exitcode'))):
    """
    Named tuple dictating the action to take in response to an unhandled
    exception of the type it is associated with in :class:`ErrorHandler`.
    The *message* is an iterable of lines to be output as critical error
    log messages, and *exitcode* is an integer to return as the exit code of
    the process.

    Either of these can also be functions which will be called with the
    exception info (type, value, traceback) and will be expected to return
    an iterable of lines (for *message*) or an integer (for *exitcode*).
    """
    pass


class ErrorHandler:
    """
    Global configurable application exception handler. For "basic" errors (I/O
    errors, keyboard interrupt, etc.) just the error message is printed as
    there's generally no need to confuse the user with a complete stack trace
    when it's just a missing file. Other exceptions, however, are logged with
    the usual full stack trace.

    The configuration can be augmented with other exception classes that
    should be handled specially by treated the instance as a dictionary mapping
    exception classes to :class:`ErrorAction` tuples.
    """
    def __init__(self):
        self._config = OrderedDict({
            # Exception type:  (handler method, exit code)
            SystemExit:        (None, self.exc_value),
            KeyboardInterrupt: (None, 2),
            IOError:           (self.exc_message, 1),
            configargparse.ArgumentError:
                               (self.syntax_error, 2),
        })

    @staticmethod
    def exc_message(exc_type, exc_value, exc_tb):
        return [exc_value]

    @staticmethod
    def exc_value(exc_type, exc_value, exc_tb):
        return exc_value

    @staticmethod
    def syntax_error(exc_type, exc_value, exc_tb):
        return [exc_value, 'Try the --help option for more information.']

    def __len__(self):
        return len(self._config)

    def __contains__(self, key):
        return key in self._config

    def __getitem__(self, key):
        return self._config[key]

    def __setitem__(self, key, value):
        self._config[key] = ErrorAction(*value)

    def __delitem__(self, key):
        del self._config[key]

    def __call__(self, exc_type, exc_value, exc_tb):
        for exc_class, (message, value) in self._config.items():
            if issubclass(exc_type, exc_class):
                if callable(message):
                    message = message(exc_type, exc_value, exc_tb)
                if callable(value):
                    value = value(exc_type, exc_value, exc_tb)
                if message is not None:
                    for line in message:
                        logging.critical(line)
                return value
        # Otherwise, log the stack trace and the exception into the log
        # file for debugging purposes
        for line in traceback.format_exception(exc_type, exc_value, exc_tb):
            for msg in line.rstrip().split('\n'):
                logging.critical(msg.replace('%', '%%'))
        return 1

error_handler = ErrorHandler()


def yes_no_prompt(question):
    """
    Print a yes/no *question* and return ``True`` (for yes) or ``False`` (for
    no) according to the user's response.
    """
    print('')
    while True:
        try:
            return {
                '': True,
                'y': True,
                'yes': True,
                'n': False,
                'no': False,
            }[input(question + ' [Y/n] ').strip().lower()]
        except KeyError:
            print('Invalid response')
