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
Defines the :class:`CloudGazer` task; see class for more details.

.. autoclass:: CloudGazer
    :members:
"""

from datetime import timedelta

from .. import protocols, transport, tasks
from .pypi import PyPIEvents, get_project_description
from .the_oracle import DbClient


class CloudGazer(tasks.PauseableTask):
    """
    This task scrapes PyPI for the list of available packages, and the versions
    of those packages. This information is written into the backend database
    for :class:`~.the_architect.TheArchitect` to use.
    """
    name = 'master.cloud_gazer'

    def __init__(self, config):
        super().__init__(config)
        self.db = DbClient(config, self.logger)
        self.pypi = PyPIEvents(config.pypi_xmlrpc)
        self.web_queue = self.socket(
            transport.PUSH, protocol=reversed(protocols.the_scribe))
        self.web_queue.hwm = 10
        self.web_queue.connect(config.web_queue)
        self.serial = -1
        self.packages = None
        if config.dev_mode:
            self.skip_default = 'development mode'
        else:
            self.skip_default = ''
        self.every(timedelta(seconds=10), self.read_pypi)

    def once(self):
        self.logger.info('retrieving current state')
        self.packages = self.db.get_all_packages()
        self.pypi.serial = self.serial = self.db.get_pypi_serial()
        self.logger.info('querying upstream')

    def read_pypi(self):
        for package, version, timestamp, action in self.pypi:
            if action == 'remove':
                if version is None:
                    self.logger.info(
                        'disabled package %s (deleted)', package)
                    self.db.skip_package(package, 'deleted')
                    self.packages.discard(package)
                else:
                    self.logger.info(
                        'disabled package %s version %s (deleted)',
                        package, version)
                    self.db.skip_package_version(package, version, 'deleted')
            else:
                if package not in self.packages:
                    self.packages.add(package)
                    if self.db.add_new_package(package, skip=self.skip_default):
                        self.logger.info('added package %s', package)
                        self.web_queue.send_msg('PKGBOTH', package)
                if version is not None:
                    skip = '' if action == 'source' else 'binary only'
                    if self.db.add_new_package_version(package, version,
                                                       timestamp, skip):
                        self.logger.info(
                            'added package %s version %s', package, version)
                        if action != 'source':
                            self.logger.info(
                                'disabled package %s version %s (binary only)',
                                package, version)
                        description = get_project_description(package)
                        if description:
                            self.db.update_project_description(package, description)
                        self.web_queue.send_msg('PKGPROJ', package)
                    elif action == 'source' and self.db.get_version_skip(
                            package, version) == 'binary only':
                        self.db.skip_package_version(package, version, '')
                        self.logger.info(
                            'enabled package %s version %s', package, version)
                        self.web_queue.send_msg('PKGPROJ', package)
        if self.serial < self.pypi.serial:
            self.serial = self.pypi.serial
            self.db.set_pypi_serial(self.serial)
