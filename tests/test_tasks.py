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


import logging
from unittest import mock
from datetime import datetime, timedelta
from time import sleep

import pytest

from piwheels import protocols, transport, tasks


class CounterTask(tasks.PauseableTask):
    # A trivial task purely for test purposes, with a very rapid poll cycle
    name = 'counter'

    def __init__(self, config, control_protocol=protocols.task_control,
                 delay=timedelta(microseconds=1)):
        super().__init__(config, control_protocol)
        self.every(delay, self.loop)
        self.count = 0

    def loop(self):
        self.count += 1

    def poll(self, timeout=0.1):
        return super().poll(timeout)

    def foo(self):
        pass


class SimpleTask(tasks.Task):
    name = 'simple'


class BrokenTask(tasks.Task):
    # A trivial task which instantly breaks
    name = 'broken'

    def __init__(self, config, control_protocol=protocols.task_control):
        super().__init__(config, control_protocol)
        self.every(timedelta(microseconds=1), self.loop)

    def loop(self):
        raise Exception("Don't panic!")


def test_task_quits(master_config):
    task = tasks.Task(master_config)
    try:
        task.start()
        task.quit()
        task.join(10)
        assert not task.is_alive()
    finally:
        task.close()


def test_task_runs(master_config):
    task = CounterTask(master_config)
    try:
        task.start()
        task.quit()
        task.join(10)
        assert task.count > 0
    finally:
        task.close()


def test_task_force(master_config):
    task = CounterTask(master_config, delay=timedelta(seconds=1))
    try:
        task.start()
        start = datetime.utcnow()
        while task.count == 0:
            sleep(0.01)
        assert datetime.utcnow() - start < timedelta(seconds=1)
        start = datetime.utcnow()
        task.force(task.loop)
        while task.count == 1:
            sleep(0.01)
        assert datetime.utcnow() - start < timedelta(seconds=1)
        task.quit()
        task.join(10)
        assert task.count > 0
        with pytest.raises(ValueError):
            task.force(task.foo)
    finally:
        task.close()


def test_task_pause(master_config):
    task = CounterTask(master_config)
    try:
        task.start()
        task.pause()
        sleep(0.01)
        current = task.count
        sleep(0.01)
        assert task.count == current
        task.resume()
        task.quit()
        task.join(10)
        assert task.count > current
    finally:
        task.close()


def test_task_pause_resume_idempotent(master_config):
    task = CounterTask(master_config)
    try:
        task.start()
        task.pause()
        task.pause()
        task.resume()
        task.resume()
        task.quit()
        task.join(10)
        assert not task.is_alive()
    finally:
        task.close()


def test_task_quit_while_paused(master_config):
    task = CounterTask(master_config)
    try:
        task.start()
        task.pause()
        task.quit()
        task.join(10)
        assert not task.is_alive()
    finally:
        task.close()


def test_task_resume_while_not_paused(master_config):
    task = CounterTask(master_config)
    try:
        task.logger = mock.Mock()
        task.start()
        task.resume()
        task.quit()
        task.join(10)
        assert not task.is_alive()
        assert task.logger.warning.call_count == 1
    finally:
        task.close()


def test_broken_control(master_config, caplog):
    protocol = protocols.Protocol(recv={
        'FOO': protocols.NoData,
        'QUIT': protocols.NoData,
    })
    task = CounterTask(master_config, control_protocol=protocol)
    try:
        task.start()
        task._ctrl('FOO')
        task.quit()
        task.join(10)
        assert not task.is_alive()
        assert caplog.record_tuples == [
            ('counter', logging.INFO, 'starting'),
            ('counter', logging.INFO, 'started'),
            ('counter', logging.ERROR, 'unhandled exception in %r' % task),
            ('counter', logging.INFO, 'stopped'),
        ]
    finally:
        task.close()
    caplog.clear()
    task = SimpleTask(master_config, control_protocol=protocol)
    try:
        task.start()
        task._ctrl('FOO')
        task.quit()
        task.join(10)
        assert not task.is_alive()
        assert caplog.record_tuples == [
            ('simple', logging.INFO, 'starting'),
            ('simple', logging.INFO, 'started'),
            ('simple', logging.ERROR, 'unhandled exception in %r' % task),
            ('simple', logging.INFO, 'stopped'),
        ]
    finally:
        task.close()


def test_bad_control(master_config, caplog):
    task = CounterTask(master_config)
    try:
        task.start()
        sock = task.ctx.socket(
            transport.PUSH, protocol=reversed(task.control_protocol),
            logger=task.logger)
        sock.connect('inproc://ctrl-counter')
        sock.send(b'FOO')
        sock.close()
        task.quit()
        task.join(10)
        assert not task.is_alive()
        assert caplog.record_tuples == [
            ('counter', logging.INFO, 'starting'),
            ('counter', logging.INFO, 'started'),
            ('counter', logging.ERROR, 'unable to deserialize data'),
            ('counter', logging.INFO, 'stopping'),
            ('counter', logging.INFO, 'stopped'),
        ]
    finally:
        task.close()
    caplog.clear()
    task = SimpleTask(master_config)
    try:
        task.start()
        sock = task.ctx.socket(
            transport.PUSH, protocol=reversed(task.control_protocol),
            logger=task.logger)
        sock.connect('inproc://ctrl-simple')
        sock.send(b'FOO')
        sock.close()
        task.quit()
        task.join(10)
        assert not task.is_alive()
        assert caplog.record_tuples == [
            ('simple', logging.INFO, 'starting'),
            ('simple', logging.INFO, 'started'),
            ('simple', logging.ERROR, 'unable to deserialize data'),
            ('simple', logging.INFO, 'stopping'),
            ('simple', logging.INFO, 'stopped'),
        ]
    finally:
        task.close()


def test_broken_task_quits(master_config, master_control_queue):
    task = BrokenTask(master_config)
    try:
        task.start()
        task.join(10)
        assert not task.is_alive()
        # Ensure the broken task tells the master to quit
        assert master_control_queue.recv_msg() == ('QUIT', None)
    finally:
        task.close()
