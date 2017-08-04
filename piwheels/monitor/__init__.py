from datetime import datetime, timedelta

import zmq
import urwid

from ..terminal import TerminalApplication
from .. import __version__


class PiWheelsMonitor(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, log_params=False)

    def main(self, args):
        ctx = zmq.Context()
        self.status_queue = ctx.socket(zmq.SUB)
        self.status_queue.hwm = 10
        self.status_queue.connect('ipc:///tmp/piw-status')
        self.status_queue.setsockopt_string(zmq.SUBSCRIBE, '')
        self.ctrl_queue = ctx.socket(zmq.PUSH)
        self.ctrl_queue.connect('ipc:///tmp/piw-control')
        try:
            self.loop = urwid.MainLoop(
                *self.build_ui(),
                unhandled_input=self.unhandled_input)
            self.loop.event_loop.alarm(1, self.tick)
            # XXX This is crap; ought to make a proper 0MQ event loop instead
            self.loop.event_loop.alarm(0.01, self.poll)
            self.loop.run()
        finally:
            self.ctrl_queue.close()
            self.status_queue.close()
            ctx.term()

    def build_button(self, caption, callback):
        btn = urwid.Button(('normal', [('hotkey', caption[0]), caption[1:]]))
        urwid.connect_signal(btn, 'click', callback)
        return urwid.AttrMap(btn, None, focus_map={'normal': 'invert'})

    def build_ui(self):
        palette = [
            ('idle',    'light red',       'default'),
            ('silent',  'yellow',          'default'),
            ('busy',    'light green',     'default'),
            ('time',    'light gray',      'default'),
            ('status',  'light gray',      'default'),
            ('hotkey',  'yellow',          'default'),
            ('normal',  'light gray',      'default'),
            ('invert',  'black',           'light gray'),
            ('todo',    'white',           'default'),
            ('done',    'black',           'light gray'),
            ('smooth',  'default',         'light gray'),
        ]
        self.slave_list = SlaveListWalker()
        list_box = urwid.ListBox(self.slave_list)
        actions_box = urwid.Columns([
            self.build_button('Pause', self.pause_clicked),
            self.build_button('Resume', self.resume_clicked),
            self.build_button('Kill slave', self.kill_clicked),
            self.build_button('Terminate master', self.term_clicked),
            self.build_button('Quit', self.quit_clicked),
        ])
        self.builds_bar = urwid.ProgressBar('todo', 'done', satt='smooth')
        self.disk_bar = urwid.ProgressBar('todo', 'done', satt='smooth')
        self.build_rate_label = urwid.Text('0 pkgs/hour')
        self.build_time_label = urwid.Text('0:00:00')
        self.build_size_label = urwid.Text('0 bytes')
        status_box = urwid.Columns([
            (12, urwid.Pile([
                urwid.Text(('normal', 'Disk')),
                urwid.Text(('normal', 'Builds')),
                urwid.Text(('normal', 'Build Rate')),
                urwid.Text(('normal', 'Build Time')),
                urwid.Text(('normal', 'Build Size')),
            ])),
            urwid.Pile([
                self.disk_bar,
                self.builds_bar,
                self.build_rate_label,
                self.build_time_label,
                self.build_size_label,
            ]),
        ])
        pile = urwid.Pile([
            ('pack', status_box),
            ('pack', urwid.Divider('\N{HORIZONTAL BAR}')),
            list_box,
            ('pack', urwid.Divider('\N{HORIZONTAL BAR}')),
            ('pack', actions_box),
        ])
        return pile, palette

    def poll(self):
        if self.status_queue.poll(0):
            slave_id, timestamp, msg, *args = self.status_queue.recv_json()
            if msg == 'STATUS':
                self.update_status(args[0])
            else:
                self.slave_list.message(slave_id, timestamp, msg, *args)
        self.loop.event_loop.alarm(0.01, self.poll)

    def tick(self):
        self.slave_list.tick()
        self.loop.event_loop.alarm(1, self.tick)

    def unhandled_input(self, key):
        if isinstance(key, str):
            try:
                {
                    'p': lambda: self.pause_clicked(None),
                    'r': lambda: self.resume_clicked(None),
                    'k': lambda: self.kill_clicked(None),
                    't': lambda: self.term_clicked(None),
                    'q': lambda: self.quit_clicked(None),
                }[key.lower()]()
            except KeyError:
                return False
            else:
                return True
        else:
            # Ignore unhandled mouse events
            return False

    def update_status(self, status_info):
        self.builds_bar.set_completion(
            (status_info['versions_built'] * 100 / status_info['versions_count'])
            if status_info['versions_count'] else 0)
        self.disk_bar.set_completion(
            status_info['disk_free'] * 100 / status_info['disk_size'])
        self.build_rate_label.set_text(
            '{} pkgs/hour'.format(status_info['builds_last_hour']))
        self.build_size_label.set_text(
            '{} Mbytes'.format(status_info['builds_size'] // 1048576))
        time = timedelta(seconds=status_info['builds_time'])
        time -= timedelta(microseconds=time.microseconds)
        self.build_time_label.set_text('{}'.format(time))

    def quit_clicked(self, button):
        raise urwid.ExitMainLoop()

    def pause_clicked(self, button):
        self.ctrl_queue.send_json(('PAUSE',))

    def resume_clicked(self, button):
        self.ctrl_queue.send_json(('RESUME',))

    def kill_clicked(self, button):
        # XXX Maybe add an "are you sure?"
        try:
            widget = self.slave_list[self.slave_list.focus]
        except IndexError:
            pass
        else:
            for slave_id, slave in self.slave_list.slaves.items():
                if slave.widget == widget:
                    self.ctrl_queue.send_json(('KILL', slave_id))
                    break

    def term_clicked(self, button):
        # XXX Maybe add an "are you sure?"
        self.ctrl_queue.send_json(('QUIT',))
        raise urwid.ExitMainLoop()


class SlaveListWalker(urwid.ListWalker):
    def __init__(self):
        super().__init__()
        self.focus = 0
        self.slaves = {}
        self.widgets = []

    def __getitem__(self, position):
        return self.widgets[position]

    def next_position(self, position):
        if position >= len(self.widgets) - 1:
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

    def message(self, slave_id, timestamp, msg, *args):
        try:
            state = self.slaves[slave_id]
        except KeyError:
            state = SlaveState()
            self.slaves[slave_id] = state
            self.widgets.append(state.widget)
            self._modified()
        state.update(timestamp, msg, *args)
        self._modified()

    def tick(self):
        # Increment "time in state" labels
        for state in self.slaves.values():
            state.tick()
        # Remove terminated slaves
        now = datetime.utcnow()
        for slave_id, state in list(self.slaves.items()):
            if state.last_msg == 'BYE' and (now - state.last_seen > timedelta(seconds=5)):
                self.widgets.remove(state.widget)
                del self.slaves[slave_id]
        self.focus = min(self.focus, len(self.widgets) - 1)
        self._modified()


class SlaveState:
    def __init__(self):
        self.widget = urwid.AttrMap(
            urwid.SelectableIcon(''), None,
            focus_map={'status': 'invert'}
        )
        self.last_msg = ''
        self.last_seen = None
        self.status = ''

    def update(self, timestamp, msg, *args):
        self.last_msg = msg
        self.last_seen = datetime.fromtimestamp(timestamp)
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
             'silent' if datetime.utcnow() - self.last_seen > timedelta(minutes=10) else
             'busy', '*'),
            ('time', ' '),
            # Annoyingly, timedelta doesn't have a __format__ method...
            ('time', str(datetime.utcnow().replace(microsecond=0) - self.last_seen.replace(microsecond=0))),
            ('time', ' '),
            ('status', self.status),
        ])


main = PiWheelsMonitor()
