import os
import heapq
import select
from time import time
from itertools import count
from collections import namedtuple

import zmq

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



AlarmTask = namedtuple('AlarmTask', ('due', 'tie_break', 'callback'))

class ZMQEventLoop():
    _alarm_break = count()

    def __init__(self):
        self._did_something = True
        self._alarms = []
        self._poller = zmq.Poller()
        self._queue_callbacks = {}
        self._idle_handle = 0
        self._idle_callbacks = {}

    def alarm(self, seconds, callback):
        tm = time() + seconds
        handle = AlarmTask(tm, next(self._alarm_break), callback)
        heapq.heappush(self._alarms, handle)
        return handle

    def remove_alarm(self, handle):
        try:
            self._alarms.remove(handle)
            heapq.heapify(self._alarms)
            return True
        except ValueError:
            return False

    def watch_queue(self, q, callback, flags=zmq.POLLIN):
        if q in self._queue_callbacks:
            raise ValueError('already watching %r' % q)
        self._poller.register(q, flags)
        self._queue_callbacks[q] = callback
        return q

    def watch_file(self, fd, callback, flags=zmq.POLLIN):
        if isinstance(fd, int):
            fd = os.fdopen(fd)
        self._poller.register(fd, flags)
        self._queue_callbacks[fd.fileno()] = callback
        return fd

    def remove_watch_queue(self, handle):
        try:
            try:
                self._poller.unregister(handle)
            finally:
                self._queue_callbacks.pop(handle, None)
            return True
        except KeyError:
            return False

    def remove_watch_file(self, handle):
        try:
            try:
                self._poller.unregister(handle)
            finally:
                self._queue_callbacks.pop(handle.fileno(), None)
            return True
        except KeyError:
            return False

    def enter_idle(self, callback):
        self._idle_handle += 1
        self._idle_callbacks[self._idle_handle] = callback
        return self._idle_handle

    def remove_enter_idle(self, handle):
        try:
            del self._idle_callbacks[handle]
            return True
        except KeyError:
            return False

    def _entering_idle(self):
        for callback in list(self._idle_callbacks.values()):
            callback()

    def run(self):
        try:
            while True:
                self._loop()
        except ExitMainLoop:
            pass

    def _loop(self):
        if self._alarms or self._did_something:
            if self._alarms:
                tm = self._alarms[0][0]
                timeout = max(0, tm - time())
            if self._did_something and (not self._alarms or
                                        (self._alarms and timeout > 0)):
                tm = 'idle'
                timeout = 0
            ready = self._poller.poll(timeout * 1000) # ms
        else:
            tm = None
            ready = self._poller.poll()

        if not ready:
            if tm == 'idle':
                self._entering_idle()
                self._did_something = False
            elif tm is not None:
                task = heapq.heappop(self._alarms)
                task.callback()
                self._did_something = True

        for q, event in ready:
            self._queue_callbacks[q]()
            self._did_something = True


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
