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

"Provides a top-level widget capable of multiple overlays"

import urwid as ur


class Overlays(ur.WidgetPlaceholder):
    def __init__(self, top):
        super().__init__(top)
        self.level = 0

    def open_dialog(self, dialog):
        self.original_widget = ur.Overlay(
            ur.AttrMap(ur.LineBox(dialog), 'dialog'),
            self.original_widget,
            align='center', width=('relative', 40),
            valign='middle', height=('relative', 30),
            min_width=20, min_height=10)
        self.level += 1

    def close_dialog(self):
        assert self.level
        self.original_widget = self.original_widget[0]
        self.level -= 1

    def keypress(self, size, key):
        if key == 'esc' and self.level:
            self.close_dialog()
        else:
            return super().keypress(size, key)


class SimpleButton(ur.Button):
    """
    Overrides :class:`Button` to enclose the label in [square brackets].
    """
    button_left = ur.Text("[")
    button_right = ur.Text("]")


class FixedButton(SimpleButton):
    """
    A fixed sized, one-line button derived from :class:`SimpleButton`.
    """
    def sizing(self):
        return frozenset(['fixed'])

    def pack(self, size, focus=False):
        # pylint: disable=unused-argument
        return (len(self.get_label()) + 4, 1)


class YesNoDialog(ur.WidgetWrap):
    """
    Wraps a box and buttons to form a simple Yes/No modal dialog. The dialog
    emits signals "yes" and "no" when either button is clicked or when "y" or
    "n" are pressed on the keyboard.
    """
    signals = ['yes', 'no']

    def __init__(self, title, message):
        yes_button = FixedButton('Yes')
        no_button = FixedButton('No')
        ur.connect_signal(yes_button, 'click', lambda btn: self._emit('yes'))
        ur.connect_signal(no_button, 'click', lambda btn: self._emit('no'))
        super().__init__(
            ur.LineBox(
                ur.Pile([
                    ('pack', ur.Text(message)),
                    ur.Filler(
                        ur.Columns([
                            ('pack', ur.AttrMap(yes_button, 'button', 'inv_button')),
                            ('pack', ur.AttrMap(no_button, 'button', 'inv_button')),
                        ], dividechars=2),
                        valign='bottom'
                    )
                ]),
                title
            )
        )

    def keypress(self, size, key):
        """
        Respond to "y" or "n" on the keyboard as a short-cut to selecting and
        clicking the actual buttons.
        """
        # Urwid does some amusing things with its widget classes which fools
        # pylint's static analysis. The super-method *is* callable here.
        # pylint: disable=not-callable
        key = super().keypress(size, key)
        if isinstance(key, str):
            if key.lower() == 'y':
                self._emit('yes')
            elif key.lower() == 'n':
                self._emit('no')
        return key

    def _get_title(self):
        return self._w.title_widget.text.strip()

    def _set_title(self, value):
        self._w.set_title(value)

    title = property(_get_title, _set_title)
