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

"Customizes urwid for the monitor application"

# This module is a one-stop shop for all the monitor's widget needs, hence all
# the unused imports
# pylint: disable=unused-import

from urwid import (
    connect_signal,
    command_map,
    Widget,
    WidgetWrap,
    AttrMap,
    Button,
    Text,
    Edit,
    IntEdit,
    RadioButton,
    CheckBox,
    SelectableIcon,
    Pile,
    Columns,
    Padding,
    Filler,
    Divider,
    SolidFill,
    BoxAdapter,
    Frame,
    ListBox,
    Overlay,
    LineBox,
    ListWalker,
    MainLoop,
    ExitMainLoop,
)

from .event_loop import ZMQEventLoop
from .dialogs import DialogMaster, Dialog
from .charts import TrendBar, RatioBar


class SimpleButton(Button):
    """
    Overrides :class:`Button` to enclose the label in [square brackets].
    """
    button_left = Text("[")
    button_right = Text("]")


class FixedButton(SimpleButton):
    """
    A fixed sized, one-line button derived from :class:`SimpleButton`.
    """
    def sizing(self):
        return frozenset(['fixed'])

    def pack(self, size, focus=False):
        # pylint: disable=unused-argument
        return (len(self.get_label()) + 4, 1)


def format_hotkey(s, default=None, hotkey='hotkey'):
    """
    Given a caption *s*, returns an urwid markup list with the first underscore
    prefixed character transformed into a (*hotkey*, char) tuple, and the rest
    marked with the *default* attribute (or not marked if *default* is
    ``None``.

    For example::

        >>> format_hotkey('_Foo')
        [('hotkey', 'F'), 'oo']
        >>> format_hotkey('_Foo', 'normal', 'hot')
        [('hot', 'F'), ('normal', 'oo')]
        >>> format_hotkey('Pa_use')
        ['Pa', ('hotkey', 'u'), 'se']
    """
    try:
        i = s.index('_')
    except ValueError:
        return [s if default is None else (default, s)]
    else:
        if i == len(s) - 1:
            raise ValueError('Underscore cannot be last char in s')
        return [
            chunk for chunk in
            (
                s[:i] if default is None else (default, s[:i]),
                (hotkey, s[i + 1:i + 2]),
                s[i + 2:] if default is None else (default, s[i + 2:])
            )
            if chunk
        ]


def find_hotkey(text, attrs, hotkey='hotkey'):
    """
    Given an urwid (text, attr) tuple (as returned by, e.g.
    :meth:`Text.get_text`), returns the first character of the text matching
    the *hotkey* attribute, or ``None`` if no character matches.
    """
    ix = 0
    for attr, rl in attrs:
        if attr == hotkey:
            return text[ix]
        ix += rl
    return None
