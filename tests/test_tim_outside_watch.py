"""Outside watch from the Mac (design D, section 15, PR-3). No network, no ssh, no osascript, no security CLI:
one fake runner answers for all four commands, GitHub is `IncidentRest` behind the injectable transport."""
from __future__ import annotations

import ast
import base64
import contextlib
import io
import json
import plistlib
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.task_governance.github_gateway import _NotSent
from src.tim_incident import github as gh
from src.tim_incident import watch
from src.tim_incident.redaction import final_scan
from tests import test_tim_incident_github as base

ROOT = Path(__file__).resolve().parents[1]
PLIST = ROOT / 'ops/launchd/com.tim.outside-watch.plist'
REPO, BOT, OWNER, TOKEN, KEY = base.REPO, base.BOT, base.OWNER, base.TOKEN, base.KEY
W = 4
START = 1791343200.0                                 # 2026-10-07 03:20 UTC
SSH_SECRET = 'GEHEIM-SSH-AUSGABE-7f3a'               # a line of ssh output that must never be logged
ENV = {'HOME': '/Users/tim', 'TIM_WATCH_ISSUE': str(W), 'TIM_WATCH_APP_ID': str(base.APP_ID),
       'TIM_WATCH_INSTALLATION_ID': str(base.INSTALLATION), 'TIM_WATCH_REPORTER_LOGIN': BOT}
SETTINGS = watch.load_watch_settings(ENV)


def show(checkup_exit, health_exit, *, result='success', status=0, active='inactive', start=None, extra=''):
    """`systemctl show --timestamp=unix` as the forced command prints it (systemd's own property order)."""
    def ts(value):
        return '' if value is None else f'@{int(value)}'
    return (f'Id=tim-checkup.service\nActiveState={active}\nResult={result}\nExecMainStartTimestamp='
            f'{ts(start if start is not None else (checkup_exit - 40 if checkup_exit else None))}\n'
            f'ExecMainExitTimestamp={ts(checkup_exit)}\nExecMainStatus={status}\n{extra}\n\n'
            f'Id=tim-server-health.service\nActiveState=inactive\nResult=success\n'
            f'ExecMainStartTimestamp={ts(health_exit - 2 if health_exit else None)}\n'
            f'ExecMainExitTimestamp={ts(health_exit)}\nExecMainStatus=0\n')


class Clock:
    def __init__(self, now=START):
        self.now = float(now)

    def __call__(self):
        return self.now


class Server:
    """What the forced command answers; `reachable=False` or a timeout makes ssh fail."""

    def __init__(self, clock):
        self.clock, self.reachable, self.timeout = clock, True, False
        self.checkup = {'exit': clock.now - 120, 'result': 'success', 'status': 0}

    def new_run(self, status=0, result=None):
        self.checkup = {'exit': self.clock.now - 30, 'status': status,
                        'result': result or ('success' if status == 0 else 'exit-code')}

    def answer(self):
        return show(self.checkup['exit'], self.clock.now - 20, result=self.checkup['result'],
                    status=self.checkup['status'], extra=f'Note={SSH_SECRET}')


class Runner:
    """ssh, security, openssl and osascript in one fake. Records argv; checks the key file while openssl runs."""

    def __init__(self, server, *, key=KEY, keychain_code=0):
        self.server, self.calls, self.notifications, self.key_files = server, [], [], []
        self.keychain = base64.b64encode(key.encode()) + b'\n' if key is not None else b''
        self.keychain_code, self.openssl_code = keychain_code, 0

    def __call__(self, argv, *, input=None, timeout):
        argv = list(argv)
        self.calls.append(argv)
        name = argv[0]
        if name == 'ssh':
            host = argv[-1]
            if self.server.timeout:
                raise subprocess.TimeoutExpired(argv, timeout)
            if host != 'tim-server' or not self.server.reachable:
                return SimpleNamespace(returncode=255, stdout=b'', stderr=b'ssh: Could not resolve hostname')
            return SimpleNamespace(returncode=0, stdout=self.server.answer().encode(), stderr=b'')
        if name == 'security':
            return SimpleNamespace(returncode=self.keychain_code, stdout=self.keychain, stderr=b'')
        if name == 'openssl':
            path = Path(argv[argv.index('-sign') + 1])
            info, folder = path.stat(), path.parent.stat()
            self.key_files.append((path, stat.S_IMODE(info.st_mode), stat.S_IMODE(folder.st_mode),
                                   path.read_text()))
            return SimpleNamespace(returncode=self.openssl_code, stdout=base.SIGNATURE, stderr=b'')
        if name == 'osascript':
            self.notifications.append(argv[-2])
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        raise AssertionError(f'unexpected command {name}')

    def ssh_calls(self):
        return [argv for argv in self.calls if argv[0] == 'ssh']


