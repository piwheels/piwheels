import cmd
import readline
import logging
from pathlib import Path

from ..terminal import _CONSOLE


class CmdError(Exception):
    "Base class for non-fatal Cmd errors"


class CmdSyntaxError(CmdError):
    "Exception raised when the user makes a syntax error"


class CmdHandler(logging.Handler):
    def __init__(self, cmd, level=logging.NOTSET):
        super().__init__(level)
        self.cmd = cmd

    def emit(self, record):
        self.cmd.pprint(record.msg % record.args)


class Cmd(cmd.Cmd):
    "An enhanced version of the standard Cmd command line processor"
    history_file = None
    history_size = 1000 # <0 implies infinite size

    def __init__(self):
        super().__init__()
        self._width = None
        self._wrapper = TextWrapper()
        self.logging_handler = CmdHandler(self, logging.DEBUG)

    def default(self, line):
        raise CmdSyntaxError('Syntax error: {}'.format(line))

    def emptyline(self):
        # Do not repeat commands when given an empty line
        pass

    def preloop(self):
        if self.history_file and Path(self.history_file).exists():
            readline.read_history_file(self.history_file)
        # Replace the _CONSOLE logging handler with something that calls pprint
        logging.getLogger().addHandler(self.logging_handler)
        logging.getLogger().removeHandler(_CONSOLE)
        # Replace warnings.showwarning with something that calls pprint
        self._showwarning = warnings.showwarning
        warnings.showwarning = self.showwarning

    def postloop(self):
        if self.history_file:
            readline.set_history_length(self.history_size)
            readline.write_history_file(self.history_file)
        # Restore the warnings.showwarning handler
        warnings.showwarning = self._showwarning
        # Restore the _CONSOLE handler
        logging.getLogger().addHandler(_CONSOLE)
        logging.getLogger().removeHandler(self.logging_handler)

    def onecmd(self, line):
        # Just catch and report CmdError's; don't terminate execution because
        # of them
        try:
            return cmd.Cmd.onecmd(self, line)
        except CmdError as exc:
            self.pprint(str(exc) + '\n')

    def showwarning(self, message, category, filename, lineno, file=None,
            line=None):
        logging.warning(str(message))

    def _get_width(self):
        if self._width:
            return self._width
        else:
            try:
                result = int(os.environ['COLUMNS'])
            except (KeyError, ValueError):
                result = 80
            return result - 2
    def _set_width(self, value):
        self._width = value
    width = property(
        _get_width, _set_width, doc="Determine or set the terminal width")

    whitespace_re = re.compile(r'\s+$')
    def wrap(self, s, newline=True, wrap=True, initial_indent='',
            subsequent_indent=''):
        "Wraps a paragraph of text to the terminal"
        suffix = ''
        if newline:
            suffix = '\n'
        elif wrap:
            match = self.whitespace_re.search(s)
            if match:
                suffix = match.group()
        if wrap:
            self._wrapper.width = self.width
            self._wrapper.initial_indent = initial_indent
            self._wrapper.subsequent_indent = subsequent_indent
            s = self._wrapper.fill(s)
        return s + suffix

    def input(self, prompt=''):
        "Prompts and reads input from the user"
        lines = self.wrap(prompt, newline=False).split('\n')
        prompt = lines[-1]
        s = ''.join(line + '\n' for line in lines[:-1])
        self.stdout.write(s)
        return input(prompt).strip()

    def pprint(self, s, newline=True, wrap=True,
            initial_indent='', subsequent_indent=''):
        "Pretty-prints text to the terminal"
        s = self.wrap(s, newline, wrap, initial_indent, subsequent_indent)
        self.stdout.write(s)

    def pprint_table(self, data, header_rows=1, footer_rows=0):
        "Pretty-prints a table of data"
        # Calculate the maximum length of each column. Note that zip(*data) is
        # a quick trick for transposing a list of lists, assuming each row in
        # data is of equal length
        lengths = [
            max(len(str(item)) for item in row)
            for row in zip(*data)
            ]
        # Take a copy of data that we can insert header and footer lines into
        data = list(data)
        if header_rows > 0:
            data.insert(header_rows, tuple('-' * i for i in lengths))
        if footer_rows > 0:
            data.insert(-footer_rows, tuple('-' * i for i in lengths))
        # Print the result. Note that we avoid pprint here as we deliberately
        # don't want to wrap anything (in the vague hope that the terminal is
        # wide enough).
        # XXX Improve algorithm to reduce column widths when terminal is slim
        for row in data:
            s = ' '.join(
                '%-*s' % (length, s) for (length, s) in zip(lengths, row)
                ) + '\n'
            self.stdout.write(s)

    def parse_bool(self, value, default=None):
        """
        Parse a string containing a boolean value.

        Given a string representing a boolean value, this method returns True
        or False, or raises a ValueError if the conversion cannot be performed.
        """
        value = value.lower()
        if value == '' and default is not None:
            return default
        elif value in set(('0', 'false', 'off', 'no', 'n')):
            return False
        elif value in set(('1', 'true', 'on', 'yes', 'y')):
            return True
        else:
            raise ValueError(
                'Invalid boolean expression {}'.format(value))

    def parse_number_range(self, s):
        """
        Parse a dash-separated number range.

        Given a string containing two dash-separated numbers, returns the integer
        value of the start and end of the range.
        """
        try:
            start, finish = (int(i) for i in s.split('-', 1))
        except ValueError as exc:
            raise CmdSyntaxError(exc)
        if finish < start:
            raise CmdSyntaxError(
                '{}-{} range goes backwards'.format(start, finish))
        return start, finish

    def parse_number_list(self, s):
        """
        Parse a comma-separated list of dash-separated number ranges.

        Given a string containing comma-separated numbers or ranges of numbers,
        returns a sequence of all specified numbers (ranges of numbers are expanded
        by this method).
        """
        result = []
        for i in s.split(','):
            if '-' in i:
                start, finish = self.parse_number_range(i)
                result.extend(range(start, finish + 1))
            else:
                try:
                    result.append(int(i))
                except ValueError as exc:
                    raise CmdSyntaxError(exc)
        return result

    def parse_docstring(self, docstring):
        "Utility method for converting docstrings into help-text"
        lines = [line.strip() for line in docstring.strip().splitlines()]
        result = ['']
        for line in lines:
            if result:
                if line:
                    if line.startswith(self.prompt):
                        if result[-1]:
                            result.append(line)
                        else:
                            result[-1] = line
                    else:
                        if result[-1]:
                            result[-1] += ' ' + line
                        else:
                            result[-1] = line
                else:
                    result.append('')
        if not result[-1]:
            result = result[:-1]
        return result

    def do_help(self, arg):
        """
        Displays the available commands or help on a specified command.

        Syntax: help [command]

        The 'help' command is used to display the help text for a command or,
        if no command is specified, it presents a list of all available
        commands along with a brief description of each.
        """
        if arg:
            if not hasattr(self, 'do_{}'.format(arg)):
                raise CmdError('Unknown command {}'.format(arg))
            paras = self.parse_docstring(
                getattr(self, 'do_{}'.format(arg)).__doc__)
            for para in paras[1:]:
                if para.startswith(self.prompt):
                    self.pprint('  ' + para, wrap=False)
                else:
                    self.pprint(para)
                    self.pprint('')
            if paras[-1].startswith(self.prompt):
                self.pprint('')
        else:
            commands = [
                (
                    method[3:],
                    self.parse_docstring(getattr(self, method).__doc__)[0]
                    )
                for method in self.get_names()
                if method.startswith('do_')
                and method != 'do_EOF'
                ]
            # Size the column containing the method names, ensuring it is no
            # wider than one third of the terminal width
            maxlen = min(
                max(len(command) for (command, help) in commands) + 2,
                self.width / 3
                )
            indent = ' ' * maxlen
            for (command, help_text) in commands:
                if len(command) <= maxlen:
                    self.pprint('%-*s%s' % (maxlen, command, help_text),
                        subsequent_indent=indent)
                else:
                    self.pprint(command)
                    self.pprint(help_text, initial_indent=indent,
                        subsequent_indent=indent)

    def do_exit(self, arg):
        """
        Exits from the application.

        Syntax: exit|quit

        The 'exit' command is used to terminate the application. You can also
        use the standard UNIX Ctrl+D end of file sequence to quit.
        """
        if arg:
            raise CmdSyntaxError('Unknown argument %s' % arg)
        self.pprint('')
        return True

    do_quit = do_exit

    do_EOF = do_exit

