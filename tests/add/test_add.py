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


from datetime import datetime, timezone
from unittest import mock
from threading import Thread

import pytest

from conftest import find_message
from piwheels import __version__, protocols, transport
from piwheels.add import main


UTC = timezone.utc


@pytest.fixture()
def import_queue_name(request, tmpdir):
    yield 'ipc://' + str(tmpdir.join('import-queue'))


@pytest.fixture()
def import_queue(request, mock_context, import_queue_name, tmpdir):
    queue = mock_context.socket(transport.REP, protocol=protocols.mr_chase)
    queue.hwm = 1
    queue.bind(import_queue_name)
    yield queue
    queue.close()


class AddThread(Thread):
    def __init__(self, args):
        super().__init__(target=self.capture_exc, args=(args,), daemon=True)
        self.exception = None
        self.exitcode = None

    def capture_exc(self, args):
        try:
            self.exitcode = main(args)
        except Exception as e:
            self.exception = e

    def join(self, timeout):
        super().join(timeout)
        if self.exception:
            raise self.exception  # re-raise in the main thread

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        try:
            self.join(10)
        except Exception:
            pass  # ignore any re-raise
        assert not self.is_alive()


def test_help(capsys):
    with pytest.raises(SystemExit):
        main(['--help'])
    out, err = capsys.readouterr()
    assert out.startswith('usage:')
    assert '--yes' in out
    assert '--skip' in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(['--version'])
    out, err = capsys.readouterr()
    assert out.strip() == __version__


def test_abort(caplog):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = False
        assert main(['foo', '0.1']) == 2
    assert find_message(caplog.records, message='User aborted addition')


def test_add_package(mock_json_server, mock_context, import_queue_name,
                     import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        mock_json_server['foo'] = 'DESCRIPTION'
        with AddThread(['--import-queue', import_queue_name, 'foo']) as thread:
            assert import_queue.recv_msg() == ('ADDPKG',
                ['foo', 'DESCRIPTION', '', False, []]
            )
            import_queue.send_msg('DONE', 'NEWPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_add_and_skip_package(mock_json_server, mock_context,
                              import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        mock_json_server['foo'] = 'DESCRIPTION'
        with AddThread(['--import-queue', import_queue_name, 'foo', '--skip',
                        'legal']) as thread:
            assert import_queue.recv_msg() == ('ADDPKG',
                ['foo', 'DESCRIPTION', 'legal', False, []]
            )
            import_queue.send_msg('DONE', 'NEWPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_add_package_with_description(mock_context, import_queue_name,
                                      import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with AddThread(['--import-queue', import_queue_name, 'foo', '-d',
                        'description']) as thread:
            assert import_queue.recv_msg() == ('ADDPKG',
                ['foo', 'description', '', False, []]
            )
            import_queue.send_msg('DONE', 'NEWPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_add_package_with_alias(mock_json_server, mock_context,
                                import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        mock_json_server['foobar'] = 'DESCRIPTION'
        with AddThread(['--import-queue', import_queue_name, 'foobar', '-a',
                        'FooBar']) as thread:
            assert import_queue.recv_msg() == ('ADDPKG',
                ['foobar', 'DESCRIPTION', '', False, ['FooBar']]
            )
            import_queue.send_msg('DONE', 'NEWPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_add_package_with_aliases(mock_json_server, mock_context,
                                  import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        mock_json_server['foobar'] = 'DESCRIPTION'
        with AddThread(['--import-queue', import_queue_name, 'foobar', '-a',
                        'FooBar', '-a', 'fooBar']) as thread:
            assert import_queue.recv_msg() == ('ADDPKG',
                ['foobar', 'DESCRIPTION', '', False, ['FooBar', 'fooBar']]
            )
            import_queue.send_msg('DONE', 'NEWPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_add_package_with_bad_alias(mock_json_server, mock_context,
                                    import_queue_name, import_queue):
    mock_json_server['foobar'] = 'DESCRIPTION'
    with AddThread(['--import-queue', import_queue_name, 'foobar', '-a',
                    'Foo-Bar', '--yes']) as thread:
        with pytest.raises(RuntimeError) as exc:
            thread.join(10)
        assert 'Alias Foo-Bar does not match canon: foobar' in str(exc.value)


def test_skip_known_package(mock_json_server, mock_context, import_queue_name,
                            import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        mock_json_server['foo'] = 'DESCRIPTION'
        with AddThread(['--import-queue', import_queue_name, 'foo', '--skip',
                        'skip']) as thread:
            assert import_queue.recv_msg() == ('ADDPKG',
                ['foo', 'DESCRIPTION', 'skip', False, []]
            )
            import_queue.send_msg('ERROR', 'SKIPPKG')
            with pytest.raises(RuntimeError) as exc:
                thread.join(10)
            assert ('Cannot skip a known package with piw-add - use '
                    'piw-remove instead') in str(exc.value)


def test_unskip_known_package(mock_json_server, mock_context,
                              import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        mock_json_server['foo'] = 'DESCRIPTION'
        with AddThread(['--import-queue', import_queue_name, 'foo',
                        '--unskip']) as thread:
            assert import_queue.recv_msg() == ('ADDPKG',
                ['foo', 'DESCRIPTION', '', True, []]
            )
            import_queue.send_msg('DONE', 'UPDPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_update_known_package_description(mock_context, import_queue_name,
                                          import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with AddThread(['--import-queue', import_queue_name, 'foo', '-d',
                        'description']) as thread:
            assert import_queue.recv_msg() == ('ADDPKG',
                ['foo', 'description', '', False, []]
            )
            import_queue.send_msg('DONE', 'UPDPKG')
            thread.join(10)
            assert thread.exitcode == 0


def test_add_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name,
                            'foo', '0.1']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', '', False,
                    datetime(2021, 1, 1, tzinfo=UTC), False, False, []
                ])
                import_queue.send_msg('DONE', 'NEWVER')
                thread.join(10)
                assert thread.exitcode == 0


def test_add_and_skip_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name, 'foo', '0.1',
                            '--skip', 'legal']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', 'legal', False,
                    datetime(2021, 1, 1, tzinfo=UTC), False, False, []
                ])
                import_queue.send_msg('DONE', 'NEWVER')
                thread.join(10)
                assert thread.exitcode == 0


def test_add_and_yank_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name, 'foo', '0.1',
                            '--yank']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', '', False,
                    datetime(2021, 1, 1, tzinfo=UTC), True, False, []
                ])
                import_queue.send_msg('DONE', 'NEWVER')
                thread.join(10)
                assert thread.exitcode == 0


