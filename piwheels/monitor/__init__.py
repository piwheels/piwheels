import os
from datetime import datetime, timedelta

import zmq

from . import widgets
from ..terminal import TerminalApplication
from .. import __version__


class PiWheelsMonitor(TerminalApplication):
    def __init__(self):
        super().__init__(__version__, __doc__, log_params=False)

    def load_configuration(self, args):
        config = super().load_configuration(args, default={
            'monitor': {
                'ext_control_queue': 'ipc:///tmp/piw-control',
                'ext_status_queue':  'ipc:///tmp/piw-status',
            },
        })
        config = dict(config['monitor'])
        # Expand any ~ in paths
        for item, value in list(config.items()):
            if item.endswith('_queue') and value.startswith('ipc://'):
                config[item] = os.path.expanduser(value)
        return config

    def main(self, args, config):
        ctx = zmq.Context()
        self.status_queue = ctx.socket(zmq.SUB)
        self.status_queue.hwm = 10
        self.status_queue.connect(config['ext_status_queue'])
        self.status_queue.setsockopt_string(zmq.SUBSCRIBE, '')
        self.ctrl_queue = ctx.socket(zmq.PUSH)
        self.ctrl_queue.connect(config['ext_control_queue'])
        self.ctrl_queue.send_pyobj(['HELLO'])
        try:
            self.loop = widgets.MainLoop(
                *self.build_ui(),
                event_loop=widgets.ZMQEventLoop(),
                unhandled_input=self.unhandled_input)
            self.loop.event_loop.watch_queue(self.status_queue, self.status_message)
            self.loop.event_loop.alarm(1, self.tick)
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
                widgets.AttrMap(
                    widgets.Divider('\N{UPPER HALF BLOCK}'),
                    'coltrans'
                ),
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
        self.build_rate_label = widgets.Text('- pkgs/hour')
        self.build_time_label = widgets.Text('-:--:--')
        self.build_size_label = widgets.Text('- bytes')
        status_box = widgets.AttrMap(
            widgets.Pile([
                widgets.Columns([
                    (12, widgets.Pile([
                        widgets.Text('Disk Free'),
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
                widgets.AttrMap(
                    widgets.Divider('\N{LOWER HALF BLOCK}'),
                    'coltrans'
                ),
                widgets.AttrMap(
                    widgets.Columns([
                        (2, widgets.Text('S')),
                        (3, widgets.Text(' #')),
                        (9, widgets.Text('  UpTime')),
                        (9, widgets.Text('TaskTime')),
                        (6, widgets.Text('ABI')),
                        widgets.Text('Task'),
                    ]),
                    'colheader'
                ),
            ]),
            'header'
        )
        self.frame = widgets.Frame(
            list_box,
            header=status_box,
            footer=actions_box
        )
        return self.frame, widgets.palette

    def status_message(self):
        slave_id, timestamp, msg, *args = self.status_queue.recv_pyobj()
        if msg == 'STATUS':
            self.update_status(args[0])
        else:
            self.slave_list.message(slave_id, timestamp, msg, *args)

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
        time = status_info['builds_time']
        time -= timedelta(microseconds=time.microseconds)
        self.build_time_label.set_text('{}'.format(time))

    def quit(self, widget=None):
        raise widgets.ExitMainLoop()

    def pause(self, widget=None):
        self.ctrl_queue.send_pyobj(['PAUSE'])

    def resume(self, widget=None):
        self.ctrl_queue.send_pyobj(['RESUME'])

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
            dialog = widgets.YesNoDialog(
                'Kill Slave',
                'Are you sure you wish to shutdown slave {}?\n\n'
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
        self.ctrl_queue.send_pyobj(['KILL', self.slave_to_kill])
        self.slave_to_kill = None

    def terminate_master(self, widget=None):
        dialog = widgets.YesNoDialog(
            'Terminate Master',
            'Are you sure you wish to shutdown the master?\n\n'
            'NOTE: this will also request shutdown of all '
            'slaves, and exit this application')
        widgets.connect_signal(dialog, 'yes', self._terminate_master)
        widgets.connect_signal(dialog, 'no', self.close_popup)
        self.show_popup(dialog)

    def _terminate_master(self, widget=None):
        self.ctrl_queue.send_pyobj(['QUIT'])
        raise widgets.ExitMainLoop()


class SlaveListWalker(widgets.ListWalker):
    def __init__(self):
        super().__init__()
        self.focus = None
        self.slaves = {}   # maps slave ID to SlaveState
        self.widgets = []  # list of SlaveState.widget objects in list order

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
        if position < 0:  # don't permit negative indexes for focus
            raise IndexError
        self.widgets[position]  # raises IndexError if position is invalid
        self.focus = position
        self._modified()

    def message(self, slave_id, timestamp, msg, *args):
        try:
            state = self.slaves[slave_id]
        except KeyError:
            state = SlaveState(slave_id)
            self.slaves[slave_id] = state
            self.widgets.append(state.widget)
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
        if self.widgets:
            self.focus = min(self.focus or 0, len(self.widgets) - 1)
        else:
            self.focus = None
        self._modified()


class SlaveState:
    def __init__(self, slave_id):
        self.widget = widgets.AttrMap(
            widgets.SelectableIcon(''), None,
            focus_map={'status': 'inv_status'}
        )
        self.terminated = False
        self.slave_id = slave_id
        self.last_msg = ''
        self.py_version = '-'
        self.abi = '-'
        self.platform = '-'
        self.first_seen = None
        self.last_seen = None
        self.status = ''

    def update(self, timestamp, msg, *args):
        self.last_msg = msg
        self.last_seen = timestamp
        if msg == 'HELLO':
            self.status = 'Initializing'
            self.first_seen = timestamp
            self.py_version = args[0]
            self.abi = args[1]
            self.platform = args[2]
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

    @property
    def state(self):
        if self.last_msg == 'SLEEP':
            return 'idle'
        if self.last_seen is not None:
            if datetime.utcnow() - self.last_seen > timedelta(minutes=10):
                return 'silent'
        return 'busy'

    def tick(self):
        self.widget.original_widget.set_text([
            (self.state, '* '),
            ('status', '%2s' % self.slave_id),
            ('status', ' '),
            ('status', since(self.first_seen)),
            ('status', ' '),
            ('status', since(self.last_seen)),
            ('status', ' '),
            ('status', '%-5s' % self.abi),
            ('status', ' '),
            ('status', self.status),
        ])


def since(dt, template='%8s'):
    if dt is None:
        return template % '-'
    else:
        return template % (datetime.utcnow().replace(microsecond=0) - dt.replace(microsecond=0))


main = PiWheelsMonitor()
