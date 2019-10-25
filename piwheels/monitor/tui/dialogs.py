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

from collections import namedtuple

from piwheels import widgets as wdg


class HelpDialog(wdg.Dialog):
    def __init__(self):
        ok_button = wdg.FixedButton(wdg.format_hotkey('_OK'))
        body = wdg.Text([
            "Welcome to the ", ('bold', "piwheels"), " monitor "
            "application. When run on the same node as the "
            "master, this should automatically connect and "
            "display its status, along with the state of any "
            "connected build slaves.\n"
            "\n",
            "The following keys can be used within the monitor:\n"
            "\n",
            ('bold', "j / down"), " - Move down the list of machines\n",
            ('bold', "k / up"), "   - Move up the list of machines\n",
            ('bold', "enter"), "    - Perform an action on the selected machine\n",
            ('bold', "h"), "        - Display this help\n",
            ('bold', "q"), "        - Quit the application",
        ])
        super().__init__(title='Help', body=body, buttons=[ok_button])
        wdg.connect_signal(ok_button, 'click', lambda btn: self._emit('close'))
        self.width = ('relative', 50)
        self.min_width = 60
        self.height = ('relative', 20)
        self.min_height = 16

    def keypress(self, size, key):
        if key == 'o':
            self._emit('close')
        else:
            return super().keypress(size, key)


Action = namedtuple('Action', ('result', 'title', 'help'))


class ActionsDialog(wdg.Dialog):
    title = 'Action!'
    actions = []  # list of Action instances

    def __init__(self, state):
        ok_button = wdg.FixedButton(wdg.format_hotkey('_OK'))
        cancel_button = wdg.FixedButton(wdg.format_hotkey('_Cancel'))
        choices = []
        self.state = state
        self.actions = {
            wdg.RadioButton(choices, wdg.format_hotkey(action.title),
                            on_state_change=self.action_picked,
                            user_data=action): action
            for action in self.actions
        }
        self.help_text = wdg.Text('')
        super().__init__(
            title=self.title,
            body=wdg.Columns([
                (20, wdg.Pile(choices)),
                self.help_text
            ]),
            buttons=[ok_button, cancel_button])
        self.result = None
        for radio, action in self.actions.items():
            if radio.state:
                self.help_text.set_text(action.help)
        wdg.connect_signal(ok_button, 'click', self.ok)
        wdg.connect_signal(cancel_button, 'click', self.cancel)
        self.width = 50
        self.min_width = 20
        self.height = 12

    def ok(self, btn=None):
        for radio, action in self.actions.items():
            if radio.state:
                self.result = action.result
                break
        self._emit('close')

    def cancel(self, btn=None):
        self._emit('close')

    def default(self, btn=None):
        # cancel if focused on cancel button, ok otherwise
        pass

    def action_picked(self, radio, new_state, action):
        if new_state:
            self.help_text.set_text(action.help)

    def keypress(self, size, key):
        try:
            {
                'enter': self.default,
                'o': self.ok,
                'c': self.cancel,
            }[key]()
        except KeyError:
            for radio in self.actions:
                if key == wdg.find_hotkey(*radio._label.get_text()).lower():
                    radio.set_state(True)
                    self.set_focus(radio)
                    return
            return super().keypress(size, key)


class MasterDialog(ActionsDialog):
    title = 'Master Control'
    actions = [
        Action('sleep', "_Pause",
               "Stops new builds from being sent to build slaves, but waits "
               "for existing builds to finish first. Useful for installing "
               "new build dependencies across the cluster without shutting "
               "everything down."),
        Action('sleep_now', "_Halt",
               "Immediately halt existing builds and stop new builds from "
               "being sent to the slaves. Useful for installing new build "
               "dependencies across the cluster."),
        Action('wake', "_Resume",
               "Resumes sending builds to slaves; the opposite to the 'Pause' "
               "and 'Halt' actions."),
        Action('kill_slaves', "_Stop Slaves",
               "Shuts down all build slaves after each has completed its "
               "existing build. Use this before 'Stop Master' to stop "
               "everything when upgrading the entire cluster."),
        Action('kill_slaves_now', "_Kill Slaves",
               "Cancels all existing builds and immediately shuts down all "
               "build slaves. Use this before 'Stop Master' to stop "
               "everything when upgrading the entire cluster quickly."),
        Action('kill_master', "Stop _Master",
               "Cancels all active builds and shuts down the master service "
               "but leaves all slaves running. Useful for upgrading just the "
               "master and/or performing database maintenance."),
    ]


class SlaveDialog(ActionsDialog):
    title = 'Slave Control'
    actions = [
        Action('skip_now', "Sk_ip",
               "Stops the current build and moves onto the next (if there is "
               "one). Useful for skipping a build which is known to fail or "
               "is obviously failing."),
        Action('sleep', "_Pause",
               "Stops new builds from being sent to the selected slave, but "
               "waits the existing build to finish first. Useful for "
               "maintaining dependencies on the slave."),
        Action('sleep_now', "_Halt",
               "Immediately halt the existing build and stop new builds from "
               "being sent to the selected slave. Useful for maintaining "
               "dependencies on the slave."),
        Action('wake', "_Resume",
               "Resumes sending builds to the selected slave; the opposite to "
               "the 'Pause' and 'Halt' actions."),
        Action('kill_slave', "_Stop Slave",
               "Shuts down the build slave after the current build has "
               "finished. Useful for maintaining the slave installation."),
        Action('kill_slave_now', "_Kill Slave",
               "Cancels the current build and immediately shuts down the "
               "build slave. Useful for maintaining the slave installation."),
    ]
