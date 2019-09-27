#!/usr/bin/env python

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

"Defines the dialogs used in the monitor application"

from . import widgets


class MasterDialog(widgets.Dialog):
    pass


class SlaveDialog(widgets.Dialog):
    pass


class HelpDialog(widgets.Dialog):
    def __init__(self):
        ok_button = widgets.FixedButton('OK')
        body = widgets.Text([
            "Welcome to the ", ("bold", "piwheels"), " monitor "
            "application. When run on the same node as the "
            "master, this should automatically connect and "
            "display its status, along with the state of any "
            "connected build slaves.\n"
            "\n",
            "The following keys can be used within the monitor:\n"
            "\n",
            ("bold", "j / down"), " - Move down the list of machines\n",
            ("bold", "k / up"), "   - Move up the list of machines\n",
            ("bold", "enter"), "    - Perform an action on the selected machine\n",
            ("bold", "h"), "        - Display this help\n",
            ("bold", "q"), "        - Quit the application",
        ])
        super().__init__(title='Help', body=body, buttons=[ok_button])
        widgets.connect_signal(ok_button, 'click', lambda btn: self._emit('close'))
        self.width = ('relative', 50)
        self.min_width = 60
        self.height = ('relative', 20)
        self.min_height = 16


class YesNoDialog(widgets.Dialog):
    def __init__(self, title, message):
        yes_button = widgets.FixedButton('Yes')
        no_button = widgets.FixedButton('No')
        super().__init__(title=title, body=widgets.Text(message),
                         buttons=[yes_button, no_button])
        self.result = None
        widgets.connect_signal(yes_button, 'click', self.yes)
        widgets.connect_signal(no_button, 'click', self.no)
        self.width = max(20, len(message) + 6)
        self.height = 5

    def yes(self, btn=None):
        self.result = True
        self._emit('close')

    def no(self, btn=None):
        self.result = False
        self._emit('close')

    def keypress(self, size, key):
        """
        Respond to "y" or "n" on the keyboard as a short-cut to selecting and
        clicking the actual buttons.
        """
        # Urwid does some amusing things with its widget classes which fools
        # pylint's static analysis. The super-method *is* callable here.
        # pylint: disable=not-callable
        if isinstance(key, str):
            if key == 'y':
                return self.yes()
            elif key == 'n':
                return self.no()
        return super().keypress(size, key)
