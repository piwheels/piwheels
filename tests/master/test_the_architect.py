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
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from piwheels import protocols, transport
from piwheels.master.the_architect import TheArchitect
from psycopg2.extensions import QueryCanceledError


UTC = timezone.utc


@pytest.fixture(scope='function')
def builds_queue(request, zmq_context, master_config):
    queue = zmq_context.socket(
        transport.PULL, protocol=reversed(protocols.the_architect))
    queue.bind(master_config.builds_queue)
    yield queue
    queue.close()


@pytest.fixture(scope='function')
def task(request, builds_queue, master_config):
    task = TheArchitect(master_config)
    yield task
    task.close()


def test_architect_queue(db, with_build, task, builds_queue):
    with mock.patch('piwheels.tasks.datetime') as dt:
        dt.now.return_value = datetime.now(tz=UTC)
        task.poll(0)
        assert builds_queue.recv_msg() == ('QUEUE', {'cp35m': [['foo', '0.1']]})
        with db.begin():
            db.execute("DELETE FROM builds")
        dt.now.return_value += timedelta(minutes=3)
        task.poll(0)
        assert builds_queue.recv_msg() == ('QUEUE', {'cp34m': [['foo', '0.1']]})


def test_architect_cancel(db, with_build, task, builds_queue):
    try:
        with mock.patch('piwheels.master.the_architect.Database') as db:
            query_event = Event()
            cancelled = Event()
            def get_build_queue(limit):
                if query_event.wait(5):
                    cancelled.set()
                    raise QueryCanceledError()
                return {}
            db().get_build_queue.side_effect = get_build_queue
            db()._conn.connection.cancel.side_effect = query_event.set
            task.db = db()
            task.start()
            while not task.can_cancel:
                cancelled.wait(0.1)
            task.quit()
            task.join(10)
            assert not task.is_alive()
            assert cancelled.wait(0)
    finally:
        task.close()
