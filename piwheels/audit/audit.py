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
Contains the functions that implement the :program:`piw-audit` script.

.. autofunction:: main
"""

import os
import sys
import logging
import argparse
from pathlib import Path

from . import report_missing, report_extra
from .. import __version__, terminal, const
from ..master.db import Database

def main(args=None):
    """
    This is the main function for the :program:`piw-audit` script. It relies
    only on a database connection to retrieve the list of packages.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[OSError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'audit'
    parser = terminal.configure_parser("""\
The piw-audit script is intended to verify that all packages in the database
have a simple index, project index and project JSON index, and that no
extraneous directories exist in the simple and project directories. Any missing
or extraneous directories will be reported to the console and optionally to
files specified on the command line.
""")
    parser.add_argument(
        '-o', '--output-path', metavar='PATH', default=const.OUTPUT_PATH,
        help="The path under which the website has been written; must be "
        "readable by the current user")
    parser.add_argument(
        '-e', '--extraneous', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the path of a file to which all extraneous "
        "filenames (files which shouldn't exist, but do) will be written")
    parser.add_argument(
        '-m', '--missing', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the path of a file to which all missing "
        "filenames (files which should exist, but don't) will be written")
    config = parser.parse_args(args)
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Audit version %s", __version__)
    config.output_path = Path(os.path.expanduser(config.output_path))
    db = Database("postgresql:///piwheels") # TODO: use config
    packages = db.get_all_packages()
    audit_packages(config, packages)
    audit_extras(config, packages)
    remove_broken_symlinks(config)

def audit_packages(config, packages):
    """
    Audit the given packages to ensure that the simple and project
    indexes exist
    """
    missing_simple = set()
    missing_project = set()
    simple = config.output_path / "simple"
    project = config.output_path / "project"

    for pkg in packages:
        simple_dir = simple / pkg
        simple_index = simple_dir / "index.html"
        if not simple_index.exists():
            missing_simple.add(pkg)
            report_missing(config, 'simple', simple_dir)
        
        proj_dir = project / pkg
        proj_index = proj_dir / "index.html"
        proj_json_dir = proj_dir / "json"
        proj_json_index = proj_json_dir / "index.json"
        if not (proj_index.exists() and proj_json_index.exists()):
            missing_project.add(pkg)
            report_missing(config, 'project', proj_dir)

def audit_extras(config, packages):
    """
    Audit the simple and project directories for extraneous directories
    """
    simple_dirs = get_dirs(config.output_path / "simple")
    extra_simple_dirs = simple_dirs - packages
    report_extra_dirs(config, "simple directory", extra_simple_dirs)
    project_dirs = get_dirs(config.output_path / "project")
    extra_project_dirs = project_dirs - packages
    report_extra_dirs(config, "project directory", extra_project_dirs)

def remove_broken_symlinks(config):
    project_dir = config.output_path / 'project'
    symlinks = get_symlinks(project_dir)
    for link in symlinks:
        if not link.exists():
            logging.warning('removing broken symlink %s', link)
            link.unlink()

def get_dirs(parent):
    """
    Return all directories within the given parent directory
    """
    return {d for d in parent.iterdir() if d.is_dir()}

def get_symlinks(parent):
    """
    Return all symlinks within the given parent directory
    """
    return {s for s in parent.iterdir() if s.is_symlink()}

def report_extra_dirs(config, label, extra_dirs):
    for path in sorted(extra_dirs):
        report_extra(config.extraneous, label, path)