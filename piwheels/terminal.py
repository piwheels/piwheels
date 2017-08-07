import os
import sys
import locale
import logging
import argparse
import traceback
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


class TerminalApplication:
    """
    Base class for command line applications.

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
        if args.debug:
            try:
                import pudb
            except ImportError:
                pudb = None
                import pdb
            return (pudb or pdb).runcall(self.main, args)
        else:
            return self.main(args) or 0

    def configure_logging(self, args):
        _CONSOLE.setLevel(args.log_level)
        if args.log_file:
            log_file = logging.FileHandler(args.log_file)
            log_file.setFormatter(
                logging.Formatter('%(asctime)s, %(levelname)s, %(message)s'))
            log_file.setLevel(logging.DEBUG)
            logging.getLogger().addHandler(log_file)
        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.INFO)

    def handle(self, exc_type, exc_value, exc_trace):
        "Global application exception handler"
        if issubclass(exc_type, (SystemExit,)):
            # Exit with 0 ("success") for system exit (as it was intentional)
            return 0
        elif issubclass(exc_type, (KeyboardInterrupt,)):
            # Exit with 2 if the user deliberately terminates with Ctrl+C
            return 2
        elif issubclass(exc_type, (argparse.ArgumentError,)):
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

    def main(self, args):
        "Called as the main body of the utility"
        raise NotImplementedError


