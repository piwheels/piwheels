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

import ipaddress as ip
import datetime as dt
from collections import namedtuple

from voluptuous import Schema, ExactSequence, Extra, Maybe, Any


class _NoData:
    # Singleton representing the lack of a schema for a message
    __slots__ = ()

    def __new__(cls):
        try:
            return NoData
        except NameError:
            return super().__new__(cls)

    def __repr__(self):
        return 'NoData'


NoData = _NoData()


class Protocol(namedtuple('Protocol', ('recv', 'send'))):
    # Protocols are generally specified from the point of view of the master;
    # i.e. the recv dictionary contains the messages (and schemas) the master
    # task expects to recv, and the send dictionary contains the messages it
    # expects to send. The special __reversed__ method is overridden to allow
    # client tasks to specify their protocol as reversed(some_protocol)
    __slots__ = ()

    def __new__(cls, recv=None, send=None):
        if recv is None:
            recv = {}
        else:
            recv = {
                msg: NoData if prototypes is NoData else Schema(prototypes)
                for msg, prototypes in recv.items()
            }
        if send is None:
            send = {}
        else:
            send = {
                msg: NoData if prototypes is NoData else Schema(prototypes)
                for msg, prototypes in send.items()
            }
        return super().__new__(cls, recv, send)

    def __reversed__(self):
        return Protocol(self.send, self.recv)


_statistics = {      # statistics
    'packages_built':        int,
    'builds_count':          int,
    'builds_last_hour':      int,
    'builds_success':        int,
    'builds_time':           dt.timedelta,
    'builds_size':           int,
    'builds_pending':        int,
    'files_count':           int,
    'disk_free':             int,
    'disk_size':             int,
    'downloads_last_month':  int,
}


_dependency = ExactSequence([str, str])  # tool, package


_file_state = ExactSequence([
    str,            # filename
    int,            # filesize
    str,            # filehash
    str,            # package_tag
    str,            # package_version_tag
    str,            # py_version_tag
    str,            # abi_tag
    str,            # platform_tag
    {_dependency},  # dependencies
    # NOTE: the optional transferred field is never included. It is effectively
    # internal to whatever is tracking the file state
])


_build_state = ExactSequence([
    int,            # slave id
    str,            # package
    str,            # version
    str,            # abi_tag
    bool,           # status
    dt.timedelta,   # duration
    str,            # output
    [_file_state],  # files
    # NOTE: the optional build-id field is never included. This is another
    # internal field that must be maintained by the caller
])


_download_state = ExactSequence([
    str,          # filename
    str,          # host
    dt.datetime,  # timestamp
    str,          # arch
    str,          # distro_name
    str,          # distro_version
    str,          # os_name
    str,          # os_version
    str,          # py_name
    str,          # py_version
])


task_control = Protocol(recv={
    'PAUSE':  NoData,
    'RESUME': NoData,
    'QUIT':   NoData,
})


master_control = Protocol(recv={
    'HELLO':  NoData,  # new monitor
    'PAUSE':  NoData,  # pause all operations on the master
    'RESUME': NoData,  # resume all operations on the master
    'KILL':   int,     # kill the specified slave
    'QUIT':   NoData,  # terminate the master
})


big_brother = Protocol(recv={
    'STATFS': ExactSequence([int, int, int]),  # frsize, bavail, blocks
    'STATBQ': {str: int},  # abi: queue-size
    'HOME':   NoData,
})


the_scribe = Protocol(recv={
    'PKGBOTH': str,  # package name
    'PKGPROJ': str,  # package name
    'HOME':    _statistics,  # statistics
    'SEARCH':  {str: int},  # package: download-count
})


the_architect = Protocol(send={
    'QUEUE': {str: [ExactSequence([str, str])]},  # abi: [(package, version), ...]
})


# This protocol isn't specified here as it's just multipart packets of bytes
# and the code doesn't use send_msg / recv_msg. See FileJuggler.handle_file and
# the associated documentation for more information on this protocol
file_juggler_files = Protocol()


file_juggler_fs = Protocol(recv={
    'EXPECT': ExactSequence([int, _file_state]),  # slave ID, file state
    'VERIFY': ExactSequence([int, str]),                 # slave ID, package
    'REMOVE': ExactSequence([str, str]),                 # package, filename
}, send={
    'OK':     Extra,  # some result object XXX refine this?
    'ERROR':  str,    # error message
})


mr_chase = Protocol(recv={
    'IMPORT': ExactSequence([
        str,            # package
        str,            # version
        Maybe(str),     # abi_tag
        bool,           # status
        dt.timedelta,   # duration
        str,            # output
        [_file_state],  # filename: filestate
    ]),
    'REMOVE': ExactSequence([str, str, str]),  # package, version, skip-reason
    'REBUILD': Any(
        ExactSequence(['HOME']),
        ExactSequence(['SEARCH']),
        ExactSequence(['PKGPROJ', Maybe(str)]),
        ExactSequence(['PKGBOTH', Maybe(str)]),
    ),
    'SENT':   NoData,
}, send={
    'SEND':   str,  # filename
    'ERROR':  str,  # message
    'DONE':   NoData,
})


lumberjack = Protocol(recv={
    'LOG': _download_state,
})


slave_driver = Protocol(recv={
    'HELLO': ExactSequence([dt.timedelta, str, str, str, str]), # timeout, py-version, abi, platform, label
    'BYE':   NoData,
    'IDLE':  NoData,
    'BUILT': ExactSequence([bool, dt.timedelta, str, [_file_state]]),
    'SENT':  NoData,
}, send={
    'ACK':   ExactSequence([int, str]),  # slave ID, PyPI URL
    'DIE':   NoData,
    'SLEEP': NoData,
    'BUILD': ExactSequence([str, str]),  # package, version
    'SEND':  str,                        # filename
    'DONE':  NoData,
})


the_oracle = Protocol(recv={
    'ALLPKGS':     NoData,
    'ALLVERS':     NoData,
    'NEWPKG':      ExactSequence([str, str]),  # package, skip reason
    'NEWVER':      ExactSequence([str, str, dt.datetime, str]),  # package, version, released, skip reason
    'SKIPPKG':     ExactSequence([str, str]),  # package, skip reason
    'SKIPVER':     ExactSequence([str, str, str]),  # package, version, skip reason
    'LOGDOWNLOAD': _download_state,
    'LOGBUILD':    _build_state,
    'DELBUILD':    ExactSequence([str, str]),  # package, version
    'PKGFILES':    str,                        # package
    'PROJVERS':    str,                        # package
    'PROJFILES':   str,                        # package
    'VERFILES':    ExactSequence([str, str]),  # package, version
    'GETSKIP':     ExactSequence([str, str]),  # package, version
    'PKGEXISTS':   str,                        # package
    'VEREXISTS':   ExactSequence([str, str]),  # package, version
    'GETABIS':     NoData,
    'GETPYPI':     NoData,
    'SETPYPI':     int,                        # PyPI serial number
    'GETSTATS':    NoData,
    'GETDL':       NoData,
    'FILEDEPS':    str,                        # filename
}, send={
    'OK':          Extra,  # result XXX refine this? Would mean separate returns...
    'ERROR':       str,    # message
})


monitor_stats = Protocol(send={
    'STATS': _statistics,
    'SLAVE': ExactSequence([int, dt.datetime, str, Extra]), # slave id, timestamp, message, data
})
