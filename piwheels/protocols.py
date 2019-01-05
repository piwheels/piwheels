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

import datetime as dt
from collections import namedtuple

from voluptuous import Schema, ExactSequence, Extra, Maybe


# Sentinel representing missing data
Missing = object()


class Protocol(namedtuple('Protocol', ('recv', 'send'))):
    # Protocols are generally specified from the point of view of the master;
    # i.e. the recv dictionary contains the messages (and schemas) the master
    # task expects to recv, and the send dictionary contains the messages it
    # expects to send. The special __reversed__ method is overridden to allow
    # client tasks to specify their protocol as reversed(some_protocol)
    __slots__ = ()

    def __new__(cls, recv=None, send=None):
        return super().__new__(cls, {} if recv is None else recv,
                               {} if send is None else send)

    def __reversed__(self):
        return Protocol(self.send, self.recv)


_statistics_schema = Schema({      # statistics
    'packages_count':        int,
    'packages_built':        int,
    'versions_count':        int,
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
})


task_control = Protocol(recv={
    'PAUSE':  None,
    'RESUME': None,
    'QUIT':   None,
})


master_control = Protocol(recv={
    'HELLO':  None,         # new monitor
    'PAUSE':  None,         # pause all operations on the master
    'RESUME': None,         # resume all operations on the master
    'KILL':   Schema(int),  # kill the specified slave
    'QUIT':   None,         # terminate the master
})


big_brother = Protocol(recv={
    'STATFS': Schema(ExactSequence([
        int,  # statvfs.f_frsize
        int,  # statvfs.f_bavail
        int,  # statvfs.f_blocks
    ])),
    'STATBQ': Schema({str: int}),  # abi: queue-size
})


the_scribe = Protocol(recv={
    'PKGBOTH': Schema(str),  # package name
    'PKGPROJ': Schema(str),  # package name
    'HOME':    _statistics_schema,  # statistics
    'SEARCH':  Schema({str: int}),  # package: download-count
})


the_architect = Protocol(send={
    'QUEUE': Schema(ExactSequence([
        str,  # abi
        str,  # package
        str,  # version
    ])),
})


# This protocol isn't specified here as it's just multipart packets of bytes
# and the code doesn't use send_msg / recv_msg. See FileJuggler.handle_file and
# the associated documentation for more information on this protocol
file_juggler_files = Protocol()


file_juggler_fs = Protocol(recv={
    'EXPECT': Schema(ExactSequence([
        int,    # slave id
        Extra,  # XXX file state
    ])),
    'VERIFY': Schema(ExactSequence([
        int,   # slave id
        str,   # package name
    ])),
    'REMOVE': Schema(ExactSequence([
        str,   # package name
        str,   # filename
    ])),
}, send={
    'OK':     Schema(Extra),  # some result object XXX refine this?
    'ERR':    Schema(Exception),  # some exception object
})


mr_chase = Protocol(recv={
    'IMPORT': Schema(ExactSequence([
        str,    # abi_tag
        str,    # package
        str,    # version
        bool,   # status
        float,  # duration
        str,    # output
        {str: Extra},  # filename: filestate XXX refine this?
    ])),
    'REMOVE': Schema(ExactSequence([
        str,    # package
        str,    # version
        str,    # skip reason
    ])),
    'SENT':   None,
}, send={
    'SEND':   str,  # filename
    'ERROR':  str,  # message
    'DONE':   None,
})


lumberjack = Protocol(recv={
    'LOG': Schema(ExactSequence([
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
    ])),
})


slave_driver = Protocol(recv={
    'HELLO': Schema(ExactSequence([
        float,   # timeout
        str,     # native_py_version
        str,     # native_abi
        str,     # native_platform
        str,     # label
    ])),
    'BYE':   None,
    'IDLE':  None,
    'BUILT': Schema(ExactSequence([
        # XXX ???
    ])),
    'SENT':  None,
}, send={
    'ACK':   Schema(ExactSequence([
        int,     # slave id
        str,     # PyPI URL
    ])),
    'DIE':   None,
    'SLEEP': None,
    'BUILD': Schema(ExactSequence([
        str,     # package
        str,     # version
    ])),
    'SEND':  str,  # filename
    'DONE':  None,
})


the_oracle = Protocol(recv={
    'ALLPKGS': None,
    'ALLVERS': None,
    'NEWPKG': Schema(ExactSequence([
        str,  # package
        Maybe(str),  # skip reason  XXX remove Maybe
    ])),
    'NEWVER': Schema(ExactSequence([
        str,          # package
        str,          # version
        dt.datetime,  # released
        Maybe(str),   # skip reason  XXX remove Maybe
    ])),
    'SKIPPKG': Schema(ExactSequence([
        str,  # package
        str,  # skip reason
    ])),
    'SKIPVER': Schema(ExactSequence([
        str,  # package
        str,  # version
        Maybe(str),  # skip reason  XXX remove Maybe
    ])),
    'LOGDOWNLOAD': Schema(Extra),  # XXX refine this
    'LOGBUILD': Schema(Extra),     # XXX refine this
    'DELBUILD': Schema(ExactSequence([
        str,  # package
        str,  # version
    ])),
    'PKGFILES': Schema(ExactSequence([
        str,  # package
    ])),
    'PROJVERS': Schema(ExactSequence([
        str,  # package
    ])),
    'PROJFILES': Schema(ExactSequence([
        str,  # package
    ])),
    'VERFILES': Schema(ExactSequence([
        str,  # package
        str,  # version
    ])),
    'GETSKIP': Schema(ExactSequence([
        str,  # package
        str,  # version
    ])),
    'PKGEXISTS': Schema(ExactSequence([
        str,  # package
        str,  # version
    ])),
    'GETABIS': None,
    'GETPYPI': None,
    'SETPYPI': Schema(ExactSequence([
        int,  # PyPI serial number
    ])),
    'GETSTATS': None,
    'GETDL': None,
    'FILEDEPS': Schema(ExactSequence([
        str,  # filename
    ])),
}, send={
    'ERROR': str,    # message
    'OK':    Schema(Extra),  # result XXX refine this? Would mean separate returns...
})


monitor_stats = Protocol(send={
    'STATS': _statistics_schema,
    'SLAVE': Schema(ExactSequence([
        int,          # slave id
        dt.datetime,  # timestamp
        Extra,        # message  XXX extend schema here?
    ])),
})