def test_add_version_with_release_date(mock_context, import_queue_name,
                                       import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name, 'foo', '0.1',
                            '--released', '2020-06-06 00:00:00']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', '', False,
                    datetime(2020, 6, 6, tzinfo=UTC), False, False, []
                ])
                import_queue.send_msg('DONE', 'NEWVER')
                thread.join(10)
                assert thread.exitcode == 0


def test_add_version_for_unknown_package(mock_context, import_queue_name,
                                         import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name,
                            'foo', '0.1']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', '', False,
                    datetime(2021, 1, 1, tzinfo=UTC), False, False, []
                ])
                import_queue.send_msg('ERROR', 'NOPKG')
                with pytest.raises(RuntimeError) as exc:
                    thread.join(10)
                assert ('Package foo does not exist - add it with piw-add '
                        'first') in str(exc.value)


def test_skip_known_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name, 'foo', '0.1',
                            '--skip', 'legal']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', 'legal', False,
                    datetime(2021, 1, 1, tzinfo=UTC), False, False, []
                ])
                import_queue.send_msg('ERROR', 'SKIPVER')
                with pytest.raises(RuntimeError) as exc:
                    thread.join(10)
                assert ('Cannot skip a known version with piw-add - use '
                        'piw-remove instead') in str(exc.value)


def test_unskip_known_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name, 'foo', '0.1',
                            '--unskip']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', '', True,
                    datetime(2021, 1, 1, tzinfo=UTC), False, False, []
                ])
                import_queue.send_msg('DONE', 'UPDVER')
                thread.join(10)
                assert thread.exitcode == 0


def test_yank_known_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name, 'foo', '0.1',
                            '--yank']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', '', False,
                    datetime(2021, 1, 1, tzinfo=UTC), True, False, []
                ])
                import_queue.send_msg('ERROR', 'YANKVER')
                with pytest.raises(RuntimeError) as exc:
                    thread.join(10)
                assert ('Cannot yank a known version with piw-add - use '
                        'piw-remove instead') in str(exc.value)


def test_unyank_known_version(mock_context, import_queue_name, import_queue):
    with mock.patch('piwheels.terminal.yes_no_prompt') as prompt_mock:
        prompt_mock.return_value = True
        with mock.patch('piwheels.add.datetime') as dt:
            dt.utcnow.return_value = datetime(2021, 1, 1)
            dt.strptime.side_effect = datetime.strptime
            with AddThread(['--import-queue', import_queue_name, 'foo', '0.1',
                            '--unyank']) as thread:
                assert import_queue.recv_msg() == ('ADDVER',[
                    'foo', '0.1', '', False,
                    datetime(2021, 1, 1, tzinfo=UTC), False, True, []
                ])
                import_queue.send_msg('DONE', 'UPDVER')
                thread.join(10)
                assert thread.exitcode == 0
