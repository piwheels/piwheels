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


def test_log_valid_download(db_queue, log_queue, download_state, task):
    log_queue.send_msg('LOGDOWNLOAD', list(download_state))
    db_queue.expect('LOGDOWNLOAD', download_state)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()


def test_log_valid_search(db_queue, log_queue, search_state, task):
    log_queue.send_msg('LOGSEARCH', list(search_state))
    db_queue.expect('LOGSEARCH', search_state)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()


def test_log_valid_project_page_hit(db_queue, log_queue, project_state, task):
    log_queue.send_msg('LOGPROJECT', list(project_state))
    db_queue.expect('LOGPROJECT', project_state)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()


def test_log_valid_json_hit(db_queue, log_queue, json_state, task):
    log_queue.send_msg('LOGJSON', list(json_state))
    db_queue.expect('LOGJSON', json_state)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()


def test_log_valid_webpage_hit(db_queue, log_queue, page_state, task):
    log_queue.send_msg('LOGPAGE', list(page_state))
    db_queue.expect('LOGPAGE', page_state)
    db_queue.send('OK', None)
    task.poll(0)
    db_queue.check()


def test_log_invalid(db_queue, log_queue, task):
    log_queue.send(b'FOO')
    task.poll(0)
    assert task.logger.error.call_count == 1


def test_log_summary(db_queue, log_queue, download_state, project_state, task):
    log_queue.send_msg('LOGDOWNLOAD', list(download_state))
    log_queue.send_msg('LOGPROJECT', list(project_state))
    db_queue.expect('LOGDOWNLOAD', download_state)
    db_queue.send('OK', None)
    db_queue.expect('LOGPROJECT', project_state)
    db_queue.send('OK', None)
    task.poll(0)
    task.poll(0)
    db_queue.check()
    task.log_counters()
    # Index [-2] is python<3.8 for call.args
    assert set(call[-2] for call in task.logger.info.call_args_list) == {
        ('logged %d %s in the last minute', 1, 'downloads'),
        ('logged %d %s in the last minute', 1, 'project hits'),
    }
    for msg, count in task.counters.items():
        assert count == 0