class Net:
    """GitHub: /zen for the online check, the rest goes to IncidentRest. `offline` fails everything before sending."""

    def __init__(self, rest):
        self.rest, self.offline, self.drop_comment_posts, self.token_seen_key = rest, False, 0, []
        self.key_path_probe = None

    def __call__(self, method, url, headers, body, timeout):
        if self.offline:
            raise _NotSent()
        if url.endswith('/zen'):
            assert timeout == watch.ONLINE_TIMEOUT and method == 'GET'
            return 200, b'Keep it logically awesome.'
        if url.endswith('/access_tokens') and self.key_path_probe is not None:
            self.token_seen_key.append(any(self.key_path_probe.glob('*/key.pem')))
        if method == 'POST' and url.endswith('/comments') and self.drop_comment_posts:
            self.drop_comment_posts -= 1
            raise _NotSent()
        return self.rest(method, url, headers, body, timeout)


class World:
    def __init__(self, tmp_path):
        self.clock = Clock()
        self.server = Server(self.clock)
        self.rest = base.IncidentRest()
        self.rest.seed(W, 'Außenwache vom Mac', login=OWNER, labels=['status:external-action'])
        self.rest.seed(10, base.marked(), login=BOT)
        self.net = Net(self.rest)
        self.runner = Runner(self.server)
        self.state_path = tmp_path / 'state' / 'state.json'
        self.tempdir = tmp_path / 'tmp'
        self.tempdir.mkdir(parents=True)
        self.net.key_path_probe = self.tempdir
        self.records = []

    def poll(self, host='tim-server', settings=SETTINGS, minutes=5):
        record = watch.run_once(settings, host=host, repository=REPO, runner=self.runner, transport=self.net,
                                clock=self.clock, state_path=self.state_path, tempdir=str(self.tempdir))
        self.records.append(record)
        self.clock.now += minutes * 60
        return record

    def comments(self):
        return [c['body'] for c in self.rest.comments.get(W, [])]

    def state(self):
        return json.loads(self.state_path.read_text())


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


# --- fixed argv and parser ---------------------------------------------------------------------------------------

def test_ssh_argv_is_fixed():
    assert watch.ssh_argv('/Users/tim') == [
        'ssh', '-T', '-i', '/Users/tim/.ssh/tim_watch_ed25519', '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
        '-o', 'RequestTTY=no', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5', '-o',
        'ServerAliveCountMax=2', '-o', 'ControlMaster=no', '-o', 'ControlPath=none', '-o', 'ClearAllForwardings=yes',
        'tim-server']
    assert watch.ssh_argv('/Users/tim', 'tim-server-unreachable.invalid')[-1] == 'tim-server-unreachable.invalid'
    for host in ('-oProxyCommand=touch /tmp/x', 'tim server', '', 'a..b', 'tim-server;id', '.tim', 'x' * 300, None):
        assert not watch.valid_host(host)
        with pytest.raises(watch.WatchError):
            watch.ssh_argv('/Users/tim', host)


def test_systemctl_show_parser():
    text = show(START - 100, START - 10, result='exit-code', status=3) + '\nId=other.service\nResult=success\n'
    units = watch.parse_show('garbage line\n' + text)
    assert set(units) == set(watch.UNITS)
    assert units['tim-checkup.service'] == {'active': 'inactive', 'result': 'exit-code', 'status': 3,
                                            'start': int(START - 140), 'exit': int(START - 100)}
    assert units['tim-server-health.service']['exit'] == int(START - 10)
    empty = watch.parse_show('Id=tim-checkup.service\nExecMainExitTimestamp=\nExecMainStartTimestamp=n/a\n'
                             'ExecMainStatus=x\nResult=$(rm -rf)\n')
    assert empty['tim-checkup.service'] == {'active': None, 'result': None, 'status': None, 'start': None,
                                            'exit': None}
    assert watch.parse_show('') == {}


# --- decision table ----------------------------------------------------------------------------------------------

def _units(text):
    return watch.parse_show(text)


