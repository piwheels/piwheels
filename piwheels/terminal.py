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

import os
import sys
import locale
import logging
import argparse
import traceback
from configparser import ConfigParser

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
_CONSOLE.setFormatter(logging.Formatter('%(name)s: %(message)s'))
_CONSOLE.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_CONSOLE)


class TerminalApplication:
    """
    Base class for piwheels applications.

    This class provides command line parsing, file globbing, response file
    handling and common logging configuration for command line utilities.
    Descendent classes should override the main() method to implement their
    main body, and __init__() if they wish to extend the command line options.
    """
    # Get the default output encoding from the default locale
    encoding = locale.getdefaultlocale()[1]

    # This class is the abstract base class for each of the command line
    # utility classes defined. It provides some basic facilities like an option
    # parser, console pretty-printing, logging and exception handling

    def __init__(self, version, description=None, log_params=True):
        super(TerminalApplication, self).__init__()
        if description is None:
            description = self.__doc__
        self.logger = logging.getLogger()
        self.parser = argparse.ArgumentParser(
            description=description,
            fromfile_prefix_chars='@')
        self.parser.add_argument(
            '--version', action='version', version=version)
        self.parser.set_defaults(log_level=logging.WARNING)
        if log_params:
            self.parser.add_argument(
                '-q', '--quiet', dest='log_level', action='store_const',
                const=logging.ERROR, help='produce less console output')
            self.parser.add_argument(
                '-v', '--verbose', dest='log_level', action='store_const',
                const=logging.INFO, help='produce more console output')
        self.parser.add_argument(
            '-c', '--configuration', metavar='FILE', default=None,
            help='Specify a configuration file to load')
        arg = self.parser.add_argument(
            '-l', '--log-file', metavar='FILE',
            help='log messages to the specified file')
        if argcomplete:
            arg.completer = argcomplete.FilesCompleter(['*.log', '*.txt'])
        self.parser.add_argument(
            '-P', '--pdb', dest='debug', action='store_true', default=False,
            help='run under PDB (debug mode)')

    def __call__(self, args=None):
        if args is None:
            args = sys.argv[1:]
        if argcomplete:
            argcomplete.autocomplete(self.parser, exclude=['-P'])
        elif 'COMP_LINE' in os.environ:
            return 0
        sys.excepthook = self.handle
        args = self.parser.parse_args(args)
        self.configure_logging(args)
        config = self.load_configuration(args)
        if args.debug:
            try:
                import pudb
            except ImportError:
                pudb = None
                import pdb
            return (pudb or pdb).runcall(self.main, args, config)
        else:
            return self.main(args, config) or 0

    def configure_logging(self, args):
        """
        Configures handlers for logging to the console and any specified log
        file. Log level is set according to the specified *args*.
        """
        _CONSOLE.setLevel(args.log_level)
        if args.log_file:
            log_file = logging.FileHandler(args.log_file)
            log_file.setFormatter(
                logging.Formatter('%(asctime)s %(name)s %(levelname)s: '
                                  '%(message)s'))
            log_file.setLevel(logging.DEBUG)
            self.logger.addHandler(log_file)
        if args.debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

    def handle(self, exc_type, exc_value, exc_trace):
        """
        Global application exception handler. For "basic" errors (I/O errors,
        keyboard interrupt, etc.) just the error message is printed as there's
        generally no need to confuse the user with a complete stack trace when
        it's just a missing file. Other exceptions, however, are logged with
        the usual full stack trace.
        """
        if issubclass(exc_type, (SystemExit,)):
            # Exit with 0 ("success") for system exit (as it was intentional)
            return 0
        elif issubclass(exc_type, (KeyboardInterrupt,)):
            # Exit with 2 if the user deliberately terminates with Ctrl+C
            return 2
        elif issubclass(exc_type, (argparse.ArgumentError,)):
            # For option parser errors output the error along with a message
            # indicating how the help page can be displayed
            self.logger.critical(str(exc_value))
            self.logger.critical('Try the --help option for more information.')
            return 2
        elif issubclass(exc_type, (IOError,)):
            # For simple errors like IOError just output the message which
            # should be sufficient for the end user (no need to confuse them
            # with a full stack trace)
            self.logger.critical(str(exc_value))
            return 1
        else:
            # Otherwise, log the stack trace and the exception into the log
            # file for debugging purposes
            for line in traceback.format_exception(
                    exc_type, exc_value, exc_trace):
                for msg in line.rstrip().split('\n'):
                    self.logger.critical(msg.replace('%', '%%'))
            return 1

    def load_configuration(self, args, default=None):
        """
        Fill the configuration parser from *default* (if any, defaults to
        ``None``) then load the configuration file specified by *args* (if
        any).
        """
        parser = ConfigParser(interpolation=None)
        if default is None:
            default = {}
        for section, section_items in default.items():
            parser.add_section(section)
            parser[section].update(section_items)
        if args.configuration is not None:
            config_files = parser.read(args.configuration)
        else:
            config_files = parser.read([
                '/etc/piwheels.conf',
                '/usr/local/etc/piwheels.conf',
                os.path.expanduser('~/.config/piwheels/piwheels.conf'),
            ])
        for f in config_files:
            self.logger.info('read configuration from %s', f)
        return parser

    def main(self, args, config):
        """
        Called as the main body of the utility. Override this in descendents.
        """
        raise NotImplementedError
