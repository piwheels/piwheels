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


import sys
import ipaddress as ip
import datetime as dt
from unittest import mock

import zmq
import pytest
from voluptuous import Any

from piwheels import cbor2
from piwheels.protocols import Protocol, NoData
from piwheels.transport import Context, Socket


def test_ipaddress_roundtrip():
    protocol = Protocol(recv={'FOO': Any(ip.IPv4Address, ip.IPv6Address)})
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=protocol)
    push = ctx.socket(zmq.PUSH, protocol=reversed(protocol))
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
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=protocol)
    push = ctx.socket(zmq.PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    delta = dt.timedelta(minutes=5)
    push.send_msg('FOO', delta)
    assert pull.recv_msg() == ('FOO', delta)
    push.close()
    pull.close()


def test_encoding_unknown_type():
    protocol = Protocol(recv={'FOO': Exception})
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=protocol)
    push = ctx.socket(zmq.PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    with pytest.raises(IOError):
        push.send_msg('FOO', NotImplementedError())
    push.close()
    pull.close()


def test_decoding_unknown_type():
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL)
    push = ctx.socket(zmq.PUSH)
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send(cbor2.dumps(cbor2.CBORTag(4000, None)))
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_cbor_roundtrip():
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL)
    push = ctx.socket(zmq.PUSH)
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_cbor(True)
    assert pull.recv_cbor() == True
    push.send_cbor(10000000000)
    assert pull.recv_cbor() == 10000000000
    push.send_cbor(['foo', 'bar'])
    assert pull.recv_cbor() == ['foo', 'bar']
    push.close()
    pull.close()


def test_recv_invalid_addr_msg_structure():
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL)
    push = ctx.socket(zmq.PUSH)
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_multipart([b'foo', b'', b'', b''])
    with pytest.raises(IOError):
        pull.recv_addr_msg()


def test_send_data_for_pure_msg():
    protocol = Protocol(recv={'FOO': NoData})
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=protocol)
    push = ctx.socket(zmq.PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    with pytest.raises(IOError):
        push.send_msg('FOO', 1)
    push.close()
    pull.close()


def test_send_no_data_for_msg():
    protocol = Protocol(recv={'FOO': int})
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=protocol)
    push = ctx.socket(zmq.PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    with pytest.raises(IOError):
        push.send_msg('FOO')
    push.close()
    pull.close()


def test_send_bad_data_for_msg():
    protocol = Protocol(recv={'FOO': int})
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=protocol)
    push = ctx.socket(zmq.PUSH, protocol=reversed(protocol))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    with pytest.raises(IOError):
        push.send_msg('FOO', 'bar')
    push.close()
    pull.close()


def test_recv_bad_data_from_msg():
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=Protocol(recv={'FOO': int}))
    push = ctx.socket(zmq.PUSH, protocol=Protocol(send={'FOO': str}))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_msg('FOO', 'bar')
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_recv_no_data_from_msg():
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=Protocol(recv={'FOO': int}))
    push = ctx.socket(zmq.PUSH, protocol=Protocol(send={'FOO': NoData}))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_msg('FOO')
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_recv_unknown_msg():
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL)
    push = ctx.socket(zmq.PUSH, protocol=Protocol(send={'FOO': int}))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_msg('FOO', 1)
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()


def test_recv_unexpected_data():
    ctx = Context.instance()
    pull = ctx.socket(zmq.PULL, protocol=Protocol(recv={'FOO': NoData}))
    push = ctx.socket(zmq.PUSH, protocol=Protocol(send={'FOO': int}))
    pull.bind('inproc://foo')
    push.connect('inproc://foo')
    push.send_msg('FOO', 1)
    with pytest.raises(IOError):
        pull.recv_msg()
    push.close()
    pull.close()
