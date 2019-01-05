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
from time import sleep

import zmq
import pytest

from piwheels.master.tasks import Task, TaskQuit, PauseableTask


class CounterTask(PauseableTask):
    # A trivial task purely for test purposes, with a very rapid poll cycle
    name = 'counter'

    def __init__(self, config):
        super().__init__(config)
        self.count = 0

    def loop(self):
        self.count += 1

    def poll(self):
        super().poll(1)


def test_task_quits(master_config, master_control_queue):
    task = Task(master_config)
    task.start()
    task.quit()
    task.join(10)
    assert not task.is_alive()


def test_task_runs(master_config, master_control_queue):
    task = CounterTask(master_config)
    task.start()
    task.quit()
    task.join(10)
    assert task.count > 0


def test_task_pause(master_config, master_control_queue):
    task = CounterTask(master_config)
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


def test_task_pause_resume_idempotent(master_config, master_control_queue):
    task = CounterTask(master_config)
    task.start()
    task.pause()
    task.pause()
    task.resume()
    task.resume()
    task.quit()
    task.join(10)
    assert not task.is_alive()


def test_task_quit_while_paused(master_config, master_control_queue):
    task = CounterTask(master_config)
    task.start()
    task.pause()
    task.quit()
    task.join(10)
    assert not task.is_alive()


def test_broken_task_quits(master_config, master_control_queue):
    class BrokenTask(Task):
        def loop(self):
            raise Exception("Don't panic!")
    task = BrokenTask(master_config)
    task.start()
    task.join(10)
    assert not task.is_alive()
    # Ensure the broken task tells the master to quit
    assert master_control_queue.recv_msg() == ('QUIT', None)
