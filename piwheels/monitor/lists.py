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

"Provides the list walker for the master/slave list"

from datetime import datetime, timedelta, timezone
from collections import deque

import urwid as ur

from ..format import format_timedelta
from ..states import SlaveStats, MasterStats


UTC = timezone.utc
TreeMarker = object()


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
        return format_timedelta(datetime.now(tz=UTC) - timestamp)


class SlaveListWalker(ur.ListWalker):
    """
    A :class:`ListWalker` that tracks the active set of build slaves currently
    known by the master. Provides methods to update the state of the list based
    on messages received on the external status queue.

    :param header:
        The widget forming the header of the main list-box.

    :param get_box:
        A callable which will return the currently shown master or slave
        stats-box widget.
    """
    def __init__(self, header, get_box):
        super().__init__()
        self.header = header
        self.get_box = get_box
        self.focus = None
        master_state = MasterState()
        self.slaves = {None: master_state}    # maps slave ID to state object
        self.widgets = [master_state.widget]  # list of widget objects in display order

    @property
    def selected_slave(self):
        try:
            widget = self.widgets[self.focus]
        except TypeError:
            return None
        for slave in self.slaves.values():
            if slave.widget is widget:
                return slave

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

    def message(self, slave_id, timestamp, msg, data):
        """
        Update the list with a message from the external status queue.

        :param int slave_id:
            The id of the slave the message was originally sent to, or None
            if it's a message about the master.

        :param datetime.datetime timestamp:
            The timestamp when the message was originally sent.

        :param str msg:
            The reply that was sent to the build slave (or master).

        :param data:
            Any data that went with the message.
        """
        try:
            state = self.slaves[slave_id]
        except KeyError:
            state = SlaveState(slave_id)
            self.slaves[slave_id] = state
            self.widgets.append(state.widget)
        state.update(timestamp, msg, data)
        if msg == 'HELLO':
            # ABI and/or label of a slave have potentially changed; time to
            # re-sort the widget list
            self.widgets = [
                state.widget for state in sorted(
                    self.slaves.values(), key=lambda state: state.sort_key
                )
            ]
        self.update()
        box = self.get_box()
        if (
            # If the subject of the message is the currently selected state,
            # update the current stats box
            box is not None and self.focus is not None and
            self.widgets[self.focus] is state.widget
        ):
            box.update(state)

    def tick(self):
        """
        Typically called once a second to update the various timers in the
        list. Also handles removing terminated slaves after a short delay (to
        let the user see the terminated state).
        """
        # Remove killed slaves
        now = datetime.now(tz=UTC)
        for slave_id, state in list(self.slaves.items()):
            if state.killed and (now - state.last_seen > timedelta(seconds=5)):
                # TODO Don't remove the master widget
                # Be careful not to change the sort-order here...
                self.widgets.remove(state.widget)
                del self.slaves[slave_id]
        if self.widgets:
            self.focus = min(self.focus or 0, len(self.widgets) - 1)
        else:
            self.focus = None
        self.update()

    def tree_columns(self, row, columns):
        return [
            (
                style, (
                    ('`-' if row == len(self.slaves) - 1 else '+-')
                    if content is TreeMarker else content
                )
            )
            for style, content in columns
        ]

    def update(self):
        """
        Called to update the list content with calculated column widths.
        """
        columns = [
            self.tree_columns(row, state.columns)
            for row, state in enumerate(self.slaves.values())
        ]
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


class MasterState:
    """
    Class for tracking the state of the master. :class:`SlaveListWalker` stores
    an instance of this as the first entry.
    """

    def __init__(self):
        self.widget = ur.AttrMap(
            ur.SelectableIcon(''), None,
            focus_map={'status': 'inv_status'}
        )
        self.killed = False
        self.stats = deque(maxlen=100)
        self.first_seen = None
        self.last_seen = None
        self.status = 'Doing whatever the master does'  # TODO
        self.label = ''
        self.os_name = '-'
        self.os_version = '-'
        self.board_revision = '-'
        self.board_serial = '-'

    def update(self, timestamp, msg, data):
        """
        Update the master's state from an incoming reply message.

        :param str msg:
            The message itself.

        :param data:
            Any data sent with the message.
        """
        self.last_seen = timestamp
        if msg == 'HELLO':
            (
                self.first_seen,
                self.label,
                self.os_name,
                self.os_version,
                self.board_revision,
                self.board_serial,
            ) = data
            self.stats.clear()
        elif msg == 'STATS':
            self.stats.append(MasterStats.from_message(data))
        else:
            assert False, 'unexpected message'

    @property
    def sort_key(self):
        return ('', '')

    @property
    def state(self):
        if self.first_seen is not None:
            if datetime.now(tz=UTC) - self.last_seen > timedelta(seconds=30):
                return 'silent'
        if self.killed:
            return 'dead'
        return 'okay'

    @property
    def columns(self):
        return [
            (self.state, '*'),
            ('status', ''),
            ('status', ''),
            ('status', self.label),
            ('status', ''),
            ('status', since(self.first_seen)),
            ('status', since(self.last_seen)),
            ('status', self.status),
        ]


