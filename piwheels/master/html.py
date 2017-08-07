class literal(str):
    "A str sub-class that assumes its content is HTML"
    def __html__(self):
        return self


class content(str):
    "A str sub-class which escapes content for inclusion in HTML"
    def __html__(self):
        return literal(self.\
                replace('&', '&amp;').\
                replace('"', '&quot;').\
                replace('<', '&lt;').\
                replace('>', '&gt;'))


def html(s):
    "Return s in a form suitable for inclusion in an HTML document"
    if hasattr(s, '__html__'):
        return s.__html__()
    else:
        return content(s).__html__()


# The set of HTML elements which should never have a closing tag

EMPTY_ELEMENTS = (
    # From HTML4 standard
    'area',
    'base',
    'basefont',
    'br',
    'col',
    'frame',
    'hr',
    'img',
    'input',
    'isindex',
    'link',
    'meta',
    'param',
    # Proprietary extensions
    'bgsound',
    'embed',
    'keygen',
    'spacer',
    'wbr',
    )

class TagFactory():
    """
    A factory class for generating XML/HTML elements (or tags).

    Instances of this class use __getattr__ magic to provide methods for
    generating any XML or HTML element. Calling a method with a particular name
    will return a string containing an XML/HTML element of that name. Any
    positional arguments will be used as content for the element, and any named
    arguments will be used as attributes for the element. If the element or
    attribute you wish to name is a reserved word in Python, you can simply
    append underscore ("_") to the name (all trailing underscore characters
    will be stripped implicitly).

    For example::

        >>> tag = TagFactory()
        >>> tag.a()
        '<a></a>'
        >>> tag.a('foo')
        '<a>foo</a>'
        >>> tag.a('foo', bar='baz')
        '<a bar="baz">foo</a>'

    You can explicitly suppress the generation of either the opening or
    closing tags by setting the ``_open`` and ``_close`` parameters to False
    respectively::

        >>> tag = TagFactory()
        >>> tag.a(_close=False)
        '<a>'
        >>> tag.form(_open=False)
        '</form>'

    Note that content of a tag is only output when ``_open`` is True (or
    omitted). The factory will automatically set ``_close`` to True for HTML
    tags which are declared "empty" in the standard, e.g. ``<br>`` and
    ``<hr>``::

        >>> tag = TagFactory()
        >>> tag.br()
        '<br>'

    If the factory is instantiated with the xml parameter set to True, this
    automatic behaviour will be disabled so that all empty tags are explicitly
    closed::

        >>> tag = TagFactory(xml=True)
        >>> tag.hr()
        '<hr/>'
    """
    def __init__(self, xml=False):
        self._xml = xml

    def _format(self, content):
        if isinstance(content, str):
            return html(content)
        elif isinstance(content, bytes):
            return html(content.decode('utf-8'))
        else:
            try:
                return literal(''.join(self._format(item) for item in content))
            except TypeError:
                return html(content)

    def _generate(self, _tag, *args, **kwargs):
        _tag = _tag.rstrip('_')
        result = ''
        open_tag = kwargs.get('_open', True)
        close_tag = kwargs.get('_close', _tag.lower() not in EMPTY_ELEMENTS)
        empty_tag = not args
        if open_tag:
            if empty_tag and not close_tag and self._xml:
                template = '<%s%s/>'
            else:
                template = '<%s%s>'
            result += template % (
                _tag,
                ''.join(
                    ' %s="%s"' % (
                        k, self._format(k if v is True else v)
                        )
                    for (_k, v) in kwargs.items()
                    for k in (_k.rstrip('_').replace('_', '-'),)
                    if v is not None
                    and v is not False)
                )
            for arg in args:
                result += self._format(arg)
        if close_tag:
            result += '</%s>' % _tag
        return literal(result)

    def __getattr__(self, attr):
        def generator(*args, **kwargs):
            return self._generate(attr, *args, **kwargs)
        setattr(self, attr, generator)
        return generator

tag = TagFactory()