@pytest.mark.parametrize('name, units, expected', [
    ('ssh fails', None, watch.SILENT),
    ('fresh and clean', show(START - 600, START - 30), watch.OK),
    ('checkup end older than 35 min', show(START - 36 * 60, START - 30), watch.STALE),
    ('checkup at 35 min is fine', show(START - 35 * 60, START - 30), watch.OK),
    ('health end older than 5 min', show(START - 600, START - 6 * 60), watch.STALE),
    ('checkup never ended', show(None, START - 30), watch.STALE),
    ('checkup running, started recently', show(None, START - 30, active='activating', start=START - 60), watch.OK),
    ('one failed run is not yet IMPAIRED', show(START - 600, START - 30, result='exit-code', status=1), watch.OK),
])
def test_decision_table(name, units, expected):
    decision = watch.decide(None if units is None else _units(units), {'last_exit': None, 'failed': []}, START)
    assert decision.state == expected, name


def test_impaired_needs_two_different_failed_runs():
    runs = {'last_exit': None, 'failed': []}
    first = _units(show(START - 900, START - 30, result='exit-code', status=1))
    for _ in range(3):                                           # the same run, seen three times
        assert watch.decide(first, runs, START).state == watch.OK
    assert len(runs['failed']) == 1
    second = _units(show(START - 60, START - 30, result='exit-code', status=3))
    decision = watch.decide(second, runs, START)
    assert decision.state == watch.IMPAIRED and watch.impaired_text(decision.detail) == 'Melden gestört'
    clean = _units(show(START + 840, START + 870))
    assert watch.decide(clean, runs, START + 900).state == watch.OK and runs['failed'] == []
    decision.detail.update(reporting=False, status=1)
    assert watch.impaired_text(decision.detail) == 'Checkup fehlgeschlagen (Status 1)'
    assert watch.impaired_text({'status': 0, 'result': 'timeout'}) == 'Checkup fehlgeschlagen (Status timeout)'


# --- alarm, episode, recovery ------------------------------------------------------------------------------------

def test_two_silent_exactly_one_comment_then_one_recovery(world):
    world.server.reachable = False
    first = world.poll()
    assert (first['state'], first['actions'], world.comments()) == ('SILENT', [], [])     # 1 deviation: no alarm
    for _ in range(4):
        world.poll()
    assert len(world.comments()) == 1
    alarm = world.comments()[0]
    episode = watch.episode_id(START)
    assert alarm.startswith(f'<!-- TIM_OUTSIDE_WATCH:{episode}:silent -->\n')
    assert 'antwortet nicht per ssh' in alarm and not final_scan(alarm)
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['SILENT']]
    world.server.reachable = True
    world.server.new_run()
    first_ok = world.poll()
    assert first_ok['actions'] == [] and first_ok['episode'] == episode    # one OK pass is no recovery yet
    recovered = world.poll()
    assert recovered['actions'] == ['recovered'] and recovered['duration_s'] == 25 * 60     # until the first OK
    world.poll()
    assert len(world.comments()) == 2
    assert world.comments()[1].startswith(f'<!-- TIM_OUTSIDE_WATCH:{episode}:recovered -->\n')
    assert 'nach 25 min vorbei' in world.comments()[1]
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['SILENT'], watch.NOTIFY_TEXTS['recovered']]
    assert world.state()['episode'] is None and world.state()['streak'] == 0


def test_single_deviation_never_alarms(world):
    for _ in range(3):
        world.server.reachable = False
        world.poll()
        world.server.reachable = True
        world.poll()
    assert world.comments() == [] and world.runner.notifications == []


def test_mac_offline_is_unknown_and_never_alarms(world):
    world.net.offline = True
    for _ in range(5):
        record = world.poll()
        assert (record['state'], record['delivery'], record['exit_code']) == ('UNKNOWN', 'skipped', 0)
    assert world.runner.ssh_calls() == [] and world.comments() == [] and world.runner.notifications == []
    assert world.state()['streak'] == 0
    world.net.offline = False
    world.server.reachable = False
    world.poll()                                                  # SILENT 1
    world.net.offline = True
    world.poll()                                                  # UNKNOWN: neither counts nor resets
    world.net.offline = False
    world.poll()                                                  # SILENT 2: alarm
    assert len(world.comments()) == 1


def test_watch_exit1_twice_alarms(world):
    world.server.new_run(status=1)
    world.poll()
    world.server.new_run(status=1)
    record = world.poll()
    assert record['state'] == 'IMPAIRED' and record['actions'] == ['alarm:impaired']
    assert len(world.comments()) == 1 and 'Checkup fehlgeschlagen (Status 1)' in world.comments()[0]
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['IMPAIRED']]
    world.server.new_run(status=3)                                 # still impaired: no second comment
    world.poll()
    assert len(world.comments()) == 1


