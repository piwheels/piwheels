import subprocess


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


def call(args, *posargs, event, timeout=None, **kwargs):
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
                    if datetime.utcnow() - start > timeout:
                        raise
                    elif event.wait(0):
                        raise ProcessTerminated(args, event)
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


def check_output(args, *posargs, event, timeout=None, **kwargs):
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
                out, err = p.communicate(timeout=10)
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
                    if datetime.utcnow() - start > timeout:
                        raise
                    elif event.wait(0):
                        raise ProcessTerminated(args, event)
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
