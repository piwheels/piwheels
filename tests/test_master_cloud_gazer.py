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
from piwheels.master.cloud_gazer import CloudGazer


@pytest.fixture()
def pypi_proxy(request, sock_push_pull):
    push, pull = sock_push_pull
    def recv(serial):
        try:
            return pull.recv_pyobj(zmq.NOBLOCK)
        except zmq.ZMQError as e:
            if e.errno != zmq.EAGAIN:
                raise
            return []
    proxy_patcher = mock.patch('xmlrpc.client.ServerProxy')
    proxy_mock = proxy_patcher.start()
    proxy_mock().changelog_since_serial.side_effect = recv
    def fin():
        proxy_patcher.stop()
    request.addfinalizer(fin)
    return push


@pytest.fixture(scope='function')
def task_cloud_gazer(request, db_queue, master_config):
    task = CloudGazer(master_config)
    task.start()
    def fin():
        task.quit()
        assert db_queue.recv_pyobj() == ['SETPYPI', task.serial]
        db_queue.send_pyobj(['OK', None])
        task.join(2)
        if task.is_alive():
            raise RuntimeError('failed to kill cloud_gazer task')
    request.addfinalizer(fin)
    return task


def test_cloud_gazer_idle(pypi_proxy, db_queue, task_cloud_gazer):
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {"foo"}])
    assert db_queue.recv_pyobj() == ['GETPYPI']
    db_queue.send_pyobj(['OK', 0])
    # Send several "blank" reads from PyPI to ensure we saturate the PUSH/PULL
    # queues; this leaves us waiting for CloudGazer to process some of these
    # messages which guarantees it reads the GETPYPI result queued up above
    pypi_proxy.send_pyobj([])
    pypi_proxy.send_pyobj([])
    pypi_proxy.send_pyobj([])
    assert task_cloud_gazer.serial == 0


def test_cloud_gazer_new_pkg(pypi_proxy, db_queue, task_cloud_gazer):
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {"foo"}])
    assert db_queue.recv_pyobj() == ['GETPYPI']
    db_queue.send_pyobj(['OK', 0])
    pypi_proxy.send_pyobj([
        ('foo', '0.2', 1531327388, 'create', 0),
        ('foo', '0.2', 1531327388, 'add source file foo-0.2.tar.gz', 1),
    ])
    assert db_queue.recv_pyobj() == ['NEWVER', 'foo', '0.2']
    db_queue.send_pyobj(['OK', True])
    assert db_queue.recv_pyobj() == ['SETPYPI', 1]
    db_queue.send_pyobj(['OK', None])


def test_cloud_gazer_existing_ver(pypi_proxy, db_queue, task_cloud_gazer):
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {}])
    assert db_queue.recv_pyobj() == ['GETPYPI']
    db_queue.send_pyobj(['OK', 0])
    pypi_proxy.send_pyobj([
        ('foo', '0.2', 1531327388, 'create', 0),
        ('foo', '0.2', 1531327388, 'add source file foo-0.2.tar.gz', 1),
    ])
    assert db_queue.recv_pyobj() == ['NEWPKG', 'foo']
    db_queue.send_pyobj(['OK', False])
    assert db_queue.recv_pyobj() == ['NEWVER', 'foo', '0.2']
    db_queue.send_pyobj(['OK', False])
    assert db_queue.recv_pyobj() == ['SETPYPI', 1]
    db_queue.send_pyobj(['OK', None])



def test_cloud_gazer_new_ver(pypi_proxy, db_queue, task_cloud_gazer):
    assert db_queue.recv_pyobj() == ['ALLPKGS']
    db_queue.send_pyobj(['OK', {"foo"}])
    assert db_queue.recv_pyobj() == ['GETPYPI']
    db_queue.send_pyobj(['OK', 2])
    pypi_proxy.send_pyobj([
        ('bar', '1.0', 1531327389, 'create', 2),
        ('bar', '1.0', 1531327389, 'add source file bar-1.0-py2.py3-none-any.whl', 3),
        ('bar', '1.0', 1531327391, 'add py2.py3 file bar-1.0-py2.py3-none-any.whl', 4),
        ('bar', '1.0', 1531327392, 'add cp34 file bar-0.1-cp34-cp34-manylinux1_x86_64.whl', 5),
        ('bar', '1.0', 1531327392, 'add cp35 file bar-0.1-cp35-cp35-manylinux1_x86_64.whl', 6),
    ])
    assert db_queue.recv_pyobj() == ['NEWPKG', 'bar']
    db_queue.send_pyobj(['OK', True])
    assert db_queue.recv_pyobj() == ['NEWVER', 'bar', '1.0']
    db_queue.send_pyobj(['OK', True])
    assert db_queue.recv_pyobj() == ['SETPYPI', 6]
    db_queue.send_pyobj(['OK', None])