def test_exit3_twice_says_reporting_disturbed(world):
    for _ in range(2):
        world.server.new_run(status=3)
        world.poll()
    assert 'Melden gestört' in world.comments()[0]
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['impaired_reporting']]


def test_watch_same_run_counted_once(world):
    world.server.new_run(status=1)
    for _ in range(4):                                           # four polls, one failed run (same exit time)
        record = world.poll(minutes=1)
    assert record['state'] == 'OK' and world.comments() == []
    assert len(world.state()['runs']['failed']) == 1


def test_watch_timeout_alarms(world, tmp_path):
    world.server.timeout = True                                  # ssh hangs: the runner times out
    world.poll()
    record = world.poll()
    assert record['state'] == 'SILENT' and len(world.comments()) == 1
    other = World(tmp_path / 'unit-timeout')
    for _ in range(2):
        other.server.new_run(result='timeout', status=0)         # TimeoutStartSec hit in two runs
        record = other.poll()
    assert record['state'] == 'IMPAIRED' and len(other.comments()) == 1
    assert 'Checkup fehlgeschlagen (Status timeout)' in other.comments()[0]


def test_stale_alarm_names_the_ages(world):
    world.server.checkup['exit'] = START - 40 * 60
    world.poll()
    world.poll()
    assert len(world.comments()) == 1 and ':stale -->' in world.comments()[0]
    assert 'vor 45 min (Grenze 35 min)' in world.comments()[0]


def test_failed_comment_is_retried_without_a_second_alarm(world):
    world.server.reachable = False
    world.net.drop_comment_posts = 1
    world.poll()
    record = world.poll()
    assert (record['delivery'], record['pending']) == ('network_down', 1) and world.comments() == []
    record = world.poll()
    assert (record['delivery'], record['pending'], record['posted']) == ('ok', 0, 1)
    world.poll()
    assert len(world.comments()) == 1 and len(world.runner.notifications) == 1


def test_401_gives_the_notification_only(world):
    world.rest.fail[('POST', r'/access_tokens$')] = 401
    world.server.reachable = False
    world.poll()
    record = world.poll()
    assert (record['delivery'], record['pending'], record['exit_code']) == ('unauthorized', 0, 3)
    assert world.comments() == []
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['SILENT'], watch.NOTIFY_TEXTS['unauthorized']]
    world.rest.fail.clear()
    world.poll()                                                 # dropped: no late alarm comment
    assert world.comments() == []


def test_401_on_the_comment_gives_the_notification_only(world):
    world.rest.fail[('POST', r'/issues/4/comments$')] = 401
    world.server.reachable = False
    world.poll()
    record = world.poll()
    assert record['delivery'] == 'unauthorized' and world.comments() == []
    assert world.runner.notifications[-1] == watch.NOTIFY_TEXTS['unauthorized']


def test_missing_keychain_entry_gives_the_notification_only(world):
    world.runner.keychain_code = 44
    world.server.reachable = False
    world.poll()
    record = world.poll()
    assert (record['delivery'], record['exit_code']) == ('key_missing', 3)
    assert not any(argv[0] == 'openssl' for argv in world.runner.calls)
    assert world.runner.notifications[-1] == watch.NOTIFY_TEXTS['key_missing']


# --- key 2, notifications, nothing leaks --------------------------------------------------------------------------

def test_key2_from_keychain_through_a_private_temp_file(world):
    world.server.reachable = False
    world.poll()
    world.poll()
    assert ['security', 'find-generic-password', '-s', 'tim-outside-watch', '-a', 'tim-reporter', '-w'] \
        in world.runner.calls
    [(path, mode, folder_mode, content)] = world.runner.key_files
    assert (mode, folder_mode, content) == (0o600, 0o700, KEY)
    assert path.parent.parent == world.tempdir
    assert world.net.token_seen_key == [False]                   # deleted before the token request left
    assert list(world.tempdir.iterdir()) == []                   # file and directory gone


def test_notification_uses_fixed_text_through_osascript_argv():
    runner_calls = []
    watch.notify(lambda argv, timeout: runner_calls.append(argv) or SimpleNamespace(returncode=0), 'STALE')
    assert runner_calls == [['osascript', '-e', 'on run argv', '-e',
                             'display notification (item 1 of argv) with title (item 2 of argv)', '-e', 'end run',
                             watch.NOTIFY_TEXTS['STALE'], 'TIM Außenwache']]

    def broken(argv, timeout):
        raise FileNotFoundError('osascript')
    assert watch.notify(broken, 'recovered') is False