class SlaveState:
    """
    Class for tracking the state of a single build slave.
    :class:`SlaveListWalker` stores a list of these in
    :attr:`~SlaveListWalker.widgets`.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, slave_id):
        self.widget = ur.AttrMap(
            ur.SelectableIcon(''), None,
            focus_map={'status': 'inv_status'}
        )
        self.killed = False
        self.slave_id = slave_id
        self.stats = deque(maxlen=100)
        self.last_msg = ''
        self.build_timeout = None
        self.busy_timeout = None
        self.py_version = '-'
        self.abi = '-'
        self.platform = '-'
        self.label = ''
        self.os_name = '-'
        self.os_version = '-'
        self.board_revision = '-'
        self.board_serial = '-'
        self.build_start = None
        self.first_seen = None
        self.last_seen = None
        self.clock_skew = None
        self.status = ''

    def update(self, timestamp, msg, data):
        """
        Update the slave's state from an incoming reply message.

        :param datetime.datetime timestamp:
            The time at which the master received the message.

        :param str msg:
            The message itself.

        :param data:
            Any data sent with the message.
        """
        self.last_msg = msg
        self.last_seen = timestamp
        if msg == 'HELLO':
            self.status = 'Initializing'
            self.first_seen = timestamp
            (
                self.build_timeout,
                self.busy_timeout,
                self.py_version,
                self.abi,
                self.platform,
                self.label,
                self.os_name,
                self.os_version,
                self.board_revision,
                self.board_serial,
            ) = data
            self.stats.clear()
        elif msg == 'STATS':
            data = SlaveStats.from_message(data)
            self.clock_skew = self.last_seen - data.timestamp
            self.stats.append(data)
        elif msg == 'SLEEP':
            self.status = 'Waiting for jobs'
        elif msg in 'DIE':
            self.status = 'Terminating'
            self.killed = True
        elif msg == 'BUILD':
            self.status = 'Building {} {}'.format(data[0], data[1])
            self.build_start = timestamp
        elif msg == 'SEND':
            self.status = 'Transferring file'
        elif msg == 'DONE':
            self.status = 'Cleaning up after build'
            self.build_start = None
        elif msg in ('CONT', 'ACK'):
            pass
        else:
            assert False, 'unexpected message'

    @property
    def sort_key(self):
        return self.abi, self.label

    @property
    def state(self):
        """
        Calculate a simple state indicator for the slave, used to color the
        initial "*" on the entry.
        """
        now = datetime.now(tz=UTC)
        if self.first_seen is not None:
            if now - self.last_seen > self.busy_timeout:
                return 'dead'
            elif now - self.last_seen > self.busy_timeout / 2:
                return 'silent'
            elif self.last_msg == 'DONE':
                return 'cleaning'
            elif self.last_msg == 'SEND':
                return 'sending'
            elif self.build_start is not None:
                return 'building'
        if self.killed:
            return 'dead'
        return 'idle'

    @property
    def columns(self):
        """
        Calculates the state of all columns for the slave's entry. Returns a
        list of (style, content) tuples. Note that the content is *not* padded
        for width. The :class:`SlaveListWalker` class handles this.
        """
        return [
            ('status', TreeMarker),
            (self.state, '*'),
            ('status', str(self.slave_id)),
            ('status', self.label),
            ('status', self.abi),
            ('status', since(self.first_seen)),
            ('status', since(self.build_start or self.last_seen)),
            ('status', self.status),
        ]
