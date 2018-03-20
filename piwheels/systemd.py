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


.. autofunction:: available

.. autofunction:: notify

.. autofunction:: ready

.. autofunction:: reloading

.. autofunction:: stopping

.. autofunction:: watchdog_ping

.. autofunction:: watchdog_reset

.. autofunction:: watchdog_enabled

.. autofunction:: main_pid
"""

import os
import socket


def _init_socket():
    # Remove NOTIFY_SOCKET implicitly so child processes don't inherit it
    addr = os.environ.pop('NOTIFY_SOCKET', None)
    if addr is not None:
        if addr[0] == '@':
            addr = '\0' + addr[1:] # abstract namespace socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            s.connect(addr)
        except IOError:
            return None
        return s


_notify_socket = _init_socket()


if _notify_socket is None:
    def available():
        """
        If systemd's notification socket is not available, raises
        :exc:`RuntimeError`. Services expecting systemd notifications to be
        available can call this to assert that notifications will be noticed.
        """
        raise RuntimeError("systemd notification socket unavailable")


    def notify(state):
        """
        Send a notification to systemd. *state* is a string type (if it is a
        unicode string it will be encoded with the 'ascii' codec).
        """
        pass


else:
    def available():
        """
        If systemd's notification socket is not available, raises
        :exc:`RuntimeError`. Services expecting systemd notifications to be
        available can call this to assert that notifications will be noticed.
        """
        pass


    def notify(state):
        """
        Send a notification to systemd. *state* is a string type (if it is a
        unicode string it will be encoded with the 'ascii' codec).
        """
        if isinstance(state, str):
            state = state.encode('ascii')
        _notify_socket.sendall(state)


def ready():
    """
    Notify systemd that service startup is complete.
    """
    notify(b'READY=1')


def reloading():
    """
    Notify systemd that the service is reloading its configuration. Call
    :func:`ready` when reload is complete.
    """
    notify(b'RELOADING=1')


def stopping():
    """
    Notify systemd that the service is stopping.
    """
    notify(b'STOPPING=1')


def extend_timeout(timeout):
    """
    Notify systemd to extend the start / stop timeout by *timeout* seconds.
    A timeout will occur if the service does not call :func:`ready` or
    terminate within *timeout* seconds but *only* if the original timeout
    (set in the systemd configuration) has already been exceeded.

    For example, if the stopping timeout is configured as 90s, and the service
    calls :func:`stopping`, systemd expects the service to terminate within
    90s. After 10s the service calls :func:`extend_timeout` with a *timeout*
    of 10s. 20s later the service has not yet terminated but systemd does
    *not* consider the timeout expired as only 30s have elapsed of the original
    90s timeout.
    """
    notify('EXTEND_TIMEOUT_USEC=%d' % int(timeout * 1000000))


def watchdog_ping():
    """
    Ping the systemd watchdog. This must be done periodically if
    :func:`watchdog_enabled` returns True.
    """
    notify(b'WATCHDOG=1')


def watchdog_reset(timeout):
    """
    Reset the systemd watchdog timer to *timeout* seconds.
    """
    notify('WATCHDOG_USEC=%d' % int(timeout * 1000000))


def watchdog_enabled(*, unset_environment=False):
    """
    Returns the time (in seconds) before which systemd expects the process
    to call :func:`watchdog_ping`. If a watchdog timeout is not set, the
    function returns ``None``.

    If *unset_environment* is ``True``, the watchdog environment variables
    will be unset (so no future child processes will inherit them). Subsequent
    calls to this function will return ``None`` in this case.
    """
    try:
        timeout = os.environ.get('WATCHDOG_USEC')
        if timeout is not None:
            pid = os.environ.get('WATCHDOG_PID')
            if pid is None or pid == os.getpid():
                return timeout / 1000000
        return None
    finally:
        if unset_environment:
            os.environ.pop('WATCHDOG_USEC', None)
            os.environ.pop('WATCHDOG_PID', None)


def main_pid(pid=None):
    """
    Report the main PID of the process to systemd (for services that confuse
    systemd with their forking behaviour). If *pid* is None, :func:`os.getpid`
    is called to determine the calling process' PID.
    """
    if pid is None:
        pid = os.getpid()
    notify('MAINPID=%d' % pid)


# TODO fd storage, retrieval, and listening
