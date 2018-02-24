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
from datetime import datetime, timedelta

import zmq

from .. import terminal, const
from . import widgets


class PiWheelsMonitor:
    """
    This is the main class for the :program:`piw-monitor` script. It
    connects to the :program:`piw-master` script via the control and external
    status queues, and displays the real-time status of the master in a nice
    curses-based UI.  Controls are provided for terminating build slaves, and
    the master itself, as well as pausing and resuming the master's operations.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self):
        self.status_queue = None
        self.ctrl_queue = None
        self.loop = None           # the main event loop
        self.frame = None          # the top-level Frame widget
        self.slave_list = None     # the list-walker for all build slaves
        self.slave_to_kill = None  # which slave the user requested to kill
        self.popup_stack = []
        # The various widgets in the status box at the top
        self.disk_bar = None
        self.builds_label = None
        self.build_rate_label = None
        self.build_size_label = None
        self.build_time_label = None
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

        ctx = zmq.Context()
        self.status_queue = ctx.socket(zmq.SUB)
        self.status_queue.hwm = 10
        self.status_queue.connect(config.status_queue)
        self.status_queue.setsockopt_string(zmq.SUBSCRIBE, '')
        self.ctrl_queue = ctx.socket(zmq.PUSH)
        self.ctrl_queue.connect(config.control_queue)
        self.ctrl_queue.send_pyobj(['HELLO'])
        try:
            self.loop = widgets.MainLoop(
                *self.build_ui(),
                event_loop=widgets.ZMQEventLoop(),
                unhandled_input=self.unhandled_input)
            self.loop.event_loop.watch_queue(self.status_queue,
                                             self.status_message)
            self.loop.event_loop.alarm(1, self.tick)
            self.loop.run()
        finally:
            ctx.destroy(linger=1000)
            ctx.term()

    def build_ui(self):
        """
        Constructs the monitor's UI from urwid widgets. Returns the root widget
        and the application's palette, for passing to the selected urwid event
        loop constructor.
        """
        actions_box = widgets.AttrMap(
            widgets.Pile([
                widgets.AttrMap(
                    widgets.Divider('\N{UPPER HALF BLOCK}'),
                    'coltrans'
                ),
                widgets.Columns([
                    build_button('Pause', self.pause),
                    build_button('Resume', self.resume),
                    build_button('Kill slave', self.kill_slave),
                    build_button('Terminate master', self.terminate_master),
                    build_button('Quit', self.quit),
                ])
            ]),
            'footer'
        )
        self.disk_bar = widgets.ProgressBar('todo', 'done',
                                            satt='todo_smooth')
        self.builds_label = widgets.Text('-/- pkgs')
        self.build_rate_label = widgets.Text('- pkgs/hour')
        self.build_time_label = widgets.Text('-:--:--')
        self.build_size_label = widgets.Text('- bytes')
        self.list_header = widgets.AttrMap(
            widgets.Columns([
                (2, widgets.Text('S')),
                (2, widgets.Text('#')),
                (6, widgets.Text('Label')),
                (7, widgets.Text('UpTime')),
                (9, widgets.Text('TaskTime')),
                (4, widgets.Text('ABI')),
                widgets.Text('Task'),
            ]),
            'colheader'
        )
        self.slave_list = SlaveListWalker(self.list_header.original_widget)
        list_box = widgets.ListBox(self.slave_list)
        status_box = widgets.AttrMap(
            widgets.Pile([
                widgets.Columns([
                    (13, widgets.Pile([
                        widgets.Text('Disk Free'),
                        widgets.Text('Build Queue'),
                        widgets.Text('Build Rate'),
                        widgets.Text('Build Time'),
                        widgets.Text('Build Size'),
                    ])),
                    widgets.Pile([
                        self.disk_bar,
                        self.builds_label,
                        self.build_rate_label,
                        self.build_time_label,
                        self.build_size_label,
                    ]),
                ]),
                widgets.AttrMap(
                    widgets.Divider('\N{LOWER HALF BLOCK}'),
                    'coltrans'
                ),
                self.list_header,
            ]),
            'header'
        )
        self.frame = widgets.Frame(
            list_box,
            header=status_box,
            footer=actions_box
        )
        return self.frame, widgets.PALETTE

    def status_message(self):
        """
        Handler for messages received from the PUB/SUB external status queue.
        As usual, messages are a list of python objects. In this case messages
        always have at least 3 elements:

        * The slave id that the message relates to (this will be -1 in the case
          of messages that don't relate to a specific build slave)
        * The timestamp when the message was sent
        * The message itself
        """
        slave_id, timestamp, msg, *args = self.status_queue.recv_pyobj()
        if msg == 'STATUS':
            self.update_status(args[0])
        else:
            self.slave_list.message(slave_id, timestamp, msg, *args)

    def tick(self):
        """
        Called by the event loop's alarm once a second to update timers in the
        build slave list.
        """
        self.slave_list.tick()
        self.loop.event_loop.alarm(1, self.tick)

    def show_popup(self, dialog):
        """
        Given a *dialog* widget, construct an :class:`Overlay` to allow it to
        sit on top of the main build slave list, display it centered and give
        it focus.

        :param widgets.YesNoDialog dialog:
            The dialog to show.
        """
        overlay = widgets.Overlay(
            widgets.AttrMap(dialog, 'dialog'), self.frame.body,
            'center', ('relative', 40),
            'middle', ('relative', 30),
            min_width=20, min_height=10)
        overlay.title = dialog.title
        self.popup_stack.append((self.frame.get_focus(), self.frame.body))
        self.frame.body = overlay
        self.frame.set_focus('body')

    def close_popup(self, widget=None):
        """
        Close the last dialog to be shown.
        """
        # The extraneous widget parameter is to permit this method to be used
        # as an urwid action callback
        # pylint: disable=unused-argument
        focus, body = self.popup_stack.pop()
        self.frame.body = body
        self.frame.set_focus(focus)

    def unhandled_input(self, key):
        """
        Permit <tab> to be used to move between the build slave list, and the
        action buttons. Also watch for the first letter of each action button.
        """
        if isinstance(key, str):
            if key == 'tab' and not self.popup_stack:
                self.frame.set_focus(
                    'body' if self.frame.get_focus() == 'footer' else
                    'footer')
                return True
            else:
                # there's probably a more elegant way of associating these
                # hotkeys with the buttons, but I'm being lazy
                try:
                    {
                        'p': self.pause,
                        'r': self.resume,
                        'k': self.kill_slave,
                        't': self.terminate_master,
                        'q': self.quit,
                    }[key.lower()]()
                except KeyError:
                    return False
                else:
                    return True
        else:
            # Ignore unhandled mouse events
            return False

    def update_status(self, status_info):
        """
        Called to update the various status widgets at the top of the window
        with the latest information from the master.

        :param dict status_info:
            A dictionary of various statistics from the master (see
            :class:`BigBrother` for full details).
        """
        self.disk_bar.set_completion(
            status_info['disk_free'] * 100 / status_info['disk_size'])
        self.builds_label.set_text(
            '{} pkg(s)'.format(status_info['versions_count'] -
                               status_info['versions_tried']
                               if status_info['versions_count'] else 0))
        self.build_rate_label.set_text(
            '{} pkgs/hour'.format(status_info['builds_last_hour']))
        self.build_size_label.set_text(
            '{} Mbytes'.format(status_info['builds_size'] // 1048576))
        time = status_info['builds_time']
        time -= timedelta(microseconds=time.microseconds)
        self.build_time_label.set_text('{}'.format(time))

    def quit(self, widget=None):
        """
        Click handler for the Quit button.
        """
        # pylint: disable=unused-argument,no-self-use
        raise widgets.ExitMainLoop()

    def pause(self, widget=None):
        """
        Click handler for the Pause button.
        """
        # pylint: disable=unused-argument
        self.ctrl_queue.send_pyobj(['PAUSE'])

    def resume(self, widget=None):
        """
        Click handler for the Resume button.
        """
        # pylint: disable=unused-argument
        self.ctrl_queue.send_pyobj(['RESUME'])

    def kill_slave(self, widget=None):
        """
        Click handler for the Kill Slave button.
        """
        try:
            widget = self.slave_list[self.slave_list.focus]
        except IndexError:
            self.slave_to_kill = None
        else:
            for slave_id, slave in self.slave_list.slaves.items():
                if slave.widget == widget:
                    self.slave_to_kill = slave_id
                    break
            dialog = widgets.YesNoDialog(
                'Kill Slave',
                'Are you sure you wish to shutdown slave {}?\n\n'
                'NOTE: this will only request shutdown after '
                'current task finishes; it will not terminate '
                'a "stuck" slave'.format(self.slave_to_kill))
            widgets.connect_signal(dialog, 'yes', self._kill_slave)
            widgets.connect_signal(dialog, 'no', self.close_popup)
            self.show_popup(dialog)

    def _kill_slave(self, widget=None):
        # pylint: disable=unused-argument
        self.close_popup()
        slave = self.slave_list.slaves[self.slave_to_kill]
        self.ctrl_queue.send_pyobj(['KILL', self.slave_to_kill])
        self.slave_to_kill = None

    def terminate_master(self, widget=None):
        """
        Click handler for the Terminate Master button.
        """
        # pylint: disable=unused-argument
        dialog = widgets.YesNoDialog(
            'Terminate Master',
            'Are you sure you wish to shutdown the master?\n\n'
            'NOTE: this will also request shutdown of all '
            'slaves, and exit this application')
        widgets.connect_signal(dialog, 'yes', self._terminate_master)
        widgets.connect_signal(dialog, 'no', self.close_popup)
        self.show_popup(dialog)

    def _terminate_master(self, widget=None):
        # pylint: disable=unused-argument
        self.ctrl_queue.send_pyobj(['QUIT'])
        raise widgets.ExitMainLoop()


class SlaveListWalker(widgets.ListWalker):
    """
    A :class:`ListWalker` that tracks the active set of build slaves currently
    known by the master. Provides methods to update the state of the list based
    on messages received on the external status queue.
    """
    def __init__(self, header):
        super().__init__()
        self.header = header
        self.focus = None
        self.slaves = {}   # maps slave ID to SlaveState
        self.widgets = []  # list of SlaveState.widget objects in list order

    def __getitem__(self, position):
        return self.widgets[position]

    def next_position(self, position):
        """
        Return valid list position after *position*.
        """
        if position >= len(self.widgets) - 1:
            raise IndexError
        return position + 1

    def prev_position(self, position):
        """
        Return valid list position before *position*.
        """
        # pylint: disable=no-self-use
        if position <= 0:
            raise IndexError
        return position - 1

    def set_focus(self, position):
        """
        Set the list focus to *position*, if valid.
        """
        if not 0 <= position < len(self.widgets):
            raise IndexError
        self.focus = position
        self._modified()

    def message(self, slave_id, timestamp, msg, *args):
        """
        Update the list with a message from the external status queue.

        :param int slave_id:
            The id of the slave the message was originally sent to.

        :param datetime.datetime timestamp:
            The timestamp when the message was originally sent.

        :param str msg:
            The reply that was sent to the build slave.

        :param *args:
            Any arguments that went with the message.
        """
        try:
            state = self.slaves[slave_id]
        except KeyError:
            state = SlaveState(slave_id)
            self.slaves[slave_id] = state
            self.widgets.append(state.widget)
        state.update(timestamp, msg, *args)
        self.update()

    def tick(self):
        """
        Typically called once a second to update the various timers in the
        list. Also handles removing terminated slaves after a short delay (to
        let the user see the terminated state).
        """
        # Remove terminated slaves
        now = datetime.utcnow()
        for slave_id, state in list(self.slaves.items()):
            if state.terminated and (now - state.last_seen > timedelta(seconds=5)):
                self.widgets.remove(state.widget)
                del self.slaves[slave_id]
        if self.widgets:
            self.focus = min(self.focus or 0, len(self.widgets) - 1)
        else:
            self.focus = None
        self.update()

    def update(self):
        """
        Called to update the list content with calculated column widths.
        """
        columns = [state.columns for state in self.slaves.values()]
        head_lens = [
            options[1] if options[0] == 'given' else 0
            for widget, options in self.header.contents
        ]
        row_lens = [
            [len(content) for style, content in state]
            for state in columns
        ]
        col_lens = zip(*row_lens)  # transpose
        col_lens = [
            max(head_len, max(col) + 1)  # add 1 for col spacing
            for head_len, col in zip(head_lens, col_lens)
        ]
        for state, state_cols in zip(self.slaves.values(), columns):
            state.widget.original_widget.set_text([
                (style, '%-*s' % (col_len, content))
                for col_len, (style, content) in zip(col_lens, state_cols)
            ])
        for index, (col, col_len) in enumerate(zip(list(self.header.contents), col_lens)):
            widget, options = col
            if options[0] == 'given':
                self.header.contents[index] = (
                    widget, self.header.options('given', col_len)
                )
        self._modified()


class SlaveState:
    """
    Class for tracking the state of a single build slave.
    :class:`SlaveListWalker` stores a list of these in
    :attr:`~SlaveListWalker.widgets`.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, slave_id):
        self.widget = widgets.AttrMap(
            widgets.SelectableIcon(''), None,
            focus_map={'status': 'inv_status'}
        )
        self.terminated = False
        self.slave_id = slave_id
        self.last_msg = ''
        self.py_version = '-'
        self.timeout = None
        self.abi = '-'
        self.platform = '-'
        self.first_seen = None
        self.last_seen = None
        self.status = ''
        self.label = ''

    def update(self, timestamp, msg, *args):
        """
        Update the slave's state from an incoming reply message.

        :param datetime.datetime timestamp:
            The time at which the message was originally sent.

        :param str msg:
            The message itself.

        :param *args:
            Any arguments sent with the message.
        """
        self.last_msg = msg
        self.last_seen = timestamp
        if msg == 'HELLO':
            self.status = 'Initializing'
            self.first_seen = timestamp
            (
                self.timeout,
                self.py_version,
                self.abi,
                self.platform,
                self.label
            ) = args
        elif msg == 'SLEEP':
            self.status = 'Waiting for jobs'
        elif msg == 'BYE':
            self.terminated = True
            self.status = 'Terminating'
        elif msg == 'BUILD':
            self.status = 'Building {} {}'.format(args[0], args[1])
        elif msg == 'SEND':
            self.status = 'Transferring file'
        elif msg == 'DONE':
            self.status = 'Cleaning up after build'

    @property
    def state(self):
        """
        Calculate a simple state indicator for the slave, used to color the
        initial "*" on the entry.
        """
        if self.last_seen is not None:
            if datetime.utcnow() - self.last_seen > timedelta(minutes=15):
                return 'silent'
            elif datetime.utcnow() - self.last_seen > self.timeout:
                return 'dead'
        if self.terminated:
            return 'dead'
        return 'okay'

    @property
    def columns(self):
        """
        Calculates the state of all columns for the slave's entry. Returns a
        list of (style, content) tuples. Note that the content is *not* padded
        for width. The :class:`SlaveListWalker` class handles this.
        """
        return [
            (self.state, '*'),
            ('status', str(self.slave_id)),
            ('status', self.label),
            ('status', since(self.first_seen)),
            ('status', since(self.last_seen)),
            ('status', self.abi),
            ('status', self.status),
        ]


def build_button(caption, callback):
    """
    Build a :class:`widgets.SimpleButton` with the specified *caption* and link
    it to *callback*. The first letter of *caption* will be highlighted as a
    hotkey.

    :param str caption:
        The caption for the new button.

    :param callback:
        The function to execute when the button is clicked.
    """
    btn = widgets.SimpleButton(
        ('button', [('hotkey', caption[0]), caption[1:]])
    )
    widgets.connect_signal(btn, 'click', callback)
    return widgets.AttrMap(widgets.AttrMap(btn, None, focus_map={
        'button': 'inv_button',
        'hotkey': 'inv_hotkey',
    }), 'button', 'inv_button')


def since(timestamp):
    """
    Return a nicely formatted string indicating the number of hours minutes and
    seconds since *timestamp*.

    :param datetime.datetime timestamp:
        The timestamp from which to measure a duration.
    """
    if timestamp is None:
        return '-'
    else:
        return str(datetime.utcnow().replace(microsecond=0) -
                   timestamp.replace(microsecond=0))


main = PiWheelsMonitor()  # pylint: disable=invalid-name

if __name__ == '__main__':
    main()
