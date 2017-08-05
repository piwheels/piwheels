from datetime import datetime, timedelta

import zmq

from . import widgets
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
            self.loop = widgets.MainLoop(
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
        btn = widgets.SimpleButton(('button', [('hotkey', caption[0]), caption[1:]]))
        widgets.connect_signal(btn, 'click', callback)
        return widgets.AttrMap(widgets.AttrMap(btn, None, focus_map={
            'button': 'inv_button',
            'hotkey': 'inv_hotkey',
        }), 'button', 'inv_button')

    def build_ui(self):
        self.slave_to_kill = None
        self.popup_stack = []
        self.slave_list = SlaveListWalker()
        list_box = widgets.ListBox(self.slave_list)
        actions_box = widgets.AttrMap(
            widgets.Pile([
                widgets.Divider('\N{UPPER HALF BLOCK}'),
                widgets.Columns([
                    self.build_button('Pause', self.pause),
                    self.build_button('Resume', self.resume),
                    self.build_button('Kill slave', self.kill_slave),
                    self.build_button('Terminate master', self.terminate_master),
                    self.build_button('Quit', self.quit),
                ])
            ]),
            'footer'
        )
        self.builds_bar = widgets.ProgressBar('todo', 'done', satt='todo_smooth')
        self.disk_bar = widgets.ProgressBar('todo', 'done', satt='todo_smooth')
        self.build_rate_label = widgets.Text('0 pkgs/hour')
        self.build_time_label = widgets.Text('0:00:00')
        self.build_size_label = widgets.Text('0 bytes')
        status_box = widgets.AttrMap(
            widgets.Pile([
                widgets.Columns([
                    (12, widgets.Pile([
                        widgets.Text('Disk'),
                        widgets.Text('Builds'),
                        widgets.Text('Build Rate'),
                        widgets.Text('Build Time'),
                        widgets.Text('Build Size'),
                    ])),
                    widgets.Pile([
                        self.disk_bar,
                        self.builds_bar,
                        self.build_rate_label,
                        self.build_time_label,
                        self.build_size_label,
                    ]),
                ]),
                widgets.Divider('\N{LOWER HALF BLOCK}')
            ]),
            'header'
        )
        self.frame = widgets.Frame(
            list_box,
            header=status_box,
            footer=actions_box
        )
        return self.frame, widgets.palette

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

    def show_popup(self, dialog):
        overlay = widgets.Overlay(
            widgets.AttrMap(dialog, 'dialog'), self.frame.body,
            'center', ('relative', 40),
            'middle', ('relative', 30),
            min_width=20, min_height=10)
        overlay.title = dialog.title
        self.popup_stack.append((self.frame.get_focus(), self.frame.body))
        self.frame.body = overlay
        self.frame.set_focus('body')

    def close_popup(self, widget=None):
        focus, body = self.popup_stack.pop()
        self.frame.body = body
        self.frame.set_focus(focus)

    def unhandled_input(self, key):
        if isinstance(key, str):
            if key == 'tab' and not self.popup_stack:
                self.frame.set_focus(
                    'body' if self.frame.get_focus() == 'footer' else
                    'footer')
                return True
            else:
                try:
                    {
                        'p': self.pause,
                        'r': self.resume,
                        'k': self.kill_slave,
                        't': self.terminate_master,
                        'q': self.quit,
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

    def quit(self, widget=None):
        raise widgets.ExitMainLoop()

    def pause(self, widget=None):
        self.ctrl_queue.send_json(('PAUSE',))

    def resume(self, widget=None):
        self.ctrl_queue.send_json(('RESUME',))

    def kill_slave(self, widget=None):
        try:
            widget = self.slave_list[self.slave_list.focus]
        except IndexError:
            self.slave_to_kill = None
        else:
            for slave_id, slave in self.slave_list.slaves.items():
                if slave.widget == widget:
                    self.slave_to_kill = slave_id
                    break
            dialog = widgets.YesNoDialog('Kill Slave',
                                 'Are you sure you wish to shutdown slave {}? '
                                 'NOTE: this will only request shutdown after '
                                 'current task finishes; it will not terminate '
                                 'a "stuck" slave'.format(self.slave_to_kill))
            widgets.connect_signal(dialog, 'yes', self._kill_slave)
            widgets.connect_signal(dialog, 'no', self.close_popup)
            self.show_popup(dialog)

    def _kill_slave(self, widget=None):
        self.close_popup()
        slave = self.slave_list.slaves[self.slave_to_kill]
        slave.terminated = True
        self.ctrl_queue.send_json(('KILL', self.slave_to_kill))
        self.slave_to_kill = None

    def terminate_master(self, widget=None):
        dialog = widgets.YesNoDialog('Terminate Master',
                             'Are you sure you wish to shutdown the master?\n\n'
                             'NOTE: this will also request shutdown of all '
                             'slaves, and exit this application')
        widgets.connect_signal(dialog, 'yes', self._terminate_master)
        widgets.connect_signal(dialog, 'no', self.close_popup)
        self.show_popup(dialog)

    def _terminate_master(self, widget=None):
        self.ctrl_queue.send_json(('QUIT',))
        raise widgets.ExitMainLoop()


class SlaveListWalker(widgets.ListWalker):
    def __init__(self):
        super().__init__()
        self.focus = 0
        self.slaves = {} # maps slave ID to SlaveState
        self.widgets = [] # list of SlaveState.widget objects in list order

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
            if state.terminated and (now - state.last_seen > timedelta(seconds=5)):
                self.widgets.remove(state.widget)
                del self.slaves[slave_id]
        self.focus = min(self.focus, len(self.widgets) - 1)
        self._modified()


class SlaveState:
    def __init__(self):
        self.widget = widgets.AttrMap(
            widgets.SelectableIcon(''), None,
            focus_map={'status': 'inv_status'}
        )
        self.terminated = False
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
            self.terminated = True
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
