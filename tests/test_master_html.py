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


from piwheels.master.html import html, literal, tag, TagFactory


def test_literals():
    assert html(literal('foo')) == 'foo'
    assert html(literal('<foo>')) == '<foo>'
    assert html(literal('foo & bar')) == 'foo & bar'


def test_content():
    assert html(content('foo')) == 'foo'
    assert html(content('<foo>')) == '&lt;foo&gt;'
    assert html(content('foo & bar')) == 'foo &amp; bar'


def test_str():
    assert html('foo') == 'foo'
    assert html('<foo>') == '&lt;foo&gt;'
    assert html('foo & bar') == 'foo &amp; bar'


def test_html_tag_basics():
    tag = TagFactory(xml=False)
    assert html(tag.a()) == '<a></a>'
    assert html(tag.br()) == '<br>'
    assert html(tag.foo()) == '<foo></foo>'


def test_html_tag_attrs():
    tag = TagFactory(xml=False)
    assert html(tag.foo(bar='baz')) == '<foo bar="baz"></foo>'
    assert html(tag.foo(bar=101)) == '<foo bar="101"></foo>'
    assert html(tag.foo(bar=True)) == '<foo bar="bar"></foo>'
    assert html(tag.foo(bar=False)) == '<foo></foo>'
    assert html(tag.foo(bar=None)) == '<foo></foo>'
    assert html(tag.br(foo='bar')) == '<br foo="bar">'
    assert html(tag.foo(bar=b'baz')) == '<foo bar="baz"></foo>'
    assert html(tag.br(foo=b'm\xc2\xb5')) == '<br foo="mµ">'
    assert html(tag.foo(bar=range(5))) == '<foo bar="01234"></foo>'


def test_xml_tag_attrs():
    tag = TagFactory(xml=True)
    assert html(tag.foo(bar='baz')) == '<foo bar="baz"></foo>'
    assert html(tag.foo(bar=101)) == '<foo bar="101"></foo>'
    assert html(tag.foo(bar=True)) == '<foo bar="bar"></foo>'
    assert html(tag.foo(bar=False)) == '<foo></foo>'
    assert html(tag.foo(bar=None)) == '<foo></foo>'
    assert html(tag.br(foo='bar')) == '<br foo="bar"/>'
    assert html(tag.foo(bar=b'baz')) == '<foo bar="baz"></foo>'
    assert html(tag.br(foo=b'm\xc2\xb5')) == '<br foo="mµ"/>'
    assert html(tag.foo(bar=range(5))) == '<foo bar="01234"></foo>'


def test_tag_half():
    tag = TagFactory(xml=False)
    assert html(tag.foo(bar='baz', _open=False)) == '</foo>'
    assert html(tag.foo(bar='baz', _close=False)) == '<foo bar="baz">'
    assert html(tag.br(foo='bar', _close=False)) == '<br foo="bar">'
    assert html(tag.br(foo='bar', _open=False)) == ''
    assert html(tag.br(foo='bar', _open=False, _close=True)) == '</br>'
    tag = TagFactory(xml=True)
    assert html(tag.foo(bar='baz', _open=False)) == '</foo>'
    # XXX Surely this is wrong?
    assert html(tag.foo(bar='baz', _close=False)) == '<foo bar="baz"/>'
    assert html(tag.br(foo='bar', _close=False)) == '<br foo="bar"/>'
    assert html(tag.br(foo='bar', _open=False)) == ''
    assert html(tag.br(foo='bar', _open=False, _close=True)) == '</br>'


def test_tag_contents():
    tag = TagFactory(xml=False)
    assert html(tag.foo(tag.bar('baz'))) == '<foo><bar>baz</bar></foo>'
    assert html(tag.foo('bar', 'baz')) == '<foo>barbaz</foo>'
    assert html(tag.foo(1, ' ', 2, ' ', 3)) == '<foo>1 2 3</foo>'
