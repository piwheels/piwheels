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

"""
The piw-monitor application is used to monitor (and optionally control) the
piw-master script. Upon startup it will request the status of all build slaves
currently known to the master, and will then continually update its display as
the slaves progress through builds. The controls at the bottom of the display
allow the administrator to pause or resume the master script, kill build slaves
that are having issues (e.g. excessive resource consumption from a huge build)
or terminate the master itself.
"""

import sys
from time import sleep
from datetime import datetime, timezone
from collections import deque

from piwheels import terminal, const, protocols, transport, widgets
from . import states, dialogs, statsbox


UTC = timezone.utc


class PiWheelsMonitor:
    """
    This is the main class for the :program:`piw-monitor` script. It
    connects to the :program:`piw-master` script via the control and external
    status queues, and displays the real-time status of the master in a nice
    curses-based UI.  Controls are provided for terminating build slaves, and
    the master itself, as well as pausing and resuming the master's operations.
    """
    # pylint: disable=too-many-instance-attributes

    # Stop the relentless march against nicely aligned code
    # pylint: disable=bad-whitespace
    palette = [
        ('idle',        'dark gray',       'default'),
        ('building',    'light green',     'default'),
        ('sending',     'light blue',      'default'),
        ('cleaning',    'light magenta',   'default'),
        ('silent',      'yellow',          'default'),
        ('dead',        'light red',       'default'),

        ('time',        'light gray',      'default'),
        ('status',      'light gray',      'default'),
        ('inv_status',  'black',           'light gray'),
        ('header',      'black',           'dark cyan'),
        ('footer',      'dark blue',       'default'),

        ('dialog',      'light gray',      'dark blue'),
        ('hotkey',      'light cyan',      'dark blue'),
        ('disabled',    'light blue',      'dark blue'),
        ('bold',        'white',           'dark blue'),
        ('button',      'light gray',      'dark blue'),
        ('inv_button',  'black',           'light gray'),
    ]

    def __init__(self):
        self.status_queue = None
        self.ctrl_queue = None
        self.loop = None           # the main event loop
        self.frame = None          # the top-level Frame widget
        self.slave_list = None     # the list-walker for all build slaves
        self.slave_box = None      # the box displaying stats for build slaves
        self.master_box = None     # the box displaying stats for the master
        self.status_box = None     # the message box at the bottom
        self.list_header = None

    def __call__(self, args=None):
        parser = terminal.configure_parser(__doc__, log_params=False)
        parser.add_argument(
            '--status-queue', metavar='ADDR',
            default=const.STATUS_QUEUE,
            help="The address of the queue used to report status to monitors "
            "(default: %(default)s)")
        parser.add_argument(
            '--control-queue', metavar='ADDR',
            default=const.CONTROL_QUEUE,
            help="The address of the queue a monitor can use to control the "
            "master (default: %(default)s)")
        try:
            config = parser.parse_args(args)
        except:  # pylint: disable=bare-except
            return terminal.error_handler(*sys.exc_info())

        ctx = transport.Context()
        self.status_queue = ctx.socket(
            transport.SUB, protocol=reversed(protocols.monitor_stats))
        self.status_queue.connect(config.status_queue)
        self.status_queue.subscribe('')
        sleep(1)
        self.ctrl_queue = ctx.socket(
            transport.PUSH, protocol=reversed(protocols.master_control))
        self.ctrl_queue.connect(config.control_queue)
        self.ctrl_queue.send_msg('HELLO')
        try:
            self.loop = widgets.MainLoop(
                self.build_ui(), self.palette,
                event_loop=widgets.ZMQEventLoop(),
                unhandled_input=self.unhandled_input)
            self.loop.event_loop.watch_queue(self.status_queue,
                                             self.status_message)
            widgets.connect_signal(self.slave_list, 'modified',
                                   self.list_modified)
            self.loop.event_loop.alarm(1, self.tick)
            self.loop.run()
        finally:
            ctx.close()
            sys.stdout.flush()

    def build_ui(self):
        """
        Constructs the monitor's UI from urwid widgets. Returns the root widget
        and the application's palette, for passing to the selected urwid event
        loop constructor.
        """
        self.list_header = widgets.AttrMap(
            widgets.Columns([
                (len(caption) + 1, widgets.Text(caption)) if index < 7 else
                widgets.Text(caption)
                for index, caption in enumerate((
                    'S',
                    '',
                    '#',
                    'Label^',
                    'ABI^',
                    'Up Time',
                    'Task Time',
                    'Task'
                ))
            ]),
            'header'
        )
        self.slave_box = statsbox.SlaveStatsBox()
        self.master_box = statsbox.MasterStatsBox()
        self.status_box = widgets.Text('Waiting for connection')
        self.slave_list = states.SlaveListWalker(
            header=self.list_header.original_widget,
            get_box=lambda: self.get_box()[0])
        list_box = widgets.ListBox(self.slave_list)
        # Make the list-box navigation vim-friendly
        list_box._command_map = list_box._command_map.copy()
        list_box._command_map['j'] = list_box._command_map['down']
        list_box._command_map['k'] = list_box._command_map['up']
        self.frame = widgets.Frame(
            list_box,
            header=self.list_header,
            footer=None)  # to be set by list_modified

        status_line = widgets.AttrMap(
            widgets.Filler(self.status_box), 'footer')

        return widgets.DialogMaster(
            widgets.Pile([
                self.frame,
                (1, status_line),
            ])
        )

    def status_message(self):
        """
        Handler for messages received from the PUB/SUB external status queue.
        """
        msg, data = self.status_queue.recv_msg()
        if msg in ('HELLO', 'STATS'):
            slave_id = None
            timestamp = datetime.now(tz=UTC)
            if msg == 'HELLO':
                self.status_box.set_text('Connected to master')
        elif msg == 'SLAVE':
            slave_id, timestamp, msg, data = data
        self.slave_list.message(slave_id, timestamp, msg, data)

    def tick(self):
        """
        Called by the event loop's alarm once a second to update timers in the
        build slave list.
        """
        self.slave_list.tick()
        self.loop.event_loop.alarm(1, self.tick)

    def unhandled_input(self, key):
        """
        Watch for "h" (for help) and "q" (for quit); pass everything else
        through to the higher level handler.
        """
        if isinstance(key, str):
            try:
                {
                    'enter': self.action,
                    'h':     self.help,
                    'q':     self.quit,
                }[key]()
            except KeyError:
                return False
            else:
                return True
        else:
            # Ignore unhandled mouse events
            return False

    def get_box(self):
        try:
            box, options = self.frame.contents['footer']
        except KeyError:
            box = options = None
        return box, options

    def list_modified(self):
        box, options = self.get_box()
        if self.slave_list.focus is None:
            if box is not None:
                self.frame.contents['footer'] = (None, options)
        elif self.slave_list.focus == 0 and box is not self.master_box:
            self.master_box.update(self.slave_list.slaves[None])
            self.frame.contents['footer'] = (self.master_box, options)
        elif self.slave_list.focus > 0 and box is not self.slave_box:
            self.slave_box.update(self.slave_list.selected_slave)
            self.frame.contents['footer'] = (self.slave_box, options)

    def help(self, widget=None):
        self.loop.widget.open_dialog(dialogs.HelpDialog())

    def quit(self, widget=None):
        """
        Click handler for the Quit button.
        """
        # pylint: disable=unused-argument,no-self-use
        raise widgets.ExitMainLoop()

    def action(self, widget=None):
        if self.slave_list.focus is not None:
            if self.slave_list.focus == 0:
                dialog = dialogs.MasterDialog(self.slave_list.slaves[None])
                self.loop.widget.open_dialog(dialog, after=self.master_action)
            elif self.slave_list.focus > 0:
                dialog = dialogs.SlaveDialog(self.slave_list.selected_slave)
                self.loop.widget.open_dialog(dialog, after=self.slave_action)

    def master_action(self, dialog):
        assert isinstance(dialog, dialogs.MasterDialog)
        if dialog.result is not None:
            if dialog.result.startswith('sleep'):
                self.ctrl_queue.send_msg('SLEEP', None)
            elif dialog.result == 'wake':
                self.ctrl_queue.send_msg('WAKE', None)
            elif dialog.result.startswith('kill_slaves'):
                self.ctrl_queue.send_msg('KILL', None)
            elif dialog.result == 'kill_master':
                self.ctrl_queue.send_msg('QUIT')
            else:
                assert False, 'unknown result code'
            if dialog.result.endswith('_now'):
                self.ctrl_queue.send_msg('SKIP', None)

    def slave_action(self, dialog):
        assert isinstance(dialog, dialogs.SlaveDialog)
        if dialog.result is not None:
            if dialog.result.startswith('sleep'):
                self.ctrl_queue.send_msg('SLEEP', dialog.state.slave_id)
            elif dialog.result == 'wake':
                self.ctrl_queue.send_msg('WAKE', dialog.state.slave_id)
            elif dialog.result.startswith('kill_slave'):
                self.ctrl_queue.send_msg('KILL', dialog.state.slave_id)
            elif dialog.result.startswith('skip'):
                # Already done above
                pass
            else:
                assert False, 'unknown result code'
            if dialog.result.endswith('_now'):
                self.ctrl_queue.send_msg('SKIP', dialog.state.slave_id)


main = PiWheelsMonitor()  # pylint: disable=invalid-name

if __name__ == '__main__':
    main()
