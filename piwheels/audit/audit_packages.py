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
import hashlib
import logging
import argparse
from pathlib import Path
from html.parser import HTMLParser

from requests import Session

from .report import report_extra, report_missing, report_broken
from .. import __version__, terminal, const
from ..master.db import Database
from ..format import canonicalize_name


def main(args=None):
    """
    This is the main function for the :program:`piw-audit-packages` script. It
    relies
    on nothing from the master application as this is intended to be used
    offline or on backups of the master.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[OSError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'audit'
    parser = terminal.configure_parser("""\
The piw-audit-packages script is intended to verify that the index generated
for a package's "simple" index are valid, i.e. that the files in the index file
all exist and optionally that the hashes recorded in the sub-indexes match the
files on disk; and that files on external servers can be verified. Note that the
script is intended to be run offline; i.e. the master should preferably be shut
down during operation of this script. If the master is active, deletions may
cause false negatives. Can be used to audit a number of given packages, or all
packages in the index.
""")
    parser.add_argument(
        'packages',
        metavar='PACKAGES',
        nargs='*',
        help="The names of the packages to audit")
    parser.add_argument(
        '-d', '--dsn', default=const.DSN,
        help="The database to use; this database must be configured with "
        "piw-initdb and the user should *not* be a PostgreSQL superuser "
        "(default: %(default)s)")
    parser.add_argument(
        '-o', '--output-path', metavar='PATH', default=const.OUTPUT_PATH,
        help="The path under which the website has been written; must be "
        "readable by the current user")
    parser.add_argument(
        '--hashes', action='store_true',
        help="If specified, the script will verify that wheel hashes are as "
        "expected")
    parser.add_argument(
        '--extra-file', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the path of a file to which all extraneous "
        "filenames (files which shouldn't exist, but do) will be written")
    parser.add_argument(
        '--missing-file', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the path of a file to which all missing "
        "filenames (files which should exist, but don't) will be written")
    parser.add_argument(
        '--broken-file', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the path of a file to which all filenames of "
        "corrupted wheels will be written; warning: this is an extremely "
        "slow operation on a full index which is avoided if this option is "
        "not specified")
    parser.add_argument(
        '--ensure-project-symlinks', action='store_true',
        help="If specified, the script will ensure that all alias symlinks "
        "exist")
    parser.add_argument(
        '--verify-external-links', action='store_true',
        help="If specified, the script will verify that all external links "
        "exist")
    parser.add_argument(
        '--delete-extras', action='store_true',
        help="If specified, the script will delete all extraneous files")
    parser.add_argument(
        '--master-url', metavar='URL',
        help="If specified, the audit will assume to be running on a secondary " 
        "archive server, rather than the master, and will attempt to verify "
        "the state of the files on the archive server, as specified in the "
        "simple index for the package on the master.")
    config = parser.parse_args(args)
    terminal.configure_logging(config.log_level, config.log_file)

    if config.verify_external_links and config.master_url:
        logging.error(
            'Cannot run with both --verify-external-links and --master-url')
        sys.exit(1)
    
    if config.master_url:
        config.master_url = config.master_url.removesuffix('/')

    logging.info("PiWheels Audit package version %s", __version__)
    config.output_path = Path(os.path.expanduser(config.output_path))
    config.packages = [canonicalize_name(pkg) for pkg in config.packages]
    db = Database(config.dsn)
    if not config.packages:
        config.packages = db.get_all_packages()

    logging.info(f"Checking {len(config.packages):,} packages")

    for package in config.packages:
        check_package_index(config, package, db)

def check_package_index(config, package, db):
    logging.info('checking %s', package)

    if config.verify_external_links or config.master_url:
        session = Session()
    else:
        session = None

    simple_pkg_dir = config.output_path / 'simple' / package
    if config.master_url:
        html = fetch_master_package_index(config, session, package)
    else:
        index_file = simple_pkg_dir / 'index.html'
        html = index_file.read_text(encoding='utf-8')

    try:
        all_files = set(simple_pkg_dir.iterdir())
    except OSError:
        report_missing(config, 'package dir', simple_pkg_dir)
        return

    for f in all_files:
        if f.is_symlink() and not f.exists():
            report_broken(config, 'symlink', f)

    if not config.master_url:
        try:
            all_files.remove(index_file)
        except KeyError:
            report_missing(config, 'package index', index_file)
            return

    for href in parse_links(html):
        file_url, filehash = href.rsplit('#', 1)
        if file_url.startswith('http'):
            if config.verify_external_links:
                verify_external_link(file_url, session, config)
            continue
        filename = file_url.split('/')[-1]
        try:
            all_files.remove(simple_pkg_dir / filename)
        except KeyError:
            report_missing(config, 'wheel', simple_pkg_dir / filename)
        else:
            if config.hashes:
                check_wheel_hash(config, package, filename, filehash)

    # all_files now contains only files that are not in the index

    for filename in all_files:
        if config.delete_extras:
            logging.warning(f"Deleting extraneous file {filename}")
            filename.unlink()
        else:
            report_extra(config, 'file', simple_pkg_dir / filename)

    aliases = db.get_package_aliases(package)
    check_project_symlinks(config, package, aliases)

def fetch_master_package_index(config, session, package):
    """
    Fetch the package index from the master server and return its HTML content
    """
    simple_pkg_index = f"{config.master_url}/simple/{package}/index.html"
    response = session.get(simple_pkg_index)
    if response.status_code != 200 or not response.text:
        report_missing(config, 'master package index', simple_pkg_index)
        sys.exit(1)
    return response.text

def verify_external_link(file_url, session, config):
    """
    Verify that an external link exists by making a HEAD request to the URL
    """
    response = session.head(file_url)
    if response.status_code != 200:
        report_missing(config, 'external link', file_url)
        
def check_project_symlinks(config, package, aliases):
    """
    Check that all project symlinks exist and are valid. If configured so,
    ensure they point to the correct target.
    """
    project_dir = config.output_path / 'project'
    canon_project_dir = project_dir / package
    for alias in aliases:
        alias_path = project_dir / alias
        target = alias_path.resolve()
        if target != canon_project_dir:
            if config.ensure_project_symlinks:
                logging.info(
                    'creating symlink %s to %s', alias, canon_project_dir)
                alias_path.unlink()
                alias_path.symlink_to(canon_project_dir)
            else:
                report_broken(config, 'project symlink', alias_path)

def check_wheel_hash(config, package, filename, filehash):
    """
    Verify the hash of a wheel file against the expected hash
    """
    logging.info('checking %s/%s', package, filename)
    algorithm, filehash = filehash.rsplit('=', 1)
    wheel = config.output_path / 'simple' / package / filename
    try:
        state = {
            'md5': hashlib.md5,
            'sha256': hashlib.sha256,
        }[algorithm]()
    except KeyError:
        report_broken(config, 'wheel hash algo', wheel)
    else:
        with wheel.open('rb') as f:
            while True:
                buf = f.read(4096)
                if not buf:
                    break
                state.update(buf)
        if state.hexdigest().lower() != filehash.lower():
            report_broken(config, 'wheel', wheel)


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr, value in attrs:
                if attr == "href":
                    self.links.add(value)


def parse_links(html):
    parser = LinkExtractor()
    parser.feed(html)
    return parser.links