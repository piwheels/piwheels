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
from unittest import mock
from threading import Event
from datetime import datetime

import zmq
import pytest

from piwheels import const
from piwheels.master.the_secretary import TheSecretary


@pytest.fixture()
def task(request, zmq_context, master_config):
    task = TheSecretary(master_config)
    yield task
    task.close()


@pytest.fixture()
def web_queue(request, zmq_context, task, master_config):
    queue = zmq_context.socket(zmq.PUSH)
    queue.hwm = 10
    queue.connect(master_config.web_queue)
    yield queue
    queue.close()


@pytest.fixture()
def scribe_queue(request, zmq_context, task):
    queue = zmq_context.socket(zmq.PULL)
    queue.hwm = 10
    queue.connect(const.SCRIBE_QUEUE)
    yield queue
    queue.close()


def test_pass_through(task, web_queue, scribe_queue):
    web_queue.send_pyobj(['HOME', {'some': 'stats'}])
    task.poll()
    assert scribe_queue.recv_pyobj() == ['HOME', {'some': 'stats'}]
    web_queue.send_pyobj(['SEARCH', {'some': 'data'}])
    task.poll()
    assert scribe_queue.recv_pyobj() == ['SEARCH', {'some': 'data'}]


def test_bad_request(task, web_queue):
    web_queue.send_pyobj(['FOO'])
    e = Event()
    task.logger = mock.Mock()
    task.logger.error.side_effect = lambda *args: e.set()
    task.poll()
    assert e.wait(1)
    assert task.logger.error.call_args('invalid web_queue message: %s', 'FOO')


def test_buffer(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt:
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 0)
        task.loop()
        web_queue.send_pyobj(['PKGPROJ', 'foo'])
        task.poll()
        task.loop()
        with pytest.raises(zmq.error.Again):
            assert scribe_queue.recv_pyobj(flags=zmq.NOBLOCK)
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 35, 0)
        task.loop()
        assert scribe_queue.recv_pyobj() == ['PKGPROJ', 'foo']


def test_upgrade(task, web_queue, scribe_queue):
    with mock.patch('piwheels.master.the_secretary.datetime') as dt:
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 0)
        task.loop()
        web_queue.send_pyobj(['PKGPROJ', 'foo'])
        task.poll()
        task.loop()
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 30)
        web_queue.send_pyobj(['PKGBOTH', 'foo'])
        task.poll()
        task.loop()
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 31)
        web_queue.send_pyobj(['PKGPROJ', 'bar'])
        task.poll()
        task.loop()
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 30, 32)
        web_queue.send_pyobj(['PKGPROJ', 'bar'])
        task.poll()
        task.loop()
        dt.utcnow.return_value = datetime(2018, 1, 1, 12, 35, 0)
        task.loop()
        assert scribe_queue.recv_pyobj() == ['PKGBOTH', 'foo']
        assert scribe_queue.recv_pyobj() == ['PKGPROJ', 'bar']
