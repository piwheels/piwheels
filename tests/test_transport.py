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


import os
import sys
import ipaddress as ip
import datetime as dt
from unittest import mock

import cbor2
import pytest
from voluptuous import Any

from piwheels.protocols import Protocol, NoData
from piwheels.transport import *


def test_ipaddress_roundtrip():
    protocol = Protocol(recv={'FOO': Any(ip.IPv4Address, ip.IPv6Address)})
    ctx = Context()
    pull = ctx.socket(PULL, protocol=protocol)
    push = ctx.socket(PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    address4 = ip.IPv4Address('192.168.0.1')
    address6 = ip.IPv6Address('::1')
    push.send_msg('FOO', address4)
    assert pull.recv_msg() == ('FOO', address4)
    push.send_msg('FOO', address6)
    assert pull.recv_msg() == ('FOO', address6)
    push.close()
    pull.close()


def test_timedelta_roundtrip():
    protocol = Protocol(recv={'FOO': dt.timedelta})
    ctx = Context()
    pull = ctx.socket(PULL, protocol=protocol)
    push = ctx.socket(PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    delta = dt.timedelta(minutes=5)
    push.send_msg('FOO', delta)
    assert pull.recv_msg() == ('FOO', delta)
    push.close()
    pull.close()


def test_encoding_unknown_type():
    protocol = Protocol(recv={'FOO': Exception})
    ctx = Context()
    pull = ctx.socket(PULL, protocol=protocol)
    push = ctx.socket(PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    with pytest.raises(IOError):
        push.send_msg('FOO', NotImplementedError())
    push.close()
    pull.close()


def test_decoding_unknown_type():
    ctx = Context()
    pull = ctx.socket(PULL)
    push = ctx.socket(PUSH)
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send(cbor2.dumps(cbor2.CBORTag(4000, None)))
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_recv_invalid_addr_msg_structure():
    ctx = Context()
    pull = ctx.socket(PULL)
    push = ctx.socket(PUSH)
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_multipart([b'foo', b'', b'', b''])
    with pytest.raises(IOError):
        pull.recv_addr_msg()


def test_send_data_for_pure_msg():
    protocol = Protocol(recv={'FOO': NoData})
    ctx = Context()
    pull = ctx.socket(PULL, protocol=protocol)
    push = ctx.socket(PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    with pytest.raises(IOError):
        push.send_msg('FOO', 1)
    push.close()
    pull.close()


def test_send_no_data_for_msg():
    protocol = Protocol(recv={'FOO': int})
    ctx = Context()
    pull = ctx.socket(PULL, protocol=protocol)
    push = ctx.socket(PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    with pytest.raises(IOError):
        push.send_msg('FOO')
    push.close()
    pull.close()


def test_send_bad_data_for_msg():
    protocol = Protocol(recv={'FOO': int})
    ctx = Context()
    pull = ctx.socket(PULL, protocol=protocol)
    push = ctx.socket(PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    with pytest.raises(IOError):
        push.send_msg('FOO', 'bar')
    push.close()
    pull.close()


def test_recv_bad_data_from_msg():
    ctx = Context()
    pull = ctx.socket(PULL, protocol=Protocol(recv={'FOO': int}))
    push = ctx.socket(PUSH, protocol=Protocol(send={'FOO': str}))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_msg('FOO', 'bar')
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_recv_no_data_from_msg():
    ctx = Context()
    pull = ctx.socket(PULL, protocol=Protocol(recv={'FOO': int}))
    push = ctx.socket(PUSH, protocol=Protocol(send={'FOO': NoData}))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_msg('FOO')
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_recv_unknown_msg():
    ctx = Context()
    pull = ctx.socket(PULL)
    push = ctx.socket(PUSH, protocol=Protocol(send={'FOO': int}))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_msg('FOO', 1)
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_recv_unexpected_data():
    ctx = Context()
    pull = ctx.socket(PULL, protocol=Protocol(recv={'FOO': NoData}))
    push = ctx.socket(PUSH, protocol=Protocol(send={'FOO': int}))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_msg('FOO', 1)
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_hwm_attr():
    ctx = Context()
    sock = ctx.socket(PULL)
    sock.hwm = 10
    assert sock.hwm == 10
    sock.close()


def test_subscribe():
    ctx = Context()
    pub = ctx.socket(PUB, protocol=Protocol(send={'FOO': int}))
    sub = ctx.socket(SUB, protocol=Protocol(recv={'FOO': int}))
    pub.bind('inproc://foo')
    sub.connect('inproc://foo')
    sub.subscribe('')
    pub.send_msg('FOO', 1)
    assert sub.recv_msg() == ('FOO', 1)
    sub.unsubscribe('')
    pub.send_msg('FOO', 2)
    assert not sub.poll(0.5)
    sub.close()
    pub.close()


def test_poll_fd(tmpdir):
    r, w = os.pipe()
    p = Poller()
    p.register(r)
    assert not p.poll(0.1)
    os.write(w, b'foo')
    assert p.poll(0.1)
    p.unregister(r)
    os.write(w, b'bar')
    assert not p.poll(0.1)
    os.close(w)
    os.close(r)
