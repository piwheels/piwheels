from datetime import datetime, timedelta

import zmq
import urwid

from ..terminal import TerminalApplication
from .. import __version__


class PiWheelsMonitor(TerminalApplication):
    def __init__(self):
        super().__init__(__version__)

    def main(self, args):
        ctx = zmq.Context()
        self.status_queue = ctx.socket(zmq.SUB)
        self.status_queue.hwm = 10
        self.status_queue.connect('ipc:///tmp/piw-status')
        self.status_queue.setsockopt_string(zmq.SUBSCRIBE, '')
        try:
            self.loop = urwid.MainLoop(
                *self.build_ui(),
                unhandled_input=self.unhandled_input)
            self.loop.event_loop.alarm(1, self.tick)
            self.loop.event_loop.alarm(0.01, self.poll)
            self.loop.run()
        finally:
            self.status_queue.close()
            ctx.term()

    def build_ui(self):
        palette = [
            ('idle',    'light red',    'default'),
            ('silent',  'yellow',       'default'),
            ('busy',    'light green',  'default'),
            ('hotkey',  'yellow',       'default'),
            ('normal',  'light gray',   'default'),
            ('invert',  'black',        'light gray'),
        ]
        self.slave_list = SlaveListWalker()
        list_box = urwid.ListBox(self.slave_list)
        self.quit_btn = urwid.Button(('normal', [('hotkey', 'Q'), 'uit']))
        self.kill_btn = urwid.Button(('normal', [('hotkey', 'K'), 'ill']))
        self.pause_btn = urwid.Button(('normal', [('hotkey', 'P'), 'ause']))
        self.resume_btn = urwid.Button(('normal', [('hotkey', 'R'), 'esume']))
        actions = urwid.Columns([
            urwid.AttrMap(widget, None, focus_map={'normal': 'invert'})
            for widget in [
                self.pause_btn,
                self.resume_btn,
                self.kill_btn,
                self.quit_btn,
            ]
        ])
        urwid.connect_signal(self.quit_btn, 'click', self.quit_clicked)
        urwid.connect_signal(self.pause_btn, 'click', self.pause_clicked)
        urwid.connect_signal(self.resume_btn, 'click', self.resume_clicked)
        urwid.connect_signal(self.kill_btn, 'click', self.kill_clicked)
        filler = urwid.Filler(actions, valign='bottom')
        pile = urwid.Pile([list_box, filler])
        return pile, palette

    def poll(self):
        if self.status_queue.poll(0):
            self.slave_list.message(*self.status_queue.recv_json())
        # XXX Remove terminated slaves
        self.loop.event_loop.alarm(0.01, self.poll)

    def tick(self):
        self.slave_list.tick()
        self.loop.event_loop.alarm(1, self.tick)

    def unhandled_input(self, key):
        try:
            {
                'q': lambda: self.quit_clicked(self.quit_btn),
                'k': lambda: self.kill_clicked(self.kill_btn),
                'p': lambda: self.pause_clicked(self.pause_btn),
                'r': lambda: self.resume_clicked(self.resume_btn),
            }[key.lower()]()
        except KeyError:
            return False
        else:
            return True

    def quit_clicked(self, button):
        raise urwid.ExitMainLoop()

    def pause_clicked(self, button):
        control_queue.send_json(('PAUSE',))

    def resume_clicked(self, button):
        control_queue.send_json(('RESUME',))

    def kill_clicked(self, button):
        control_queue.send_json(('KILL', self.slave_list.focus))


class SlaveListWalker(urwid.ListWalker):
    def __init__(self):
        super().__init__()
        self.focus = 0
        self.slaves = {}
        self.widgets = []

    def __len__(self):
        return len(self.widgets)

    def __getitem__(self, position):
        return self.widgets[position]

    def next_position(self, position):
        if position >= len(self) - 1:
            raise IndexError
        return position + 1

    def prev_position(self, position):
        if position <= 0:
            raise IndexError
        return position - 1

    def set_focus(self, position):
        self.widgets[position] # raises IndexError if position is invalid
        self.focus = position
        self._modified()

    def message(self, slave_id, last_seen, msg, *args):
        try:
            state = self.slaves[slave_id]
        except KeyError:
            state = SlaveState()
            self.slaves[slave_id] = state
            self.widgets.append(state.widget)
            self._modified()
        state.update(last_seen, msg, *args)
        self._modified()

    def tick(self):
        for state in self.slaves.values():
            state.tick()
        self._modified()


class SlaveState:
    def __init__(self):
        self.widget = urwid.AttrMap(
            urwid.Text(''), None,
            focus_map={'normal': 'invert'}
        )
        self.last_msg = ''
        self.last_seen = None
        self.status = ''

    def update(self, last_seen, msg, *args):
        self.last_msg = msg
        self.last_seen = datetime.utcfromtimestamp(last_seen)
        if msg == 'HELLO':
            self.status = 'Initializing'
        elif msg == 'SLEEP':
            self.status = 'Waiting for jobs'
        elif msg == 'BYE':
            self.status = 'Terminating'
        elif msg == 'BUILD':
            self.status = 'Building {} {}'.format(args[0], args[1])
        elif msg == 'SEND':
            self.status = 'Transferring file'
        elif msg == 'DONE':
            self.status = 'Cleaning up after build'
        self.tick()

    def tick(self):
        self.widget.original_widget.set_text([
            ('idle' if self.last_msg == 'SLEEP' else
             'silent' if datetime.now() - self.last_seen > timedelta(minutes=10) else
             'busy', '*'),
            ('normal', ' '),
            ('normal', str(datetime.now() - self.last_seen)),
            ('normal', ' '),
            ('normal', self.status),
        ])


main = PiWheelsMonitor()