def test_ssh_output_token_and_key_never_logged(world, capsys):
    for reachable in (False, False, True):
        world.server.reachable = reachable
        world.poll()
    dumped = json.dumps(world.records) + world.state_path.read_text()
    for secret in (SSH_SECRET, TOKEN, KEY.splitlines()[1], 'Keep it logically'):
        assert secret not in dumped
    assert capsys.readouterr().out == ''                          # run_once prints nothing itself
    assert stat.S_IMODE(world.state_path.stat().st_mode) == 0o600
    for comment in world.comments():
        assert SSH_SECRET not in comment and TOKEN not in comment


def test_broken_state_file_is_reset(world):
    world.state_path.parent.mkdir(parents=True)
    world.state_path.write_text('{"version": 1, "pending": "kaputt"}')
    record = world.poll()
    assert record['state_file'] == 'reset' and record['state'] == 'OK'


def test_settings_name_the_variable_never_the_value():
    settings = watch.load_watch_settings({'HOME': 'relative', 'TIM_WATCH_ISSUE': 'ghp_' + 'x' * 36,
                                          'TIM_WATCH_APP_ID': 'EINTRAGEN', 'TIM_WATCH_REPORTER_LOGIN': 'uzi'})
    assert not settings.complete
    assert set(settings.problems) == {'TIM_WATCH_ISSUE invalid', 'TIM_WATCH_APP_ID invalid',
                                      'TIM_WATCH_INSTALLATION_ID missing', 'TIM_WATCH_REPORTER_LOGIN invalid',
                                      'HOME missing'}
    record = watch.run_once(settings, repository=REPO, runner=None, transport=None)
    assert record['exit_code'] == 2 and 'ghp_' not in json.dumps(record)
    assert SETTINGS.complete


# --- write guard: the one exception for W ------------------------------------------------------------------------

def _watch_gateway(rest, **kwargs):
    return gh.IncidentGateway(REPO, TOKEN, reporter_login=BOT, owner_login=None, authority_issue=None,
                              watch_issue=W, transport=rest, outside_watch=True, **kwargs)


def test_guard_allows_only_tagged_comments_on_w():
    rest = base.IncidentRest()
    rest.seed(W, 'Außenwache', login=OWNER, labels=['status:external-action'])
    rest.seed(10, base.marked(), login=BOT)
    rest.seed(3, 'Freigabe', login=OWNER, labels=['governance'])
    gw = _watch_gateway(rest)
    tag = f'TIM_OUTSIDE_WATCH:{watch.episode_id(START)}:silent'
    request = gh.task_request('DATA_FLOW', base.EP, base.HOST, 'Vorfall', base.body_for())
    refused = [
        lambda: gw.comment_once(10, tag, 'Text.'),                         # an incident issue: not for the watch
        lambda: gw.comment_once(3, tag, 'Text.'),
        lambda: gw.comment_once(W, 'evidence', 'Text.'),                   # an incident tag on W
        lambda: gw.comment_once(W, 'TIM_OUTSIDE_WATCH:x:silent', 'Text.'),
        lambda: gw.comment_once(W, tag, f'ghp_{"a1B2" * 9}'),              # final scan
        lambda: gw.add_labels(W, ['incident']),
        lambda: gw.close_incident(W),
        lambda: gw.close_incident(10),
        lambda: gw.set_status_line(10, '- Stand'),
        lambda: gw.update_issue(10, request, 'x'),
        lambda: gw.post_summary([{'class': 'DATA_FLOW', 'episode': base.EP, 'at': base.AT, 'issue': 10}]),
        lambda: gw._comment(10, 'direkt'),                                 # even the raw helper is refused
        lambda: gw._comment(3, 'direkt'),
    ]
    for write in refused:
        with pytest.raises(gh.GuardError):
            write()
    with pytest.raises(Exception):
        gw.create_issue(request, request.fingerprint, timeout=5)
    assert rest.repo_writes() == []
    assert gw.comment_once(W, tag, 'Alarm.') is True and gw.comment_once(W, tag, 'Nochmal.') is False
    assert rest.repo_writes() == [('POST', f'/repos/{REPO}/issues/{W}/comments')]


@pytest.mark.parametrize('change', ['bot_opened', 'other_bot_opened', 'app_account', 'no_label', 'closed', 'locked',
                                    'pull_request'])
