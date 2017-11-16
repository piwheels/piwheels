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

from .tasks import PauseableTask
from .pypi import PyPIEvents
from .the_oracle import DbClient


class CloudGazer(PauseableTask):
    """
    This task scrapes PyPI for the list of available packages, and the versions
    of those packages. This information is written into the backend database
    for :class:`~.the_architect.TheArchitect` to use.
    """
    name = 'master.cloud_gazer'

    def __init__(self, config):
        super().__init__(config)
        self.db = DbClient(config)
        self.pypi = PyPIEvents(config.pypi_xmlrpc)
        self.packages = None

    def loop(self):
        for package, version in self.pypi:
            if package not in self.packages:
                if self.db.add_new_package(package):
                    self.packages.add(package)
                    self.logger.info('added package %s', package)
            if self.db.add_new_package_version(package, version):
                self.logger.info('added package %s version %s',
                                 package, version)
            self.poll(0)
        self.db.set_pypi_serial(self.pypi.serial)

    def run(self):
        self.logger.info('retrieving current state')
        self.packages = self.db.get_all_packages()
        self.pypi.serial = self.db.get_pypi_serial()
        self.logger.info('querying upstream')
        try:
            super().run()
        finally:
            self.db.set_pypi_serial(self.pypi.serial)
