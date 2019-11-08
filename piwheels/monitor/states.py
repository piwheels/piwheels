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
Implements the classes for tracking master and slave states in monitor
applications.

.. autoclass:: SlaveList

.. autoclass:: MasterState

.. autoclass:: SlaveState
"""

from datetime import datetime, timedelta, timezone
from collections import deque

from ..states import SlaveStats, MasterStats


UTC = timezone.utc


class MasterState:
    """
    Class for tracking the state of the master via messages sent over the
    monitor PUB socket.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self):
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
        Update the master's state from an incoming status message.

        :param datetime.datetime timestamp:
            The time at which the message was originally sent.

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
    def slave_id(self):
        return None

    @property
    def sort_key(self):
        return '', ''

    @property
    def state(self):
        if self.first_seen is not None:
            if datetime.now(tz=UTC) - self.last_seen > timedelta(seconds=30):
                return 'silent'
        if self.killed:
            return 'dead'
        return 'okay'


class SlaveState:
    """
    Class for tracking the state of a single build slave via messages sent
    over the monitor PUB socket.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, slave_id):
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
        Update the slave's state from an incoming status message.

        :param datetime.datetime timestamp:
            The time at which the message was originally sent.

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
        elif msg == 'DIE':
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