def test_guard_refuses_a_w_that_is_not_the_owners_watch_issue(change):
    rest = base.IncidentRest()
    login = {'bot_opened': BOT, 'other_bot_opened': 'github-actions[bot]', 'app_account': 'renovate'}.get(change, OWNER)
    rest.seed(W, 'Außenwache', login=login,
              labels=[] if change == 'no_label' else ['status:external-action'],
              state='closed' if change == 'closed' else 'open', pr=change == 'pull_request')
    if change == 'app_account':
        rest.issues[W]['user']['type'] = 'Bot'                   # a bot account without the [bot] suffix
    if change == 'locked':
        rest.issues[W]['locked'] = True
    with pytest.raises(gh.GuardError):
        _watch_gateway(rest).comment_once(W, f'TIM_OUTSIDE_WATCH:{watch.episode_id(START)}:stale', 'Text.')
    assert rest.repo_writes() == []


def test_server_gateway_still_never_touches_w():
    rest = base.IncidentRest()
    rest.seed(W, 'Außenwache', login=OWNER, labels=['status:external-action'])
    with pytest.raises(gh.GuardError):
        base.gateway(rest).comment_once(W, f'TIM_OUTSIDE_WATCH:{watch.episode_id(START)}:silent', 'Text.')
    with pytest.raises(ValueError):
        gh.IncidentGateway(REPO, TOKEN, reporter_login=BOT, owner_login=None, authority_issue=3, transport=rest)
    with pytest.raises(ValueError):
        gh.IncidentGateway(REPO, TOKEN, reporter_login=BOT, owner_login=None, authority_issue=None,
                           transport=rest, outside_watch=True)
    assert rest.repo_writes() == []


# --- command line: the simulation of design section 16 -------------------------------------------------------------

