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

"""
This module defines the default configuration for all applications in the
piwheels suite. Configuration can be overridden via configuration files, the
command line or, in certain cases, environment variables.
"""

DSN = 'postgres:///piwheels'
USER = 'piwheels'
PYPI_ROOT = 'https://pypi.org/'
PYPI_XMLRPC = '{PYPI_ROOT}pypi'.format(PYPI_ROOT=PYPI_ROOT)
PYPI_SIMPLE = '{PYPI_ROOT}simple'.format(PYPI_ROOT=PYPI_ROOT)
PYPI_JSON = '{PYPI_ROOT}pypi'.format(PYPI_ROOT=PYPI_ROOT)
OUTPUT_PATH = '/var/www'
STATUS_QUEUE = 'ipc:///tmp/piw-status'
CONTROL_QUEUE = 'ipc:///tmp/piw-control'
BUILDS_QUEUE = 'inproc://builds'
STATS_QUEUE = 'inproc://stats'
DB_QUEUE = 'inproc://db'
FS_QUEUE = 'inproc://fs'
WEB_QUEUE = 'inproc://web'
SLAVE_QUEUE = 'tcp://*:5555'
FILE_QUEUE = 'tcp://*:5556'
IMPORT_QUEUE = 'ipc:///tmp/piw-import'
LOG_QUEUE = 'ipc:///tmp/piw-logger'

# NOTE: The following queues are *not* configurable and should always be an
# inproc queue
INT_STATUS_QUEUE = 'inproc://status'
ORACLE_QUEUE = 'inproc://oracle'
SCRIBE_QUEUE = 'inproc://scribe'
SKIP_QUEUE = 'inproc://skip'
