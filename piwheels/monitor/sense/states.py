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
    :members:

.. autoclass:: MasterState
    :members:

.. autoclass:: SlaveState
    :members:
"""

from datetime import datetime, timedelta, timezone

from colorzero import Color, Hue

from .. import states


UTC = timezone.utc


class SlaveList:
    """
    Tracks the active set of build slaves currently known by the master.
    Provides methods to update the state of the list based on messages received
    on the external status queue.
    """
    def __init__(self):
        self.slaves = {None: MasterState()}

    def __len__(self):
        return len(self.slaves)

    def __getitem__(self, index):
        return self._sorted_list()[index]

    def __iter__(self):
        for slave in self._sorted_list():
            yield slave

    def _sorted_list(self):
        return sorted(self.slaves.values(),
                      key=lambda state: state.sort_key)

    def prune(self):
        now = datetime.now(tz=UTC)
        for slave in self._sorted_list():
            if slave.killed and (now - slave.last_seen > timedelta(seconds=5)):
                # TODO Don't remove the master widget
                del self.slaves[slave.slave_id]

    def message(self, slave_id, timestamp, msg, data):
        """
        Update the list with a message from the external status queue.

        :param int slave_id:
            The id of the slave the message was originally sent to.

        :param datetime.datetime timestamp:
            The timestamp when the message was originally sent.

        :param str msg:
            The reply that was sent to the build slave.

        :param data:
            Any data that went with the message.
        """
        try:
            state = self.slaves[slave_id]
        except KeyError:
            state = SlaveState(slave_id)
            self.slaves[slave_id] = state
        state.update(timestamp, msg, data)


class MasterState(states.MasterState):
    """
    Class for tracking the state of the master. :class:`SlaveList` stores an
    instance of this against slave_id ``None``.
    """
    @property
    def color(self):
        return {
            'okay':   Color('#060'),
            'silent': Color('#760'),
            'dead':   Color('red'),
        }[self.state]


class SlaveState(states.SlaveState):
    """
    Class for tracking the state of a single build slave. :class:`SlaveList`
    stores instances of this keyed by the *slave_id*.
    """
    @property
    def color(self):
        """
        Calculate a simple color indicator for the slave.
        """
        return {
            'idle':     Color('#333'),
            'building': Color('#060'),
            'sending':  Color('#007'),
            'cleaning': Color('#707'),
            'silent':   Color('#760'),
            'dead':     Color('red'),
        }[self.state]