def test_cli_simulation_unreachable_host_twice_then_normal(world):
    from scripts import tim_checkup

    def cli(*argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tim_checkup.run_watch(host=argv[0], environ=ENV, runner=world.runner, transport=world.net,
                                         clock=world.clock, state_path=world.state_path, tempdir=str(world.tempdir))
        world.clock.now += 300
        line = json.loads(out.getvalue().strip().splitlines()[-1])
        assert line['event'] == 'watch_end' and SSH_SECRET not in out.getvalue()
        return code, line

    assert cli('tim-server-unreachable.invalid')[1]['state'] == 'SILENT'
    code, line = cli('tim-server-unreachable.invalid')
    assert (code, line['actions']) == (0, ['alarm:silent'])
    code, line = cli('tim-server')
    assert (code, line['actions']) == (0, [])                       # recovery needs 2 OK passes in a row
    code, line = cli('tim-server')
    assert (code, line['actions']) == (0, ['recovered'])
    assert [body.split(' -->')[0].rsplit(':', 1)[1] for body in world.comments()] == ['silent', 'recovered']


def test_cli_parses_watch_options(monkeypatch):
    from scripts import tim_checkup
    seen = {}
    monkeypatch.setattr(tim_checkup, 'run_watch', lambda **kwargs: seen.update(kwargs) or 0)
    assert tim_checkup.main(['watch', '--once', '--host', 'tim-server-unreachable.invalid'], environ=ENV) == 0
    assert seen == {'host': 'tim-server-unreachable.invalid', 'environ': ENV}
    assert tim_checkup.main(['watch'], environ=ENV) == 0 and seen['host'] == 'tim-server'


def test_cli_invalid_host_is_refused_before_any_call(world):
    from scripts import tim_checkup
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = tim_checkup.run_watch(host='-oProxyCommand=id', environ=ENV, runner=world.runner, transport=world.net,
                                     clock=world.clock, state_path=world.state_path)
    assert code == 2 and world.runner.calls == [] and not world.state_path.exists()


# --- launchd plist and module hygiene ------------------------------------------------------------------------------

def test_plist_absolute_paths_interval_and_no_secrets():
    with PLIST.open('rb') as handle:
        plist = plistlib.load(handle)
    repo = '/Users/tim/Documents/TIM/tim'
    assert plist['Label'] == 'com.tim.outside-watch'
    assert plist['ProgramArguments'] == [f'{repo}/.venv/bin/python', f'{repo}/scripts/tim_checkup.py', 'watch']
    assert (ROOT / 'scripts/tim_checkup.py').is_file()
    assert plist['WorkingDirectory'] == repo
    assert plist['StartInterval'] == 300 and plist['RunAtLoad'] is True and 'KeepAlive' not in plist
    env = plist['EnvironmentVariables']
    assert set(env) == {'HOME', 'TIM_WATCH_ISSUE', 'TIM_WATCH_APP_ID', 'TIM_WATCH_INSTALLATION_ID',
                        'TIM_WATCH_REPORTER_LOGIN'}
    assert env['HOME'] == '/Users/tim'
    assert plist['StandardOutPath'] == '/Users/tim/Library/Logs/tim-outside-watch.log'
    assert plist['StandardErrorPath'] == '/Users/tim/Library/Logs/tim-outside-watch.err.log'
    for value in [*plist['ProgramArguments'], plist['WorkingDirectory'], plist['StandardOutPath'],
                  plist['StandardErrorPath']]:
        assert value.startswith('/') or value == 'watch'
    text = PLIST.read_text(encoding='utf-8')
    assert not final_scan(text)
    for word in ('TOKEN', 'PASSWORD', 'SECRET', 'PRIVATE', 'BEGIN', 'ghs_', 'ghp_'):
        assert word not in text.upper() if word.isupper() else word not in text
    # placeholders until the owner fills them in: they fail the settings check, so the watch stays quiet (exit 2)
    assert not watch.load_watch_settings(env).complete


def test_watch_module_imports_and_subprocess_hygiene():
    source = (ROOT / 'src/tim_incident/watch.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    modules = {node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    for forbidden in ('bugfixer', 'graph_mcp', 'operational', 'agents'):
        assert not any(forbidden in name for name in modules), forbidden
    assert 'shell=True' not in source and 'os.system' not in source and 'Popen' not in source
    assert 'logging' not in modules and 'print(' not in source


# --- review 3: delivery problems are never silent, no flapping floods, no stale key files ---------------------------

def test_closed_w_notifies_once_and_keeps_the_comment(world):
    world.rest.issues[W]['state'] = 'closed'
    world.server.reachable = False
    world.poll()
    record = world.poll()
    assert (record['delivery'], record['pending'], record['exit_code']) == ('guard_refused', 1, 3)
    assert world.comments() == []
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['SILENT'], watch.NOTIFY_TEXTS['guard_refused']]
    record = world.poll()                                        # still refused: no second notification
    assert (record['delivery'], record['exit_code'], record['actions']) == ('guard_refused', 3, [])
    assert len(world.runner.notifications) == 2
    world.rest.issues[W]['state'] = 'open'                       # the owner reopens W: the alarm arrives late
    record = world.poll()
    assert (record['delivery'], record['posted'], record['exit_code']) == ('ok', 1, 0)
    assert len(world.comments()) == 1 and world.state()['problem'] is None


def test_label_removed_from_w_notifies(world):
    world.rest.set_labels(W, [])
    world.server.new_run(status=1)
    world.poll()
    world.server.new_run(status=1)
    record = world.poll()
    assert record['delivery'] == 'guard_refused' and world.comments() == []
    assert world.runner.notifications[-1] == watch.NOTIFY_TEXTS['guard_refused']


def test_persistent_403_gives_up_the_head_comment_and_notifies(world):
    world.rest.fail[('POST', r'/issues/4/comments$')] = 403
    world.server.reachable = False
    deliveries = [world.poll()['delivery'] for _ in range(4)]
    assert deliveries == ['idle', 'forbidden', 'forbidden', 'forbidden_persistent']
    record = world.records[-1]
    assert (record['pending'], record['exit_code']) == (0, 3)
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['SILENT'], watch.NOTIFY_TEXTS['forbidden_persistent']]


def test_flapping_ssh_keeps_one_episode(world):
    for _ in range(8):                                           # 2 h: fail, fail, ok, over and over
        for reachable in (False, False, True):
            world.server.reachable = reachable
            if reachable:
                world.server.new_run()                           # the checkup keeps running on the server
            world.poll()
    assert len(world.comments()) == 1 and world.runner.notifications == [watch.NOTIFY_TEXTS['SILENT']]
    world.server.reachable = True
    world.server.new_run()
    world.poll()                                                 # the second OK in a row: one recovery
    assert len(world.comments()) == 2 and world.runner.notifications[-1] == watch.NOTIFY_TEXTS['recovered']


