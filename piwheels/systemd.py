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
Provides a simple interface to systemd's notification and watchdog services.

.. autoclass:: Systemd
"""

import os
import socket


class Systemd:
    """
    Provides a simple interface to systemd's notification and watchdog
    services. It is suggested applications construct a single, top-level
    instance of this class and use it to communicate with systemd.
    """

    __slots__ = ('_socket',)

    def __init__(self, address=None):
        # Remove NOTIFY_SOCKET implicitly so child processes don't inherit it
        self._socket = None
        if address is None:
            address = os.environ.pop('NOTIFY_SOCKET', None)
        if address is not None:
            if len(address) <= 1 or address[0] not in ('@', '/'):
                return None
            if address[0] == '@':
                address = '\0' + address[1:] # abstract namespace socket
            self._socket = socket.socket(socket.AF_UNIX,
                              socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
            try:
                self._socket.connect(address)
            except IOError:
                self._socket = None

    def available(self):
        """
        If systemd's notification socket is not available, raises
        :exc:`RuntimeError`. Services expecting systemd notifications to be
        available can call this to assert that notifications will be noticed.
        """
        if self._socket is None:
            raise RuntimeError("systemd notification socket unavailable")

    def notify(self, state):
        """
        Send a notification to systemd. *state* is a string type (if it is a
        unicode string it will be encoded with the 'ascii' codec).
        """
        if self._socket is not None:
            if isinstance(state, str):
                state = state.encode('ascii')
            self._socket.sendall(state)

    def ready(self):
        """
        Notify systemd that service startup is complete.
        """
        self.notify(b'READY=1')

    def reloading(self):
        """
        Notify systemd that the service is reloading its configuration. Call
        :func:`ready` when reload is complete.
        """
        self.notify(b'RELOADING=1')

    def stopping(self):
        """
        Notify systemd that the service is stopping.
        """
        self.notify(b'STOPPING=1')

    def extend_timeout(self, timeout):
        """
        Notify systemd to extend the start / stop timeout by *timeout* seconds.
        A timeout will occur if the service does not call :func:`ready` or
        terminate within *timeout* seconds but *only* if the original timeout
        (set in the systemd configuration) has already been exceeded.

        For example, if the stopping timeout is configured as 90s, and the
        service calls :func:`stopping`, systemd expects the service to
        terminate within 90s. After 10s the service calls
        :func:`extend_timeout` with a *timeout* of 10s. 20s later the service
        has not yet terminated but systemd does *not* consider the timeout
        expired as only 30s have elapsed of the original 90s timeout.
        """
        self.notify('EXTEND_TIMEOUT_USEC=%d' % int(timeout * 1000000))

    def watchdog_ping(self):
        """
        Ping the systemd watchdog. This must be done periodically if
        :func:`watchdog_period` returns a value other than ``None``.
        """
        self.notify(b'WATCHDOG=1')

    def watchdog_reset(self, timeout):
        """
        Reset the systemd watchdog timer to *timeout* seconds.
        """
        self.notify('WATCHDOG_USEC=%d' % int(timeout * 1000000))

    def watchdog_period(self):
        """
        Returns the time (in seconds) before which systemd expects the process
        to call :func:`watchdog_ping`. If a watchdog timeout is not set, the
        function returns ``None``.
        """
        timeout = os.environ.get('WATCHDOG_USEC')
        if timeout is not None:
            pid = os.environ.get('WATCHDOG_PID')
            if pid is None or int(pid) == os.getpid():
                return int(timeout) / 1000000
        return None

    def watchdog_clean(self):
        """
        Unsets the watchdog environment variables so that no future child
        processes will inherit them.

        .. warning::

            After calling this function, :func:`watchdog_period` will return
            ``None`` but systemd will continue expecting :func:`watchdog_ping`
            to be called periodically. In other words, you should call
            :func:`watchdog_period` first and store its result somewhere before
            calling this function.
        """
        os.environ.pop('WATCHDOG_USEC', None)
        os.environ.pop('WATCHDOG_PID', None)

    def main_pid(self, pid=None):
        """
        Report the main PID of the process to systemd (for services that
        confuse systemd with their forking behaviour). If *pid* is None,
        :func:`os.getpid` is called to determine the calling process' PID.
        """
        if pid is None:
            pid = os.getpid()
        self.notify('MAINPID=%d' % pid)

    # TODO fd storage, retrieval, and listening


_SYSTEMD = None
def get_systemd():
    global _SYSTEMD
    if _SYSTEMD is None:
        _SYSTEMD = Systemd()
    return _SYSTEMD
