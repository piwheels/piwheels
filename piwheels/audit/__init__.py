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
from queue import Queue, Empty
from html.parser import HTMLParser

from .. import __version__, terminal, const


def main(args=None):
    """
    This is the main function for the :program:`piw-audit` script. It relies
    on nothing from the master application as this is intended to be used
    offline or on backups of the master.
    """
    sys.excepthook = terminal.error_handler
    terminal.error_handler[OSError] = (
        terminal.error_handler.exc_message, 1)
    logging.getLogger().name = 'audit'
    parser = terminal.configure_parser("""\
The piw-audit script is intended to verify that the indexes generated for the
"simple" index are valid, i.e. that the directories and files pointed to all
exist and optionally that the hashes recorded in the sub-indexes match the
files on disk. Note that the script is intended to be run offline; i.e. the
master should preferably be shut down during operation of this script. If the
master is active, deletions may cause false negatives.
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
    parser.add_argument(
        '-b', '--broken', metavar='FILE', type=argparse.FileType('w'),
        help="If specified, the path of a file to which all filenames of "
        "corrupted wheels will be written; warning: this is an extremely "
        "slow operation on a full index which is avoided if this option is "
        "not specified")
    config = parser.parse_args(args)
    terminal.configure_logging(config.log_level, config.log_file)

    logging.info("PiWheels Audit version %s", __version__)
    config.output_path = Path(os.path.expanduser(config.output_path))
    check_simple_index(config)


def check_simple_index(config):
    logging.info('checking simple index')
    path = config.output_path / 'simple'
    index = path / 'index.html'
    try:
        for href, text in parse_links(index):
            check_package_index(config, href)
    except OSError as exc:
        report_missing(config, 'simple index', index)


def check_package_index(config, package):
    logging.info('checking %s', package)
    path = config.output_path / 'simple' / package
    index = path / 'index.html'
    try:
        all_files = set(path.iterdir())
    except OSError:
        report_missing(config, 'package dir', path)
    else:
        try:
            all_files.remove(index)
        except KeyError:
            report_missing(config, 'package index', index)
        else:
            for href, text in parse_links(index):
                filename, filehash = href.rsplit('#', 1)
                try:
                    all_files.remove(path / filename)
                except KeyError:
                    report_missing(config, 'wheel', path / filename)
                else:
                    if config.broken:
                        check_wheel_hash(config, package, filename, filehash)
        for filename in all_files:
            report_extra(config, 'file', path / filename)


def check_wheel_hash(config, package, filename, filehash):
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


# TODO Test JSON data
# TODO Test project dirs
# TODO Test wheel metadata?


def report(file, prefix, label, path):
    logging.error('%s %s %s', prefix, label, path)
    if file:
        file.write(str(path))
        file.write('\n')

def report_missing(config, label, path):
    report(config.missing, 'missing', label, path)

def report_extra(config, label, path):
    report(config.extraneous, 'extraneous', label, path)

def report_broken(config, label, path):
    report(config.broken, 'corrupted', label, path)


class IndexParser(HTMLParser):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        self.href = None
        self.data = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for name, value in attrs:
                if name == 'href':
                    self.href = value
                    break

    def handle_data(self, data):
        if self.href is not None:
            if self.data is None:
                self.data = data
            else:
                self.data += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None and self.data is not None:
            self.queue.put((self.href, self.data))
            self.href = None
            self.data = None


def parse_links(path):
    with path.open('r') as f:
        q = Queue()
        parser = IndexParser(q)
        while True:
            buf = f.read(4096)
            if not buf:
                break
            parser.feed(buf)
            while True:
                try:
                    yield q.get(block=False)
                except Empty:
                    break
