#!/usr/bin/env python3
# vim: set et sw=4 sts=4 fileencoding=utf-8:
#
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

import sys
import os
from pathlib import Path
from datetime import datetime
from setuptools.config import read_configuration

on_rtd = os.environ.get('READTHEDOCS', '').lower() == 'true'
config = read_configuration(str(Path(__file__).parent / '..' / 'setup.cfg'))
metadata = config['metadata']

# -- Project information -----------------------------------------------------

project = metadata['name'].title()
author = metadata['author']
copyright = '2017-{now:%Y} {author}'.format(now=datetime.now(), author=author)
release = metadata['version']
version = release

# -- General configuration ------------------------------------------------

needs_sphinx = '1.4.0'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
]

if on_rtd:
    tags.add('rtd')

imgmath_image_format = 'svg'

templates_path = ['_templates']
master_doc = 'index'

exclude_patterns = ['_build']
pygments_style = 'sphinx'

# -- Autodoc options ---------------------------------------------------------

autodoc_member_order = 'groupwise'
autodoc_mock_imports = [
    'zmq',
    'dateutil',
    'configargparse',
    'sqlalchemy',
    'piwheels.terminal',
    'voluptuous',
    'cbor2',
    'chameleon',
    'psycopg2',
    'apt',
]

# -- Intersphinx options -----------------------------------------------------

intersphinx_mapping = {
    'python': ('https://docs.python.org/3.9', None),
    'lars': ('https://lars.readthedocs.io/en/latest', None),
    'simplejson': ('https://simplejson.readthedocs.io/en/latest', None),
}

# -- Options for HTML output ----------------------------------------------

html_theme = 'sphinx_rtd_theme'
pygments_style = 'default'
html_title = '{project} {version} Documentation'.format(
    project=project, version=version)
html_static_path = ['_static']
html_extra_path = ['_html']
manpages_url = 'https://manpages.ubuntu.com/manpages/focal/en/man{section}/{page}.{section}.html'

# Hack to make wide tables work properly in RTD
# See https://github.com/snide/sphinx_rtd_theme/issues/117 for details
def setup(app):
    app.add_css_file('style_override.css')

# -- Options for LaTeX output ------------------------------------------------

latex_engine = 'xelatex'

latex_elements = {
    'papersize': 'a4paper',
    'pointsize': '10pt',
    'preamble': r'\def\thempfootnote{\arabic{mpfootnote}}', # workaround sphinx issue #2530
}

latex_documents = [
    (
        'index',            # source start file
        project + '.tex',   # target filename
        html_title,         # title
        author,             # author
        'manual',           # documentclass
        True,               # documents ref'd from toctree only
    ),
]

latex_show_pagerefs = True
latex_show_urls = 'footnote'

# -- Options for epub output -------------------------------------------------

epub_basename = project
epub_author = author
epub_identifier = 'https://{metadata[name]}.readthedocs.io/'.format(metadata=metadata)
epub_show_urls = 'no'

# -- Options for manual page output ------------------------------------------

man_pages = [
    ('master',   'piw-master',   'PiWheels Master',              [metadata['author']], 1),
    ('slaves',   'piw-slave',    'PiWheels Build Slave',         [metadata['author']], 1),
    ('monitor',  'piw-monitor',  'PiWheels Monitor',             [metadata['author']], 1),
    ('sense',    'piw-sense',    'PiWheels Sense HAT Monitor',   [metadata['author']], 1),
    ('initdb',   'piw-initdb',   'PiWheels Initialize Database', [metadata['author']], 1),
    ('importer', 'piw-import',   'PiWheels Package Importer',    [metadata['author']], 1),
    ('add',      'piw-add',      'PiWheels Package Addition',    [metadata['author']], 1),
    ('remove',   'piw-remove',   'PiWheels Package Remover',     [metadata['author']], 1),
    ('rebuild',  'piw-rebuild',  'PiWheels Page Rebuilder',      [metadata['author']], 1),
    ('logger',   'piw-logger',   'PiWheels Logger',              [metadata['author']], 1),
]

man_show_urls = True

# -- Options for linkcheck builder -------------------------------------------

linkcheck_retries = 3
linkcheck_workers = 20
linkcheck_anchors = True
