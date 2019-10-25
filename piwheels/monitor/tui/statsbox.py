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

"Defines the stats boxes for the master and slaves"

from operator import attrgetter

from piwheels import widgets as wdg
from piwheels.format import format_size, format_timedelta


def extract(stats, attr):
    """
    Extract the named *attr* from *stats*, a sequence of :class:`MasterStats`
    or :class:`SlaveStats` instances returning a generator of ``(timestamp,
    attr)`` pairs.
    """
    value = attrgetter(attr)
    return ((s.timestamp, value(s)) for s in stats)


def invert(stats, attr, size_attr):
    """
    Similar to :func:`extract` this returns the named *attr* from *stats*, a
    sequence of :class:`MasterStats` or :class:`SlaveStats` instances. However,
    rather than returning the value of *attr* verbatim, it returns the result
    of subtracting *attr* from *size_attr*. This can be used to return usage of
    a resource from its free value, for instance.
    """
    value = attrgetter(attr)
    size = attrgetter(size_attr)
    return ((s.timestamp, size(s) - value(s)) for s in stats)


class MasterStatsBox(wdg.WidgetWrap):
    def __init__(self):
        self.board_label = wdg.Text('-')
        self.serial_label = wdg.Text('-')
        self.os_label = wdg.Text('-')
        self.load_bar = wdg.TrendBar(
            minimum=0.0, format=lambda x: '{:.3g}'.format(x))
        self.temperature_bar = wdg.TrendBar(
            minimum=40, maximum=100, format=lambda x: '{:.3g}°C'.format(x),
            show_current=True)
        self.disk_bar = wdg.TrendBar(minimum=0, format=format_size)
        self.swap_bar = wdg.TrendBar(minimum=0, format=format_size)
        self.memory_bar = wdg.TrendBar(minimum=0, format=format_size)
        self.builds_bar = wdg.RatioBar()
        self.queue_bar = wdg.RatioBar()
        self.downloads_bar = wdg.TrendBar(minimum=0)
        self.builds_size_label = wdg.Text('-')
        self.builds_time_label = wdg.Text('-')
        self.files_count_label = wdg.Text('-')
        super().__init__(
            wdg.AttrMap(
                wdg.LineBox(
                    wdg.Columns([
                        (12, wdg.Pile([
                            wdg.Text('Board'),
                            wdg.Text('Serial #'),
                            wdg.Text('OS'),
                            wdg.Text('Build Size'),
                            wdg.Text('Build Time'),
                            wdg.Text('File Count'),
                            wdg.Text('Queue'),
                        ])),
                        wdg.Pile([
                            self.board_label,
                            self.serial_label,
                            self.os_label,
                            self.builds_size_label,
                            self.builds_time_label,
                            self.files_count_label,
                            self.queue_bar,
                        ]),
                        (12, wdg.Pile([
                            wdg.Text('Temperature'),
                            wdg.Text('Load Avg'),
                            wdg.Text('Disk'),
                            wdg.Text('Swap'),
                            wdg.Text('Memory'),
                            wdg.Text('Downloads/hr'),
                            wdg.Text('Builds/hr'),
                        ])),
                        wdg.Pile([
                            self.temperature_bar,
                            self.load_bar,
                            self.disk_bar,
                            self.swap_bar,
                            self.memory_bar,
                            self.downloads_bar,
                            self.builds_bar,
                        ]),
                    ], dividechars=1),
                ),
                'dialog',
            )
        )

    def update(self, state):
        self.board_label.set_text(state.board_revision)
        self.serial_label.set_text(state.board_serial)
        self.os_label.set_text('{} {}'.format(state.os_name, state.os_version))
        if not state.stats:
            self.disk_bar.update(())
            self.swap_bar.update(())
            self.memory_bar.update(())
            self.queue_bar.update({})
            self.builds_bar.update({})
            self.downloads_bar.update(())
            self.load_bar.update(())
            self.temperature_bar.update(())
            self.builds_size_label.set_text('-')
            self.builds_time_label.set_text('-')
            self.files_count_label.set_text('-')
        else:
            latest = state.stats[-1]
            self.disk_bar.maximum = latest.disk_size
            self.swap_bar.maximum = latest.swap_size
            self.memory_bar.maximum = latest.mem_size
            self.disk_bar.update(invert(state.stats, 'disk_free', 'disk_size'))
            self.swap_bar.update(invert(state.stats, 'swap_free', 'swap_size'))
            self.memory_bar.update(invert(state.stats, 'mem_free', 'mem_size'))
            self.queue_bar.update(state.stats[-1].builds_pending)
            self.builds_bar.update(state.stats[-1].builds_last_hour)
            self.downloads_bar.update(extract(state.stats, 'downloads_last_hour'))
            self.load_bar.update(extract(state.stats, 'load_average'))
            self.temperature_bar.update(extract(state.stats, 'cpu_temp'))
            self.builds_size_label.set_text(format_size(latest.builds_size))
            self.builds_time_label.set_text(format_timedelta(latest.builds_time))
            self.files_count_label.set_text('{:,}'.format(latest.files_count))


