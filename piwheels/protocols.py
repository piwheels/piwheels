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

from voluptuous import Schema, ExactSequence, Extra


task_control = {
    'PAUSE':  None,
    'RESUME': None,
    'QUIT':   None,
}

master_control = {
    'HELLO':  None,         # new monitor
    'PAUSE':  None,         # pause all operations on the master
    'RESUME': None,         # resume all operations on the master
    'KILL':   Schema(int),  # kill the specified slave
    'QUIT':   None,         # terminate the master
}

big_brother = {
    'STATFS': Schema(ExactSequence([
        int,  # statvfs.f_frsize
        int,  # statvfs.f_bavail
        int,  # statvfs.f_blocks
    ])),
    'STATBQ': Schema({str: int}),  # abi: queue-size
}

the_scribe = {
    'PKGBOTH': Schema(str),  # package name
    'PKGPROJ': Schema(str),  # package name
    'HOME':    Schema({str: int}),  # statistics XXX include actual keys
    'SEARCH':  Schema({str: int}),  # package: download-count
}

the_architect = {
    'QUEUE': Schema(ExactSequence([
        str,  # abi
        str,  # package
        str,  # version
    ])),
}

file_juggler_files = {
    # This protocol isn't specified here as it's just multipart packets of
    # bytes and the code doesn't use send_msg / recv_msg. See
    # FileJuggler.handle_file and the associated documentation for more
    # information on this protocol
}

file_juggler_fs = {
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
    'OK':     Schema(Extra),  # some result object XXX refine this?
    'ERR':    Schema(Exception),  # some exception object
}

mr_chase = {
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
    'ERROR':  str,  # message
    'SEND':   str,  # filename
    'DONE':   None,
}

lumberjack = {
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
}

slave_driver = {
    'HELLO': Schema(ExactSequence([
        float,   # timeout
        str,     # native_py_version
        str,     # native_abi
        str,     # native_platform
        str,     # label
    ])),
    'ACK':   Schema(ExactSequence([
        int,     # slave id
        str,     # PyPI URL
    ])),
    'BYE':   None,
    'IDLE':  None,
    'SLEEP': None,
    'BUILD': Schema(ExactSequence([
        str,     # package
        str,     # version
    ])),
    'BUILT': Schema(ExactSequence([
    ])),
    'SEND':  str,  # filename
    'SENT':  None,
    'DONE':  None,
}

the_oracle = {
    'ALLPKGS': None,
    'ALLVERS': None,
    'NEWPKG': Schema(ExactSequence([
        str,  # package
        str,  # skip reason,
    ])),
    'NEWVER': Schema(ExactSequence([
        str,          # package
        str,          # version
        dt.datetime,  # released
        str,          # skip reason
    ])),
    'SKIPPKG': Schema(ExactSequence([
        str,  # package
        str,  # skip reason
    ])),
    'SKIPVER': Schema(ExactSequence([
        str,  # package
        str,  # version
        str,  # skip reason
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
    ])),,
    'ERROR': str,    # message
    'OK':    Extra,  # result
}

monitor_stats = {
    'STATS': Schema({str: int}),   # statistics XXX include actual keys
    'SLAVE': Schema(ExactSequence([
        int,          # slave id
        dt.datetime,  # timestamp
        Extra,        # message  XXX extend schema here?
    ])),
}