def test_flapping_episodes_are_capped_per_day(world):
    for _ in range(12):                                          # 4 h: fail, fail, ok, ok: a new episode each hour/3
        for reachable in (False, False, True, True):
            world.server.reachable = reachable
            if reachable:
                world.server.new_run()                           # the checkup keeps running on the server
            world.poll()
    limit = watch.MAX_EPISODES_PER_DAY
    alarms = [c for c in world.comments() if ':silent -->' in c]
    assert len(alarms) == limit and len(world.comments()) == 2 * limit
    assert 'Flattern' in alarms[-1] and all('Flattern' not in c for c in alarms[:-1])
    assert len(world.runner.notifications) == 2 * limit
    actions = [a for r in world.records for a in r['actions']]
    assert actions.count('alarm:silent:muted') == actions.count('recovered:muted') == 12 - limit
    world.clock.now += 24 * 3600                                 # the window rolls on: alarms comment again
    for reachable in (False, False):
        world.server.reachable = reachable
        world.poll()
    assert len(world.comments()) == 2 * limit + 1


def test_failed_runs_with_unseen_runs_between_are_not_in_a_row(world):
    runs = {'last_exit': None, 'failed': []}
    first = _units(show(START - 60, START - 30, result='exit-code', status=3))
    assert watch.decide(first, runs, START).state == watch.OK
    later = START + 3 * 3600                                      # Mac asleep: 11 runs nobody saw
    second = _units(show(later - 60, later - 30, result='exit-code', status=3))
    assert watch.decide(second, runs, later).state == watch.OK and len(runs['failed']) == 1
    world.server.new_run(status=1)
    world.poll()
    world.clock.now += 3 * 3600
    world.server.new_run(status=1)
    record = world.poll()
    assert record['state'] == 'OK' and world.comments() == [] and world.runner.notifications == []


@pytest.mark.parametrize('failure', ['keychain_locked', 'openssl_failed', 'token_404'])
def test_transient_key_and_token_failures_keep_the_comment(world, failure):
    if failure == 'keychain_locked':
        world.runner.keychain_code = 36                          # errSecInteractionNotAllowed and the like
        expected = watch.KEY_UNAVAILABLE
    elif failure == 'openssl_failed':
        world.runner.openssl_code = 1
        expected = watch.KEY_UNAVAILABLE
    else:
        world.rest.fail[('POST', r'/access_tokens$')] = 404
        expected = 'token_invalid'
    world.server.reachable = False
    world.poll()
    record = world.poll()
    assert (record['delivery'], record['pending'], record['exit_code']) == (expected, 1, 3)
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['SILENT'], watch.NOTIFY_TEXTS[expected]]
    world.poll()
    assert len(world.runner.notifications) == 2                  # notified once while it lasts
    assert list(world.tempdir.iterdir()) == []                   # no key file left behind
    world.runner.keychain_code, world.runner.openssl_code = 0, 0
    world.rest.fail.clear()
    record = world.poll()
    assert (record['delivery'], record['posted']) == ('ok', 1) and len(world.comments()) == 1


def test_stale_key_directory_of_a_killed_pass_is_removed(world, tmp_path):
    import os
    old = world.tempdir / 'tim-watch-old1'
    old.mkdir(mode=0o700)
    (old / 'key.pem').write_text(KEY)
    outside = tmp_path / 'outside.pem'
    outside.write_text('keep')
    linked = world.tempdir / 'tim-watch-old2'
    linked.mkdir(mode=0o700)
    (linked / 'key.pem').symlink_to(outside)
    fresh = world.tempdir / 'tim-watch-fresh'                   # a pass running right now: left alone
    fresh.mkdir(mode=0o700)
    other = world.tempdir / 'unrelated'
    other.mkdir()
    for folder in (old, linked, other):
        os.utime(folder, (0, 0))
    world.poll()
    assert sorted(p.name for p in world.tempdir.iterdir()) == ['tim-watch-fresh', 'unrelated']
    assert outside.read_text() == 'keep'                         # the symlink was removed, never followed


def test_unknown_for_two_hours_notifies_once(world):
    world.net.offline = True
    for _ in range(watch.UNKNOWN_NOTIFY_AFTER + 6):
        record = world.poll()
        assert record['exit_code'] == 0
    assert world.runner.notifications == [watch.NOTIFY_TEXTS['offline_long']]
    assert [r['actions'] for r in world.records].count(['notify:offline_long']) == 1
    world.net.offline = False
    world.poll()
    assert world.state()['unknown_passes'] == 0


def test_sigterm_ends_the_pass_through_systemexit():
    from scripts import tim_checkup
    with pytest.raises(SystemExit) as raised:
        tim_checkup._exit_on_sigterm(15, None)
    assert raised.value.code == 143
