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
This module augments the classes provided by pyzmq (the 0MQ Python bindings)
to use CBOR encoding, and voluptuous for message validation. It also tweaks a
few minor things like using seconds for timeouts.

.. autoclass:: Context
    :members:

.. autoclass:: Socket
    :members:

.. autoclass:: Poller
    :members:
"""

import logging
import ipaddress as ip
import datetime as dt
from binascii import hexlify

import zmq
from voluptuous import Invalid

import cbor2
from .protocols import Protocol, NoData


PUSH = zmq.PUSH
PULL = zmq.PULL
REQ = zmq.REQ
REP = zmq.REP
PUB = zmq.PUB
SUB = zmq.SUB
ROUTER = zmq.ROUTER
DEALER = zmq.DEALER

NOBLOCK = zmq.NOBLOCK
POLLIN = zmq.POLLIN
POLLOUT = zmq.POLLOUT

SUBSCRIBE = zmq.SUBSCRIBE
UNSUBSCRIBE = zmq.UNSUBSCRIBE

Error = zmq.ZMQError
Again = zmq.error.Again


def default_encoder(encoder, value):
    if isinstance(value, dt.timedelta):
        encoder.encode(
            cbor2.CBORTag(2001, (
                value.days, value.seconds, value.microseconds)))
    elif value is NoData:
        encoder.encode(cbor2.CBORTag(2002, None))
    else:
        raise cbor2.CBOREncodeError(
            'cannot serialize type %s' % value.__class__.__name__)


def default_decoder(decoder, tag):
    if tag.tag == 2001:
        days, seconds, microseconds = tag.value
        return dt.timedelta(
            days=days, seconds=seconds, microseconds=microseconds)
    elif tag.tag == 2002:
        return NoData
    return tag


class Context:
    """
    Wrapper for 0MQ :class:`zmq.Context`. This extends the :meth:`socket`
    method to include parameters for the socket's protocol and logger.
    """
    def __init__(self):
        self._context = zmq.Context.instance()

    def socket(self, sock_type, *, protocol=None, logger=None):
        return Socket(self._context.socket(sock_type), protocol, logger)

    def close(self, linger=1):
        self._context.destroy(linger=linger * 1000)
        self._context.term()


class Socket:
    """
    Wrapper for :class:`zmq.Socket`. This extends 0MQ's sockets to include a
    protocol which will be used to validate messages that are sent and received
    (via a voluptuous schema), and a logger which can be used to debug socket
    behaviour.
    """
    def __init__(self, socket, protocol=None, logger=None):
        if logger is None:
            logger = logging.getLogger()
        if protocol is None:
            protocol = Protocol()
        self._logger = logger
        self._socket = socket
        self._protocol = protocol
        self._socket.ipv6 = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    def _dump_msg(self, msg, data=NoData):
        try:
            schema = self._protocol.send[msg]
        except KeyError:
            raise IOError('unknown message: %s' % msg)
        if data is NoData:
            if schema is not NoData:
                raise IOError('data must be specified for %s' % msg)
            return cbor2.dumps(msg, default=default_encoder)
        else:
            if schema is NoData:
                raise IOError('no data expected for %s' % msg)
            try:
                data = schema(data)
            except Invalid as e:
                raise IOError('invalid data for %s: %r' % (msg, data))
            try:
                return cbor2.dumps((msg, data), default=default_encoder)
            except cbor2.CBOREncodeError as e:
                raise IOError('unable to serialize data')

    def _load_msg(self, buf):
        try:
            msg = cbor2.loads(buf, tag_hook=default_decoder)
        except cbor2.CBORDecodeError as e:
            raise IOError('unable to deserialize data')
        if isinstance(msg, str):
            try:
                schema = self._protocol.recv[msg]
            except KeyError:
                raise IOError('unknown message: %s' % msg)
            if schema is NoData:
                return msg, None
            raise IOError('missing data for: %s' % msg)
        else:
            try:
                msg, data = msg
            except (TypeError, ValueError):
                raise IOError('invalid message structure received')
            try:
                schema = self._protocol.recv[msg]
            except KeyError:
                raise IOError('unknown message: %s' % msg)
            if schema is NoData:
                raise IOError('data not expected for: %s' % msg)
            try:
                return msg, schema(data)
            except Invalid as e:
                raise IOError('invalid data for %s: %r' % (msg, data))

    @property
    def hwm(self):
        """
        The high-water mark of the socket, i.e. the number of messages that can
        be queued before the socket blocks (or drops, depending on the socket
        type) messages.
        """
        return self._socket.hwm

    @hwm.setter
    def hwm(self, value):
        self._socket.hwm = value

    def bind(self, address):
        """
        Binds the socket to listen on the specified *address*.
        """
        return self._socket.bind(address)

    def connect(self, address):
        """
        Connects the socket to the listening socket at *address*.
        """
        return self._socket.connect(address)

    def close(self, linger=None):
        """
        Closes the socket. If *linger* is specified, it is the number of
        seconds to wait for pending messages to be flushed.
        """
        return self._socket.close(
            linger=linger if linger is None else linger * 1000)

    def subscribe(self, topic):
        """
        Subscribes SUB type sockets to the specified *topic* (a string prefix).
        """
        self._socket.setsockopt_string(SUBSCRIBE, topic)

    def unsubscribe(self, topic):
        """
        Unsubscribes SUB type sockets from the specified *topic* (a string
        prefix).
        """
        self._socket.setsockopt_string(UNSUBSCRIBE, topic)

    def poll(self, timeout=None, flags=POLLIN):
        """
        Polls the socket for pending data (by default, when *flags* is POLLIN).
        If no data is available after *timeout* seconds, returns False.
        Otherwise returns True.

        If *flags* is POLLOUT instead, tests whether the socket has available
        slots for queueing new messages.
        """
        return self._socket.poll(
            timeout if timeout is None else timeout * 1000, flags)

    def send(self, buf, flags=0):
        """
        Send *buf* (a :class:`bytes` string).
        """
        self._logger.debug('>> %s', buf)
        return self._socket.send(buf, flags)

    def recv(self, flags=0):
        """
        Receives the next message as a :class:`bytes` string.
        """
        buf = self._socket.recv(flags)
        self._logger.debug('<< %s', buf)
        return buf

    def drain(self):
        """
        Receives all pending messages in the queue and discards them. This
        is typically useful during shutdown routines or for testing.
        """
        while self.poll(0):
            self.recv()

    def send_multipart(self, msg_parts, flags=0):
        """
        Send *msg_parts*, a list of :class:`bytes` strings as a multi-part
        message which can be received intact with :meth:`recv_multipart`.
        """
        self._logger.debug('>>' + (' %s' * len(msg_parts)), *msg_parts)
        return self._socket.send_multipart(msg_parts, flags)

    def recv_multipart(self, flags=0):
        """
        Receives a multi-part message, returning its content as a list of
        :class:`bytes` strings.
        """
        msg_parts = self._socket.recv_multipart(flags)
        self._logger.debug('<<' + (' %s' * len(msg_parts)), *msg_parts)
        return msg_parts

    def send_msg(self, msg, data=NoData, flags=0):
        """
        Send the unicode string *msg* with its associated *data* as a
        CBOR-encoded message. This is the primary method used in piwheels for
        sending information between tasks.

        The message, and its associated data, must validate against the
        :attr:`protocol` associated with the socket on construction.
        """
        self._logger.debug('>> %s %r', msg, data)
        return self._socket.send(self._dump_msg(msg, data), flags)

    def recv_msg(self, flags=0):
        """
        Receive a CBOR-encoded message, returning a tuple of the unicode
        message string and its associated data. This is the primary method used
        in piwheels for receving information into a task.

        The message, and its associated data, will be validated agains the
        :attr:`protocol` associated with the socket on construction.
        """
        msg, data = self._load_msg(self._socket.recv(flags))
        self._logger.debug('<< %s %r', msg, data)
        return msg, data

    def send_addr_msg(self, addr, msg, data=NoData, flags=0):
        """
        Send a CBOR-encoded message (and associated data) to *addr*, a
        :class:`bytes` string.
        """
        self._logger.debug('>> %s %s %r',
                           hexlify(addr).decode('ascii'), msg, data)
        self._socket.send_multipart([addr, b'', self._dump_msg(msg, data)],
                                    flags)

    def recv_addr_msg(self, flags=0):
        """
        Receive a CBOR-encoded message (and associated data) along with the
        address it came from (represented as a :class:`bytes` string).
        """
        try:
            addr, empty, buf = self._socket.recv_multipart(flags)
        except ValueError:
            raise IOError('invalid message structure received')
        msg, data = self._load_msg(buf)
        self._logger.debug('<< %s %s %r',
                           hexlify(addr).decode('ascii'), msg, data)
        return addr, msg, data


class Poller:
    """
    Wrapper for 0MQ :class:`zmq.Poller`. This simply tweaks 0MQ's poller to use
    seconds for timeouts, and to return a :class:`dict` by default from
    :meth:`poll`.
    """
    def __init__(self):
        self._poller = zmq.Poller()
        self._map = {}

    def register(self, sock, flags=POLLIN | POLLOUT):
        """
        Register *sock* with the poller, watching for events as specified by
        *flags* (which defaults to POLLIN and POLLOUT events).
        """
        if isinstance(sock, Socket):
            self._map[sock._socket] = sock
            return self._poller.register(sock._socket, flags)
        else:
            return self._poller.register(sock, flags)

    def unregister(self, sock):
        """
        Unregister *sock* from the poller. After this, calls to :meth:`poll`
        will never return references to *sock*.
        """
        if isinstance(sock, Socket):
            self._poller.unregister(sock._socket)
            del self._map[sock._socket]
        else:
            self._poller.unregister(sock)

    def poll(self, timeout=None):
        """
        Poll all registered sockets for the events they were registered with,
        for *timeout* seconds. Returns a dictionary mapping sockets to events
        or an empty dictinoary if the *timeout* elapsed with no events
        occurring.
        """
        return {
            self._map.get(sock, sock): event
            for sock, event in self._poller.poll(
                timeout if timeout is None else timeout * 1000)
        }
