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
Contains the functions that implement the :program:`piw-archive` script, and
the file-movement helpers shared with :class:`~piwheels.master.the_archivist.TheArchivist`.

.. autofunction:: main

.. autofunction:: do_archive

.. autofunction:: ensure_package_dir

.. autofunction:: copy_file

.. autofunction:: delete_file
"""

import os
import sys
import logging
from pathlib import Path
import shutil

from .. import __version__, terminal, const


def main(args=None):
    """
    This is the main function for the :program:`piw-archive` script.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[RuntimeError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'import'
    parser = terminal.configure_parser("""\
The piw-archive script is used to manually move files from the master to the
archive or vice-versa. This script must be run on the same node as the
piw-master script. It only copies the files themselves; it does not update
the database's record of each file's location. It's intended as a manual
override alongside the automatic daily archiving performed by piw-master
(see TheArchivist); for a one-off move, follow it with a manual database
update.
""")
    parser.add_argument(
        'files_file', help="The text file containing the list of wheels to "
        "archive, one 'package/filename' per line")
    parser.add_argument(
        '-o', '--output-path', metavar='PATH', default=const.OUTPUT_PATH,
        help="The path under which the website is stored")
    parser.add_argument(
        '--archive-dir', required=True,
        help="The location of the archive server's mount point")
    parser.add_argument(
        '--unarchive', action='store_true',
        help="Move files from the archive back to the master")
    config = parser.parse_args(args)

    config.output_path = Path(os.path.expanduser(config.output_path))
    config.archive_dir = Path(os.path.expanduser(config.archive_dir))
    config.files_file = Path(os.path.expanduser(config.files_file))

    logging.info("PiWheels Archiver version %s", __version__)
    do_archive(config)


def do_archive(config):
    """
    Move files from the master to the archive or vice-versa

    :param config:
        The configuration obtained from parsing the command line.
    """
    master_simple = config.output_path / 'simple'
    archive_simple = config.archive_dir / 'simple'
    if config.unarchive:
        src_simple, dst_simple = archive_simple, master_simple
    else:
        src_simple, dst_simple = master_simple, archive_simple
    for f in config.files_file.read_text().splitlines():
        package, filename = f.split('/', 1)
        if copy_file(src_simple, dst_simple, package, filename):
            logging.info("%s %s", "Unarchiving" if config.unarchive else
                         "Archiving", f)
        else:
            logging.warning(
                "File %s not found in %s", f,
                "archive" if config.unarchive else "on master")


def ensure_package_dir(simple_path, package):
    """
    Ensure the ``simple/<package>`` directory exists under *simple_path*,
    creating it (and any parents) if necessary.
    """
    (simple_path / package).mkdir(parents=True, exist_ok=True)


def copy_file(src_simple, dst_simple, package, filename):
    """
    Copy *package*/*filename*, along with its accompanying ``.metadata``
    file (if present), from *src_simple* to *dst_simple*, creating the
    destination package directory as required. Symlinks (e.g. the armv6l
    hard-links to armv7l wheels) are preserved as symlinks rather than being
    dereferenced.

    Returns ``True`` if the file was copied, or ``False`` if it was missing
    from *src_simple*.
    """
    src_file = src_simple / package / filename
    dst_file = dst_simple / package / filename
    try:
        ensure_package_dir(dst_simple, package)
        shutil.copy2(src_file, dst_file, follow_symlinks=False)
    except FileNotFoundError:
        return False
    src_metadata = src_file.with_name(src_file.name + '.metadata')
    dst_metadata = dst_file.with_name(dst_file.name + '.metadata')
    try:
        shutil.copy2(src_metadata, dst_metadata, follow_symlinks=False)
    except FileNotFoundError:
        pass
    return True


def delete_file(simple_path, package, filename):
    """
    Delete *package*/*filename*, along with its accompanying ``.metadata``
    file (if present), from under *simple_path*.
    """
    file_path = simple_path / package / filename
    file_path.unlink(missing_ok=True)
    file_path.with_name(file_path.name + '.metadata').unlink(missing_ok=True)