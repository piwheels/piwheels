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

from . import cbor2


class Socket(zmq.Socket):
    # Customized zmq.Socket with CBOR-specific send and recv methods
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._protocol = kw.get('protocol', {})

    def dump_msg(self, msg, data=None):
        try:
            schema = self._protocol[msg]
        except KeyError:
            raise IOError('unknown message: %s' % msg)
        if data is None:
            if schema is not None:
                raise Invalid('data cannot be empty for %s' % msg)
            return pickle.dumps(msg)
        else:
            try:
                data = schema(data)
            except Invalid as e:
                raise IOError('invalid for %s: %s' % (msg, e))
            return pickle.dumps((msg, data))

    def load_msg(self, buf):
        if isinstance(buf, str):
            try:
                schema = self._protocol[buf]
            except KeyError:
                raise IOError('unknown message: %s' % buf)
            if schema is None:
                return buf, None
            raise IOError('missing data for: %s' % buf)
        else:
            try:
                msg, data = msg
            except TypeError, ValueError:
                raise IOError('invalid message structure received')
            try:
                return schema(data)
            except Invalid as e:
                raise IOError('invalid data for %s: %s' % (msg, e))

    def send_msg(self, msg, data=None, flags=0):
        self.send(self.dump_msg(msg, data), flags=flags)

    def recv_msg(self, flags=0):
        buf = self.recv(flags=flags)
        return self.load_msg(buf)

    def send_addr_msg(self, addr, msg, data=None, flags=0):
        self.send_multipart([address, b'', self.dump_msg(msg, data)], flags=flags)

    def recv_addr_msg(self, flags=0):
        try:
            addr, _, buf = self.recv_multipart()
        except TypeError, ValueError:
            raise IOError('invalid message structure from client')
        msg, data = self.load_msg(buf)
        return addr, msg, data


class Context(zmq.Context):
    # Customized zmq.Context which provides CBORSocket instances from its
    # socket() method
    _socket_class = Socket
