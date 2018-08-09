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
Implements the classes for tracking slave states.

.. autoclass:: SlaveList

.. autoclass:: SlaveState
"""

from collections import OrderedDict
from datetime import datetime, timedelta

from colorzero import Color


class SlaveList:
    """
    Tracks the active set of build slaves currently known by the master.
    Provides methods to update the state of the list based on messages received
    on the external status queue.
    """
    def __init__(self):
        self.slaves = OrderedDict()

    def __len__(self):
        return len(self.slaves)

    def __getitem__(self, index):
        return list(self.slaves.values())[index]

    def __iter__(self):
        for slave in self.slaves.values():
            yield slave

    def prune(self):
        now = datetime.utcnow()
        for slave in self:
            if slave.terminated and (now - state.last_seen >
                                     timedelta(seconds=5)):
                del self.slaves[slave.slave_id]

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
        state.update(timestamp, msg, *args)


class SlaveState:
    """
    Class for tracking the state of a single build slave.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, slave_id):
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
    def color(self):
        """
        Calculate a simple color indicator for the slave.
        """
        if self.first_seen is not None:
            if datetime.utcnow() - self.last_seen > timedelta(minutes=15):
                return Color('#760')  # silent
            elif datetime.utcnow() - self.last_seen > self.timeout:
                return Color('red')  # dead
        if self.terminated:
            return Color('red')  # dead
        return Color('#050')
