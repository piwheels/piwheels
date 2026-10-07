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
Defines the :class:`TheArchivist` task; see class for more details.

.. autoclass:: TheArchivist
    :members:
"""

from datetime import timedelta
from pathlib import Path
from itertools import groupby
from operator import itemgetter

from .. import const, protocols, tasks, transport
from ..archive import copy_file, delete_file
from .db import Database


class TheArchivist(tasks.PauseableTask):
    """
    This task periodically moves wheel files between the master and the
    archive server: files whose builds have received few downloads recently
    are moved to the archive to free up space on the master, while archived
    files that have become popular again are moved back. After moving a
    package's files it updates the database's record of their location and
    requests a rebuild of that package's index page.

    This mirrors the (formerly manual) archive process, but stops short of
    the audit/symlink-repair steps of that process, which remain a manual
    task; see the operations documentation.
    """
    name = 'master.the_archivist'

    def __init__(self, config):
        super().__init__(config)
        self.db = Database(config.dsn)
        self.master_simple = Path(config.output_path) / 'simple'
        self.archive_simple = Path(config.archive_dir) / 'simple'
        self.archive_threshold = config.archive_threshold
        self.unarchive_threshold = config.unarchive_threshold
        self.web_queue = self.socket(
            transport.REQ, protocol=reversed(protocols.the_scribe))
        self.web_queue.connect(config.web_queue)
        self.every(
            timedelta(hours=config.archive_interval), self.do_archive_run)

    def close(self):
        self.db.close()
        super().close()

    def do_archive_run(self):
        """
        Runs one archiving pass (master to archive) followed by one
        unarchiving pass (archive to master).
        """
        self.logger.info('starting archive run')
        self._move_files(
            self.db.get_archive_candidates(self.archive_threshold),
            self.master_simple, self.archive_simple,
            const.ARCHIVE_LOCATION, 'archiving')
        self._move_files(
            self.db.get_unarchive_candidates(self.unarchive_threshold),
            self.archive_simple, self.master_simple,
            const.MASTER_LOCATION, 'unarchiving')
        self.logger.info('finished archive run')

    def _move_files(self, candidates, src_simple, dst_simple, new_location,
                     verb):
        # candidates is a list of (package, filename) tuples, ordered by
        # package (see get_archive_candidates/get_unarchive_candidates)
        for package, group in groupby(candidates, key=itemgetter(0)):
            filenames = [filename for _, filename in group]
            moved = [
                filename for filename in filenames
                if copy_file(src_simple, dst_simple, package, filename)
            ]
            if len(moved) < len(filenames):
                self.logger.warning(
                    '%d of %d files for %s not found while %s',
                    len(filenames) - len(moved), len(filenames), package,
                    verb)
            if not moved:
                continue
            self.logger.info('%s %d files for %s', verb, len(moved), package)
            # The DB is only updated, and the source files only deleted,
            # once the copies are confirmed on disk: a crash between here
            # and the deletion below leaves a harmless duplicate, never a
            # dangling database reference
            self.db.set_files_location(moved, new_location)
            self.web_queue.send_msg('PROJECT', package)
            self.web_queue.recv_msg()
            for filename in moved:
                delete_file(src_simple, package, filename)
