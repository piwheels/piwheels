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
            const=logging.ERROR, help='produce less console output')
        parser.add_argument(
            '-v', '--verbose', dest='log_level', action='store_const',
            const=logging.INFO, help='produce more console output')
        arg = parser.add_argument(
            '-l', '--log-file', metavar='FILE',
            help='log messages to the specified file')
        if argcomplete is not None:
            arg.completer = argcomplete.FilesCompleter(['*.log', '*.txt'])
    return parser


def configure_logging(log_level, log_filename=None):
    """
    Configures handlers for logging to the console and any specified log file.
    """
    _CONSOLE.setLevel(log_level)
    if log_filename is not None:
        log_file = logging.FileHandler(log_filename)
        log_file.setFormatter(logging.Formatter(
            '%(asctime)s %(name)s %(levelname)s: %(message)s'))
        log_file.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(log_file)
    logging.getLogger().setLevel(logging.INFO)


def error_handler(exc_type, exc_value, exc_trace):
    """
    Global application exception handler. For "basic" errors (I/O errors,
    keyboard interrupt, etc.) just the error message is printed as there's
    generally no need to confuse the user with a complete stack trace when it's
    just a missing file. Other exceptions, however, are logged with the usual
    full stack trace.
    """
    if issubclass(exc_type, (SystemExit,)):
        # Exit with whatever exit code the exception holds
        return exc_value
    elif issubclass(exc_type, (KeyboardInterrupt,)):
        # Exit with 2 if the user deliberately terminates with Ctrl+C
        return 2
    elif issubclass(exc_type, (configargparse.ArgumentError,)):
        # For option parser errors output the error along with a message
        # indicating how the help page can be displayed
        logging.critical(str(exc_value))
        logging.critical('Try the --help option for more information.')
        return 2
    elif issubclass(exc_type, (IOError,)):
        # For simple errors like IOError just output the message which
        # should be sufficient for the end user (no need to confuse them
        # with a full stack trace)
        logging.critical(str(exc_value))
        return 1
    else:
        # Otherwise, log the stack trace and the exception into the log
        # file for debugging purposes
        for line in traceback.format_exception(exc_type, exc_value, exc_trace):
            for msg in line.rstrip().split('\n'):
                logging.critical(msg.replace('%', '%%'))
        return 1


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
