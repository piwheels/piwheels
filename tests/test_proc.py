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


import re
from unittest import mock
from threading import Event, Thread
from datetime import datetime, timedelta
from time import sleep

import pytest

from piwheels import proc


@pytest.fixture(scope='function')
def stop_event(request):
    yield Event()


@pytest.fixture()
def stop_after(stop_event):
    class StopAfter(Thread):
        def __init__(self, seconds):
            super().__init__()
            self.when = seconds
            self.start()
        def run(self):
            sleep(self.when)
            stop_event.set()
    yield StopAfter


def test_terminated_exc(stop_event):
    exc = proc.ProcessTerminated('foo', stop_event, b'bar', b'baz')
    assert str(exc) == "Command 'foo' was terminated early by event"
    assert exc.stderr == b'baz'
    assert exc.stdout == b'bar'
    assert exc.output == b'bar'
    exc.stdout = b'bar2'
    assert exc.stdout == b'bar2'
    assert exc.output == b'bar2'
    exc.output = b'bar3'
    assert exc.stdout == b'bar3'
    assert exc.output == b'bar3'


def test_proc_call_timeout():
    start = datetime.utcnow()
    with pytest.raises(proc.TimeoutExpired):
        proc.call(['sleep', '10'], timeout=0.1)
    assert datetime.utcnow() - start < timedelta(seconds=10)


def test_proc_call_stopped(stop_event, stop_after):
    start = datetime.utcnow()
    stop_after(0.1)
    with pytest.raises(proc.ProcessTerminated):
        proc.call(['sleep', '10'], event=stop_event)
    assert datetime.utcnow() - start < timedelta(seconds=10)


def test_proc_call_kill():
    args = ['sleep', '10']
    with mock.patch('subprocess.Popen') as popen:
        def wait(timeout=None):
            raise proc.TimeoutExpired(args, 1)
        popen().__enter__().wait.side_effect = wait
        with pytest.raises(proc.TimeoutExpired):
            proc.call(args, timeout=0.1)
        assert popen().__enter__().terminate.call_count == 1
        assert popen().__enter__().kill.call_count == 1


def test_proc_check_call_okay():
    start = datetime.utcnow()
    assert proc.check_call(['sleep', '0'], timeout=10) == 0


def test_proc_check_call_bad():
    start = datetime.utcnow()
    with pytest.raises(proc.CalledProcessError):
        proc.check_call(['sleep', 'foo'])


def test_proc_check_output_timeout():
    start = datetime.utcnow()
    with pytest.raises(proc.TimeoutExpired):
        proc.check_output(['sleep', '10'], timeout=0.1)
    assert datetime.utcnow() - start < timedelta(seconds=10)


def test_proc_check_output_stopped(stop_event, stop_after):
    start = datetime.utcnow()
    stop_after(0.1)
    with pytest.raises(proc.ProcessTerminated):
        proc.check_output(['sleep', '10'], event=stop_event)
    assert datetime.utcnow() - start < timedelta(seconds=10)


def test_proc_check_output_echo():
    assert proc.check_output(['echo', 'foo']) == b'foo\n'


def test_proc_check_output_bad():
    start = datetime.utcnow()
    with pytest.raises(proc.CalledProcessError):
        proc.check_output(['sleep', 'foo'])


def test_proc_check_output_kill():
    args = ['sleep', '10']
    with mock.patch('subprocess.Popen') as popen:
        def communicate(input=None, timeout=None):
            raise proc.TimeoutExpired(args, 1)
        popen().__enter__().communicate.side_effect = communicate
        with pytest.raises(proc.TimeoutExpired):
            proc.check_output(args, timeout=0.1)
        assert popen().__enter__().terminate.call_count == 1
        assert popen().__enter__().kill.call_count == 1
