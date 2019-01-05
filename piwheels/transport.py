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

import pickle

import zmq
from voluptuous import Invalid

from .protocols import Protocol, NoData


class Socket(zmq.Socket):
    # Customized zmq.Socket with protocol checking and CBOR-specific send and
    # recv methods; _protocol needs to be defined at the class level otherwise
    # pyzmq's __setattr__ denies assignment
    _protocol = None

    def __init__(self, *a, **kw):
        protocol = kw.pop('protocol', Protocol())
        super().__init__(*a, **kw)
        self._protocol = protocol

    def dump_msg(self, msg, data=NoData):
        try:
            schema = self._protocol.send[msg]
        except KeyError:
            raise IOError('unknown message: %s' % msg)
        if data is NoData:
            if schema is not NoData:
                raise Invalid('data must be specified for %s' % msg)
            return pickle.dumps(msg)
        else:
            if schema is NoData:
                raise Invalid('no data expected for %s' % msg)
            try:
                data = schema(data)
            except Invalid as e:
                raise IOError('invalid data for %s: %s' % (msg, e))
            return pickle.dumps((msg, data))

    def load_msg(self, buf):
        try:
            msg = pickle.loads(buf)
        except Exception as e:
            # XXX Change except to CBORDecoderError when moving to CBOR; pretty
            # much any error can occur during unpickling
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
                raise IOError('invalid data for %s: %s' % (msg, e))

    def send_msg(self, msg, data=NoData, flags=0):
        self.send(self.dump_msg(msg, data), flags=flags)

    def recv_msg(self, flags=0):
        buf = self.recv(flags=flags)
        return self.load_msg(buf)

    def send_addr_msg(self, addr, msg, data=NoData, flags=0):
        self.send_multipart([addr, b'', self.dump_msg(msg, data)], flags=flags)

    def recv_addr_msg(self, flags=0):
        try:
            addr, empty, buf = self.recv_multipart()
        except ValueError:
            raise IOError('invalid message structure received')
        msg, data = self.load_msg(buf)
        return addr, msg, data


class Context(zmq.Context):
    _socket_class = Socket