class SlaveStatsBox(wdg.WidgetWrap):
    def __init__(self):
        self.board_label = wdg.Text('-')
        self.serial_label = wdg.Text('-')
        self.python_label = wdg.Text('-')
        self.os_label = wdg.Text('-')
        self.clock_label = wdg.Text('-')
        self.load_bar = wdg.TrendBar(
            minimum=0.0, format=lambda x: '{:.3g}'.format(x))
        self.temperature_bar = wdg.TrendBar(
            minimum=40, maximum=100, format=lambda x: '{:.3g}°C'.format(x),
            show_current=True)
        self.disk_bar = wdg.TrendBar(minimum=0, format=format_size)
        self.swap_bar = wdg.TrendBar(minimum=0, format=format_size)
        self.memory_bar = wdg.TrendBar(minimum=0, format=format_size)
        super().__init__(
            wdg.AttrMap(
                wdg.LineBox(
                    wdg.Columns([
                        (11, wdg.Pile([
                            wdg.Text('Board'),
                            wdg.Text('Serial #'),
                            wdg.Text('OS'),
                            wdg.Text('Python'),
                            wdg.Text('Clock Delta'),
                        ])),
                        wdg.Pile([
                            self.board_label,
                            self.serial_label,
                            self.os_label,
                            self.python_label,
                            self.clock_label,
                        ]),
                        (11, wdg.Pile([
                            wdg.Text('Temperature'),
                            wdg.Text('Load Avg'),
                            wdg.Text('Disk'),
                            wdg.Text('Swap'),
                            wdg.Text('Memory'),
                        ])),
                        wdg.Pile([
                            self.temperature_bar,
                            self.load_bar,
                            self.disk_bar,
                            self.swap_bar,
                            self.memory_bar,
                        ]),
                    ], dividechars=1)
                ),
                'dialog'
            )
        )

    def update(self, state):
        self.board_label.set_text(state.board_revision)
        self.serial_label.set_text(state.board_serial)
        self.os_label.set_text('{} {}'.format(state.os_name, state.os_version))
        self.python_label.set_text('{} (on {})'.format(
            state.py_version, state.platform))
        if not state.stats:
            self.clock_label.set_text('-')
            self.disk_bar.update(())
            self.swap_bar.update(())
            self.memory_bar.update(())
            self.load_bar.update(())
            self.temperature_bar.update(())
        else:
            self.clock_label.set_text(format_timedelta(state.clock_skew))
            latest = state.stats[-1]
            self.disk_bar.maximum = latest.disk_size
            self.swap_bar.maximum = latest.swap_size
            self.memory_bar.maximum = latest.mem_size
            self.disk_bar.update(invert(state.stats, 'disk_free', 'disk_size'))
            self.swap_bar.update(invert(state.stats, 'swap_free', 'swap_size'))
            self.memory_bar.update(invert(state.stats, 'mem_free', 'mem_size'))
            self.load_bar.update(extract(state.stats, 'load_average'))
            self.temperature_bar.update(extract(state.stats, 'cpu_temp'))
