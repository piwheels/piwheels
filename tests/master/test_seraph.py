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


import cbor2
import pytest

from piwheels import const, transport
from piwheels.master.seraph import Seraph


def test_router(zmq_context, master_config):
    seraph = Seraph(master_config)
    seraph.start()
    try:
        client = zmq_context.socket(transport.REQ)
        client.connect(master_config.db_queue)
        worker = zmq_context.socket(transport.REQ)
        worker.connect(const.ORACLE_QUEUE)
        worker.send(b'READY')
        client.send(cbor2.dumps(['FOO']))
        client_addr, empty, msg = worker.recv_multipart()
        assert cbor2.loads(msg) == ['FOO']
        worker.send_multipart([client_addr, empty, cbor2.dumps(['BAR'])])
        assert cbor2.loads(client.recv()) == ['BAR']
    finally:
        seraph.quit()
        seraph.join()


def test_router_no_workers(zmq_context, master_config):
    seraph = Seraph(master_config)
    seraph.start()
    try:
        client = zmq_context.socket(transport.REQ)
        client.connect(master_config.db_queue)
        client.send(cbor2.dumps(['FOO']))
        with pytest.raises(transport.Error):
            client.recv(flags=transport.NOBLOCK)
        worker = zmq_context.socket(transport.REQ)
        worker.connect(const.ORACLE_QUEUE)
        worker.send(b'READY')
        client_addr, empty, msg = worker.recv_multipart()
        assert cbor2.loads(msg) == ['FOO']
        worker.send_multipart([client_addr, empty, cbor2.dumps(['BAR'])])
        assert cbor2.loads(client.recv()) == ['BAR']
    finally:
        seraph.quit()
        seraph.join()
