from urwid import (
    connect_signal,
    AttrMap,
    Button,
    Text,
    SelectableIcon,
    WidgetWrap,
    Pile,
    Columns,
    Filler,
    Divider,
    Frame,
    LineBox,
    ListBox,
    Overlay,
    ProgressBar,
    ListWalker,
    MainLoop,
    ExitMainLoop,
)


palette = [
    ('idle',        'light red',       'default'),
    ('silent',      'yellow',          'default'),
    ('busy',        'light green',     'default'),
    ('time',        'light gray',      'default'),
    ('status',      'light gray',      'default'),
    ('hotkey',      'light cyan',      'dark blue'),
    ('normal',      'light gray',      'default'),
    ('todo',        'white',           'dark blue'),
    ('done',        'black',           'light gray'),
    ('todo_smooth', 'dark blue',       'light gray'),
    ('header',      'light gray',      'dark blue'),
    ('footer',      'light gray',      'dark blue'),
    ('dialog',      'light gray',      'dark blue'),
    ('button',      'light gray',      'dark blue'),
    ('inv_dialog',  'dark blue',       'light gray'),
    ('inv_normal',  'black',           'light gray'),
    ('inv_hotkey',  'dark cyan',       'light gray'),
    ('inv_button',  'black',           'light gray'),
    ('inv_status',  'black',           'light gray'),
]


class SimpleButton(Button):
    button_left = Text("[")
    button_right = Text("]")


class FixedButton(SimpleButton):
    def sizing(self):
        return frozenset(['fixed'])

    def pack(self, size, focus=False):
        return (len(self.get_label()) + 4, 1)


class YesNoDialog(WidgetWrap):
    signals = ['yes', 'no']

    def __init__(self, title, message):
        yes_button = FixedButton('Yes')
        no_button = FixedButton('No')
        connect_signal(yes_button, 'click', lambda btn: self._emit('yes'))
        connect_signal(no_button, 'click', lambda btn: self._emit('no'))
        super().__init__(
            LineBox(
                Pile([
                    ('pack', Text(message)),
                    Filler(
                        Columns([
                            ('pack', AttrMap(yes_button, 'button', 'inv_button')),
                            ('pack', AttrMap(no_button, 'button', 'inv_button')),
                        ], dividechars=2),
                        valign='bottom'
                    )
                ]),
                title
            )
        )

    def keypress(self, size, key):
        key = super().keypress(size, key)
        if isinstance(key, str):
            if key.lower() == 'y':
                self._emit('yes')
            elif key.lower() == 'n':
                self._emit('no')
        return key

    def _get_title(self):
        return self._w.title_widget.text.strip()
    def _set_title(self, value):
        self._w.set_title(value)
    title = property(_get_title, _set_title)
