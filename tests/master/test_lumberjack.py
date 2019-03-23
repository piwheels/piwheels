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


from unittest import mock

import pytest

from piwheels import protocols, transport
from piwheels.master.lumberjack import Lumberjack


@pytest.fixture(scope='function')
def task(request, zmq_context, master_config):
    task = Lumberjack(master_config)
    task.logger = mock.Mock()
    yield task
    task.close()


@pytest.fixture(scope='function')
def log_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.PUSH, protocol=reversed(protocols.lumberjack))
    queue.connect(master_config.log_queue)
    yield queue
    queue.close()


def test_log_valid(db_queue, log_queue, download_state, task):
    log_queue.send_msg('LOG', list(download_state))
    db_queue.expect('LOGDOWNLOAD', download_state)
    db_queue.send('OK', None)
    task.poll()
    assert task.logger.info.call_args == mock.call(
        'logging download of %s from %s',
        download_state.filename, download_state.host)
    db_queue.check()


def test_log_invalid(db_queue, log_queue, task):
    log_queue.send(b'FOO')
    task.poll()
    assert task.logger.error.call_count == 1
