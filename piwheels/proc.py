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

import subprocess
from datetime import datetime, timedelta


PIPE = subprocess.PIPE
DEVNULL = subprocess.DEVNULL
SubprocessError = subprocess.SubprocessError
CalledProcessError = subprocess.CalledProcessError
TimeoutExpired = subprocess.TimeoutExpired


class ProcessTerminated(SubprocessError):
    def __init__(self, cmd, event, output=None, stderr=None):
        self.cmd = cmd
        self.event = event
        self.output = output
        self.stderr = stderr

    def __str__(self):
        return ("Command '%s' was terminated early by event" % self.cmd)

    @property
    def stdout(self):
        return self.output

    @stdout.setter
    def stdout(self, value):
        self.output = value


def _test_term(args, start, timeout, event):
    # NOTE: This convenience function expects to be called from an exception
    # handler for the TimeoutExpired exception which it will re-raise if a
    # timeout has really occurred
    if timeout is not None and datetime.utcnow() - start > timeout:
        raise
    elif event is not None and event.wait(0):
        raise ProcessTerminated(args, event)


def call(args, *posargs, event=None, timeout=None, **kwargs):
    """
    A version of :func:`subprocess.call` which watches *event* for early
    termination.
    """
    if timeout is not None:
        timeout = timedelta(seconds=timeout)
    with subprocess.Popen(args, *posargs, **kwargs) as p:
        start = datetime.utcnow()
        while True:
            try:
                try:
                    return p.wait(1)
                except subprocess.TimeoutExpired:
                    _test_term(args, start, timeout, event)
            except:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                raise


def check_call(args, *posargs, **kwargs):
    """
    A version of :func:`subprocess.check_call` which watches *event* for early
    termination.
    """
    rc = call(args, *posargs, **kwargs)
    if rc != 0:
        raise subprocess.CalledProcessError(rc, args)
    return 0


def check_output(args, *posargs, event=None, timeout=None, **kwargs):
    """
    A version of :func:`subprocess.check_output` which watches *event* for
    early termination.
    """
    if timeout is not None:
        timeout = timedelta(seconds=timeout)
    with subprocess.Popen(args, *posargs, stdout=subprocess.PIPE, **kwargs) as p:

        def stop_nicely():
            p.terminate()
            try:
                out, err = p.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                out, err = p.communicate()
            return out, err

        start = datetime.utcnow()
        while True:
            try:
                try:
                    out, err = p.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    _test_term(args, start, timeout, event)
                else:
                    break
            except subprocess.TimeoutExpired:
                out, err = stop_nicely()
                raise subprocess.TimeoutExpired(
                    p.args, timeout.total_seconds(), output=out)
            except:
                stop_nicely()
                raise
        if p.returncode != 0:
            raise subprocess.CalledProcessError(
                p.returncode, p.args, output=out)
    return out
