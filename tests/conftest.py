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

import zmq
import pytest

from piwheels import const


@pytest.fixture(scope='function')
def zmq_context(request):
    context = zmq.Context.instance()
    def fin():
        context.destroy()
        context.term()
    request.addfinalizer(fin)
    return context


@pytest.fixture()
def master_config(request):
    config = mock.Mock()
    config.index_queue = 'inproc://tests-indexes'
    config.status_queue = 'inproc://tests-status'
    config.control_queue = 'inproc://tests-control'
    config.builds_queue = 'inproc://tests-builds'
    config.db_queue = 'inproc://tests-db'
    config.fs_queue = 'inproc://tests-fs'
    config.slave_queue = 'inproc://tests-slave-driver'
    config.file_queue = 'inproc://tests-file-juggler'
    config.import_queue = 'inproc://tests-imports'
    config.log_queue = 'inproc://tests-logger'
    return config


@pytest.fixture(scope='function')
def master_control_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PULL)
    queue.hwm = 10
    queue.bind(master_config.control_queue)
    def fin():
        queue.close()
    request.addfinalizer(fin)
    return queue


@pytest.fixture(scope='function')
def master_status_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(zmq.PULL)
    queue.hwm = 10
    queue.bind(const.INT_STATUS_QUEUE)
    def fin():
        queue.close()
    request.addfinalizer(fin)
    return queue