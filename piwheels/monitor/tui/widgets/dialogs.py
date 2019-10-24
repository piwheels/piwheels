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


CANCEL_DIALOG = 'cancel dialog'
TOGGLE_FOCUS = 'toggle focus'


ur.command_map['esc'] = CANCEL_DIALOG
ur.command_map['tab'] = TOGGLE_FOCUS


class DialogMaster(ur.WidgetPlaceholder):
    def __init__(self, top):
        super().__init__(top)
        self.dialogs = []

    def open_dialog(self, dialog, after=None):
        ur.connect_signal(dialog, 'close', self.close_dialog)
        self.original_widget = ur.Overlay(
            ur.AttrMap(dialog, 'dialog'), self.original_widget,
            align=dialog.align, width=dialog.width,
            valign=dialog.valign, height=dialog.height,
            min_width=dialog.min_width, min_height=dialog.min_height)
        self.dialogs.append((dialog, after))

    def close_dialog(self, widget=None):
        assert self.dialogs
        self.original_widget = self.original_widget[0]
        dialog, after = self.dialogs.pop()
        if after is not None:
            after(dialog)

    def keypress(self, size, key):
        if self._command_map[key] == CANCEL_DIALOG and self.dialogs:
            self.close_dialog()
        else:
            return super().keypress(size, key)


class Dialog(ur.WidgetWrap):
    signals = ['close']

    def __init__(self, title, body, buttons):
        buttons = [
            ('pack', ur.AttrMap(btn, 'button', 'inv_button'))
            for btn in buttons
        ]
        super().__init__(
            ur.LineBox(
                ur.Pile([
                    ('pack', body),
                    ur.Filler(
                        ur.Columns([ur.Text('')] + buttons, dividechars=2),
                        valign='bottom'
                    ),
                ]),
                title
            )
        )
        self._saved_focus = None
        self.width = ('relative', 80)
        self.height = ('relative', 60)
        self.align = 'center'
        self.valign = ('relative', 30)
        self.min_width = 0
        self.min_height = 0

    @property
    def root(self):
        return self._w.base_widget

    @property
    def body(self):
        return self.root[0]

    def _focus_path(self, widget, root=None, path=None):
        if path is None:
            path = []
        if root is widget:
            return path
        elif root is None:
            root = self.root
        try:
            for index in root:
                result = self._focus_path(widget, root[index], path + [index])
                if result:
                    return result
        except TypeError:
            return

    def set_focus(self, widget):
        if widget.selectable():
            self.root.set_focus_path(self._focus_path(widget))

    def keypress(self, size, key):
        if self._command_map[key] == TOGGLE_FOCUS:
            current_focus = self.root.get_focus_path()
            if self._saved_focus and self._saved_focus[0] != current_focus[0]:
                self.root.set_focus_path(self._saved_focus)
                self._saved_focus = current_focus
            elif self.root.contents[1 - current_focus[0]][0].selectable():
                self._saved_focus = current_focus
                self.root.set_focus_path([1 - current_focus[0]])
        else:
            return super().keypress(size, key)
