"""Outside watch from the Mac (design D, PR-3). OBSERVE only.

One pass, started by launchd every 300 s (`ops/launchd/com.tim.outside-watch.plist`):

1. Is the Mac online? `GET https://api.github.com/zen`, 5 s. Any HTTP answer counts as online. If not: UNKNOWN, no
   alarm, the deviation streak is neither raised nor reset.
2. One ssh call with a fixed argv (`ssh_argv`). The key may only run the forced command on the server, which prints
   `systemctl show --timestamp=unix` for tim-checkup.service and tim-server-health.service. Its stdout is parsed
   here and never logged; its stderr is dropped.
3. Decision (`decide`), counted per checkup run (different `ExecMainExitTimestamp`), not per poll:
   SILENT (ssh fails or the answer is unusable) > STALE (checkup end older than 35 min or health end older than
   5 min) > IMPAIRED (2 different runs in a row with Result != success or ExecMainStatus != 0; "in a row" only when
   the second started at most CONSECUTIVE_GAP after the first ended) > OK.
4. Alarm after 2 deviations in a row (IMPAIRED already stands for 2 failed runs): exactly one comment per episode on
   the watch issue W via `IncidentGateway.comment_once` with tag `TIM_OUTSIDE_WATCH:<episode>:<kind>`, one recovery
   comment with the duration after 2 OK passes in a row, and always a macOS notification with a fixed text. At most
   MAX_EPISODES_PER_DAY episodes in 24 h comment and notify; later ones are muted (log only), the last comment says so.
   Delivery problems are never silent: HTTP 401 or key 2 missing from the keychain drop the queue and notify; a W
   that is closed, locked or lost its label, a locked keychain, a failed signature or a refused token keep the queue
   and notify once; HTTP 403 three passes in a row gives up the head comment and notifies. 2 h of UNKNOWN notify once.
5. State: `~/Library/Application Support/TIM Outside Watch/state.json` (0600). Key 2 comes from the login keychain
   (`security find-generic-password ... -w`, base64 PEM). `github_app.build_jwt` needs a regular file (it checks
   S_ISREG before openssl signs), so a pipe is not possible: the key goes to a 0600 file in a fresh 0700 temp
   directory that is deleted right after openssl returned, before the token request is sent. Directories a killed
   pass left behind are removed at the start of the next pass (`sweep_stale_keys`).

Every subprocess (ssh, security, openssl, osascript) runs without a shell through one injectable runner. The output
line `{"event": "watch_end", ...}` holds states, ages and actions only: never ssh output, key, JWT or token.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from src.task_governance.github_gateway import _NotSent

from . import github_app
from .github import (_WATCH_TAG, GuardError, HTTPStatusError, IncidentGateway, NetworkDown, RepositoryNotVisible,
                     incident_transport)
from .policy import _BOT_LOGIN, _NUMBER
from .redaction import final_scan

UTC = timezone.utc

SILENT, STALE, IMPAIRED, OK, UNKNOWN = 'SILENT', 'STALE', 'IMPAIRED', 'OK', 'UNKNOWN'
DEVIATIONS = (SILENT, STALE, IMPAIRED)

DEFAULT_HOST = 'tim-server'
SSH_KEY = '.ssh/tim_watch_ed25519'
SSH_TIMEOUT = 40.0                      # ConnectTimeout 10 + ServerAlive 2 x 5 + the answer, with room
SSH_MAX_OUTPUT = 64 * 1024
ONLINE_URL = 'https://api.github.com/zen'
ONLINE_TIMEOUT = 5.0
UNITS = ('tim-checkup.service', 'tim-server-health.service')
CHECKUP_UNIT, HEALTH_UNIT = UNITS
CHECKUP_MAX_AGE = 35 * 60
HEALTH_MAX_AGE = 5 * 60
ALARM_AFTER = 2                         # deviations in a row before the alarm
RECOVER_AFTER = 2                       # OK passes in a row before the recovery (no flapping episodes)
MAX_EPISODES_PER_DAY = 6                # new episodes per 24 h that comment and notify; later ones are muted
CONSECUTIVE_GAP = 900 + 60              # tim-checkup.timer OnUnitActiveSec plus slack: two failed runs further
                                        # apart had at least one unseen run in between and are not "in a row"
FORBIDDEN_LIMIT = 3                     # passes with HTTP 403 on the same comment before it is given up
UNKNOWN_NOTIFY_AFTER = 24               # UNKNOWN passes in a row (2 h awake) before one notification
STALE_KEY_AGE = 120                     # seconds: leftover tim-watch-* key directories older than this are removed
KEYCHAIN_NOT_FOUND = 44                 # `security` exit code errSecItemNotFound
KEY_UNAVAILABLE = 'key_unavailable'     # keychain locked, key unreadable or openssl failed: may heal, queue kept
EXIT_REPORTING_DISTURBED = 3            # tim-checkup exit code "Melden gestört"
MAX_PENDING = 20
STATE_DIR = Path('Library/Application Support/TIM Outside Watch')
KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT = 'tim-outside-watch', 'tim-reporter'
KEYCHAIN_ARGV = ('security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT, '-w')
KEYCHAIN_TIMEOUT = 10.0
NOTIFY_TIMEOUT = 10.0
NOTIFY_TITLE = 'TIM Außenwache'
SUBPROCESS_PATH = '/usr/bin:/bin:/usr/sbin:/sbin'

# Fixed notification texts (German, macOS). The argv carries them as data: `on run argv` never parses them as script.
NOTIFY_TEXTS = {
    SILENT: 'tim-server antwortet nicht per ssh. Details im Außenwache-Issue.',
    STALE: 'Checkup oder tim-server-health läuft nicht mehr. Details im Außenwache-Issue.',
    'impaired_reporting': 'Melden gestört: der Checkup erreicht GitHub nicht. Details im Außenwache-Issue.',
    IMPAIRED: 'Checkup fehlgeschlagen. Details im Außenwache-Issue.',
    'recovered': 'tim-server wieder in Ordnung.',
    'unauthorized': 'GitHub lehnt den Schlüssel der Außenwache ab (HTTP 401). Kein Kommentar möglich.',
    'key_missing': 'Schlüssel der Außenwache fehlt im Schlüsselbund. Kein Kommentar möglich.',
    'token_invalid': 'GitHub verweigert der Außenwache das Token: App-ID, Installation und Repo prüfen. '
                     'Kommentare warten.',
    KEY_UNAVAILABLE: 'Schlüssel der Außenwache nicht nutzbar (Schlüsselbund gesperrt oder Signatur gescheitert). '
                     'Kommentare warten.',
    'guard_refused': 'Außenwache-Issue W nicht nutzbar (geschlossen, gesperrt oder ohne Label '
                     'status:external-action). Kommentare warten.',
    'forbidden_persistent': 'GitHub verweigert der Außenwache das Schreiben (HTTP 403, dreimal in Folge). '
                            'Ein Kommentar wurde verworfen.',
    'offline_long': 'Die Außenwache erreicht GitHub seit über 2 Stunden nicht (Netz, Proxy oder Zertifikate der '
                    'Python-Umgebung prüfen). tim-server wird so nicht überwacht.',
}
# Delivery outcomes that notify and end with exit 3. DROP_OUTCOMES discard the queue (will not heal by waiting) and
# notify every time; the others keep the queue and notify once until a delivery succeeds again.
DROP_OUTCOMES = ('unauthorized', 'key_missing', 'forbidden_persistent')
NOTIFY_ONLY = DROP_OUTCOMES + ('token_invalid', KEY_UNAVAILABLE, 'guard_refused')
NOTIFY_SCRIPT = ('on run argv', 'display notification (item 1 of argv) with title (item 2 of argv)', 'end run')

_HOST = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$')
_TIMESTAMP = re.compile(r'^@([0-9]{1,12})$')
_RESULT = re.compile(r'^[a-z][a-z-]{0,39}$')
_STATUS = re.compile(r'^-?[0-9]{1,6}$')
_LINE = re.compile(r'^([A-Za-z]{1,40})=(.{0,200})$')


class WatchError(Exception):
    """A fixed text; never subprocess output or a secret."""


@dataclass(frozen=True)
class WatchSettings:
    issue: int | None
    app_id: int | None
    installation_id: int | None
    reporter_login: str | None
    home: str | None
    problems: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.problems


def load_watch_settings(environ: Mapping[str, str]) -> WatchSettings:
    """The four TIM_WATCH_* values and HOME. Problems name the variable, never its value."""
    problems: list[str] = []

    def number(name: str) -> int | None:
        raw = (environ.get(name) or '').strip()
        if not raw:
            problems.append(f'{name} missing')
            return None
        if not _NUMBER.match(raw):
            problems.append(f'{name} invalid')
            return None
        return int(raw)

    issue = number('TIM_WATCH_ISSUE')
    app_id = number('TIM_WATCH_APP_ID')
    installation_id = number('TIM_WATCH_INSTALLATION_ID')
    login = (environ.get('TIM_WATCH_REPORTER_LOGIN') or '').strip()
    if not login:
        problems.append('TIM_WATCH_REPORTER_LOGIN missing')
    elif not _BOT_LOGIN.match(login):
        problems.append('TIM_WATCH_REPORTER_LOGIN invalid')
    home = (environ.get('HOME') or '').strip()
    if not home.startswith('/'):
        problems.append('HOME missing')
    return WatchSettings(issue, app_id, installation_id, login if _BOT_LOGIN.match(login or '') else None,
                         home if home.startswith('/') else None, tuple(problems))


# --- subprocesses --------------------------------------------------------------------------------------------------

Runner = Callable[..., subprocess.CompletedProcess]


def default_runner(home: str) -> Runner:
    """No shell, output captured, minimal environment (HOME for ~/.ssh/config, known_hosts and the keychain)."""
    env = {'PATH': SUBPROCESS_PATH, 'HOME': home, 'LC_ALL': 'C'}

    def run(argv, *, input=None, timeout):
        return subprocess.run(list(argv), input=input, capture_output=True, timeout=timeout, check=False, env=env,
                              stdin=None if input is not None else subprocess.DEVNULL)
    return run


def valid_host(host) -> bool:
    return isinstance(host, str) and bool(_HOST.match(host)) and '..' not in host


def ssh_argv(home: str, host: str = DEFAULT_HOST) -> list[str]:
    """The fixed ssh call of design D.2. No remote command: the server's forced command decides what runs."""
    if not valid_host(host):
        raise WatchError('host invalid')
    # ControlMaster/ControlPath: never share a multiplexed connection with the owner's own `ssh tim-server`
    # (it would bypass the forced-command key, or hand the owner's next login to the forced command).
    return ['ssh', '-T', '-i', str(Path(home) / SSH_KEY), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
            '-o', 'RequestTTY=no', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=2', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'ClearAllForwardings=yes', host]


def notify(runner: Runner, key: str) -> bool:
    """One macOS notification with a fixed text, through osascript argv (no shell, no string building)."""
    text = NOTIFY_TEXTS[key]
    argv = ['osascript']
    for line in NOTIFY_SCRIPT:
        argv += ['-e', line]
    argv += [text, NOTIFY_TITLE]
    try:
        result = runner(argv, timeout=NOTIFY_TIMEOUT)
    except Exception:
        return False
    return getattr(result, 'returncode', 1) == 0


# --- systemctl show ------------------------------------------------------------------------------------------------

def _timestamp(value: str | None) -> int | None:
    match = _TIMESTAMP.match(value or '')
    return int(match.group(1)) if match and int(match.group(1)) > 0 else None


def parse_show(text: str) -> dict[str, dict]:
    """`systemctl show --timestamp=unix --property=Id,... A B`: blocks separated by blank lines, `Key=value` lines.
    Returns {unit id: {'active', 'result', 'status', 'start', 'exit'}} for the two watched units only. Unknown or
    malformed lines are skipped; values are validated, never copied as free text."""
    units: dict[str, dict] = {}
    for block in re.split(r'\n\s*\n', text or ''):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            match = _LINE.match(line.strip())
            if match:
                fields.setdefault(match.group(1), match.group(2).strip())
        unit = fields.get('Id')
        if unit not in UNITS or unit in units:
            continue
        result = fields.get('Result', '')
        status = fields.get('ExecMainStatus', '')
        active = fields.get('ActiveState', '')
        units[unit] = {
            'active': active if _RESULT.match(active) else None,
            'result': result if _RESULT.match(result) else None,
            'status': int(status) if _STATUS.match(status) else None,
            'start': _timestamp(fields.get('ExecMainStartTimestamp')),
            'exit': _timestamp(fields.get('ExecMainExitTimestamp')),
        }
    return units


def probe(runner: Runner, home: str, host: str) -> dict[str, dict] | None:
    """The ssh call; None when it fails or the answer misses a unit. stdout stays in this function."""
    try:
        result = runner(ssh_argv(home, host), timeout=SSH_TIMEOUT)
    except Exception:
        return None
    if getattr(result, 'returncode', 1) != 0:
        return None
    raw = getattr(result, 'stdout', b'') or b''
    if not isinstance(raw, bytes) or len(raw) > SSH_MAX_OUTPUT:
        return None
    units = parse_show(raw.decode('utf-8', 'replace'))
    return units if all(unit in units for unit in UNITS) else None


# --- decision ------------------------------------------------------------------------------------------------------

@dataclass
class Decision:
    state: str
    detail: dict = field(default_factory=dict)


def _running(unit: dict) -> bool:
    return unit.get('active') in ('activating', 'active', 'reloading', 'deactivating')


def _last_seen(unit: dict) -> int | None:
    """End of the last run; for a run in progress its start (systemd clears the exit time at start)."""
    if _running(unit) and unit.get('start'):
        return max(unit['start'], unit.get('exit') or 0)
    return unit.get('exit')


def _failed(unit: dict) -> bool:
    return unit.get('result') != 'success' or unit.get('status') != 0


def decide(units: dict[str, dict] | None, runs: dict, now: float) -> Decision:
    """Pure decision of design D.3. `runs` ({'last_exit', 'failed': [[exit, status, result], ...]}) is updated in
    place: a run counts once, by its ExecMainExitTimestamp. Two failed runs count as "in a row" only if the second
    started at most CONSECUTIVE_GAP after the first ended (Mac asleep or ssh down: unseen runs may lie between)."""
    if units is None:
        return Decision(SILENT, {'ssh': 'failed'})
    checkup, health = units[CHECKUP_UNIT], units[HEALTH_UNIT]
    exit_ts = checkup.get('exit')
    if exit_ts and exit_ts != runs.get('last_exit') and not _running(checkup):
        runs['last_exit'] = exit_ts
        if _failed(checkup):
            failed = list(runs.get('failed') or [])
            begun = checkup.get('start') or exit_ts
            if failed and not (isinstance(failed[-1][0], int) and 0 <= begun - failed[-1][0] <= CONSECUTIVE_GAP):
                failed = []                         # runs ended in between that the watch never saw: not in a row
            failed.append([exit_ts, checkup.get('status'), checkup.get('result')])
            runs['failed'] = failed[-ALARM_AFTER:]
        else:
            runs['failed'] = []
    checkup_seen, health_seen = _last_seen(checkup), _last_seen(health)
    checkup_age = None if checkup_seen is None else max(0, int(now - checkup_seen))
    health_age = None if health_seen is None else max(0, int(now - health_seen))
    detail = {'checkup_age_s': checkup_age, 'health_age_s': health_age}
    if checkup_age is None or checkup_age > CHECKUP_MAX_AGE or health_age is None or health_age > HEALTH_MAX_AGE:
        return Decision(STALE, detail)
    failed = runs.get('failed') or []
    if len(failed) >= ALARM_AFTER:
        last = failed[-1]
        detail.update(status=last[1], result=last[2],
                      reporting=last[1] == EXIT_REPORTING_DISTURBED)
        return Decision(IMPAIRED, detail)
    return Decision(OK, detail)


# --- texts (German, fixed) -----------------------------------------------------------------------------------------

def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime('%Y-%m-%d %H:%M UTC')


def _minutes(seconds) -> str:
    if not isinstance(seconds, int):
        return 'unbekannt'
    minutes = seconds // 60
    return f'{minutes // 60} h {minutes % 60} min' if minutes >= 60 else f'{minutes} min'


def episode_id(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime('%Y%m%dT%H%M%SZ')


def watch_tag(episode: str, kind: str) -> str:
    return f'TIM_OUTSIDE_WATCH:{episode}:{kind}'


def impaired_text(detail: dict) -> str:
    if detail.get('reporting'):
        return 'Melden gestört'
    status = detail.get('status')
    shown = str(status) if isinstance(status, int) and status != 0 else (detail.get('result') or 'unbekannt')
    return f'Checkup fehlgeschlagen (Status {shown})'


def alarm_text(decision: Decision, started: float) -> str:
    head = f'**Außenwache vom Mac: {decision.state}** seit {_utc(started)} (2 Abweichungen in Folge).'
    if decision.state == SILENT:
        body = ('tim-server antwortet nicht per ssh. Möglich: Server aus, Netz am Standort weg, sshd gestört. '
                'Der Checkup auf dem Server kann in dieser Lage nichts melden.')
    elif decision.state == STALE:
        body = (f"Der Checkup oder tim-server-health läuft nicht mehr: letztes Ende tim-checkup vor "
                f"{_minutes(decision.detail.get('checkup_age_s'))} (Grenze 35 min), tim-server-health vor "
                f"{_minutes(decision.detail.get('health_age_s'))} (Grenze 5 min).")
    else:
        body = f'{impaired_text(decision.detail)}: zwei Checkup-Läufe in Folge sind nicht sauber beendet.'
    return (f'{head}\n\n{body}\n\nPrüfen auf dem Server: `systemctl status tim-checkup.service '
            f'tim-server-health.service` und `sudo journalctl -u tim-checkup -n 5 -o cat`.')


def recovery_text(episode: str, kind: str, seconds: int) -> str:
    return (f'**Außenwache vom Mac: wieder in Ordnung.** Episode {episode} ({kind}) ist nach '
            f'{_minutes(seconds)} vorbei.')


def _notify_key(decision: Decision) -> str:
    if decision.state == IMPAIRED and decision.detail.get('reporting'):
        return 'impaired_reporting'
    return decision.state


# --- state ---------------------------------------------------------------------------------------------------------

def empty_state() -> dict:
    return {'version': 1, 'streak': 0, 'deviation_since': None, 'runs': {'last_exit': None, 'failed': []},
            'episode': None, 'pending': [], 'last': None, 'ok_streak': 0, 'ok_since': None, 'opened': [],
            'problem': None, 'forbidden': 0, 'unknown_passes': 0}


def load_state(path: Path) -> tuple[dict, str]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return empty_state(), 'new'
    except (OSError, ValueError, UnicodeDecodeError):
        return empty_state(), 'reset'
    base = empty_state()
    if not isinstance(data, dict) or data.get('version') != 1:
        return base, 'reset'
    runs, pending, episode = data.get('runs'), data.get('pending'), data.get('episode')
    streak, since = data.get('streak'), data.get('deviation_since')
    if not (isinstance(runs, dict) and isinstance(runs.get('failed', []), list) and isinstance(pending, list)
            and all(isinstance(item, dict) and isinstance(item.get('tag'), str) and isinstance(item.get('text'), str)
                    for item in pending)
            and (episode is None or (isinstance(episode, dict) and isinstance(episode.get('id'), str)
                                     and isinstance(episode.get('kind'), str)
                                     and isinstance(episode.get('started'), (int, float))
                                     and isinstance(episode.get('muted', False), bool)))
            and type(streak) is int and streak >= 0 and (since is None or isinstance(since, (int, float)))):
        return base, 'reset'
    base.update(streak=streak, deviation_since=since, episode=episode, pending=pending[-MAX_PENDING:],
                runs={'last_exit': runs.get('last_exit') if isinstance(runs.get('last_exit'), int) else None,
                      'failed': [item for item in runs.get('failed', []) if isinstance(item, list) and len(item) == 3]},
                last=data.get('last') if isinstance(data.get('last'), dict) else None)
    for key in ('ok_streak', 'forbidden', 'unknown_passes'):
        if type(data.get(key)) is int and data[key] >= 0:
            base[key] = data[key]
    if isinstance(data.get('ok_since'), (int, float)):
        base['ok_since'] = data['ok_since']
    if isinstance(data.get('opened'), list):
        base['opened'] = [ts for ts in data['opened'] if isinstance(ts, (int, float))][-MAX_EPISODES_PER_DAY:]
    if data.get('problem') in NOTIFY_TEXTS:
        base['problem'] = data['problem']
    return base, 'ok'


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        os.write(fd, json.dumps(state, sort_keys=True).encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


# --- key 2 and token -----------------------------------------------------------------------------------------------

def keychain_key(runner: Runner) -> bytes:
    """PEM bytes of key 2 from the login keychain (stored base64 without newlines). Fixed errors only.
    Only `security` exit 44 (item not found) is KEY_MISSING; a locked keychain, a timeout or a broken entry is
    KEY_UNAVAILABLE, which keeps the queued comments."""
    try:
        result = runner(list(KEYCHAIN_ARGV), timeout=KEYCHAIN_TIMEOUT)
    except Exception:
        raise github_app.AppTokenError(KEY_UNAVAILABLE, 'keychain not readable') from None
    code = getattr(result, 'returncode', 1)
    if code == KEYCHAIN_NOT_FOUND:
        raise github_app.AppTokenError(github_app.KEY_MISSING, 'key 2 missing in the keychain')
    if code != 0 or not isinstance(getattr(result, 'stdout', None), bytes):
        raise github_app.AppTokenError(KEY_UNAVAILABLE, 'keychain not readable')
    try:
        pem = base64.b64decode(result.stdout.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise github_app.AppTokenError(KEY_UNAVAILABLE, 'key 2 is not base64') from None
    if not pem.lstrip().startswith(b'-----BEGIN') or len(pem) > github_app.MAX_KEY_BYTES:
        raise github_app.AppTokenError(KEY_UNAVAILABLE, 'key 2 is not a PEM key')
    return pem


def mint_token(settings: WatchSettings, *, runner: Runner, transport, now: int, repository_name: str,
               tempdir: str | None = None) -> str:
    """Installation token from key 2. The PEM sits in a 0600 file inside a fresh 0700 directory only until openssl
    returned (the openssl runner deletes it at once), and in any case is removed before this function returns."""
    pem = keychain_key(runner)
    directory = tempfile.mkdtemp(prefix='tim-watch-', dir=tempdir)
    path = os.path.join(directory, 'key.pem')

    def remove():
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            os.write(fd, pem)
        finally:
            os.close(fd)
        del pem

        def openssl(argv, *, input, timeout):
            try:
                return runner(argv, input=input, timeout=timeout)
            finally:
                remove()                                    # deleted at once, before the token request

        try:
            return github_app.mint_installation_token(settings.app_id, settings.installation_id, path,
                                                      runner=openssl, transport=transport, now=now,
                                                      repository_name=repository_name)
        except github_app.AppTokenError as error:
            if error.kind == github_app.KEY_MISSING:     # the key came from the keychain: openssl failed
                raise github_app.AppTokenError(KEY_UNAVAILABLE, 'signing with openssl failed') from None
            raise
    finally:
        remove()
        try:
            os.rmdir(directory)
        except OSError:
            pass


def sweep_stale_keys(tempdir: str | None, *, max_age: float = STALE_KEY_AGE) -> int:
    """Remove key files a killed pass left behind (SIGTERM from launchd skips `finally`): `tim-watch-*` directories
    of this user in `tempdir`, older than `max_age`, no symlinks followed. Returns the number of directories removed."""
    if not tempdir:
        return 0
    removed = 0
    try:
        entries = list(os.scandir(tempdir))
    except OSError:
        return 0
    limit = time.time() - max_age
    for entry in entries:
        if not entry.name.startswith('tim-watch-'):
            continue
        try:
            info = os.lstat(entry.path)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mtime > limit:
                continue
            for inner in os.scandir(entry.path):
                inner_info = os.lstat(inner.path)
                if inner.name == 'key.pem' and (stat.S_ISREG(inner_info.st_mode) or stat.S_ISLNK(inner_info.st_mode)):
                    os.unlink(inner.path)               # a symlink is removed itself, never followed
            os.rmdir(entry.path)
            removed += 1
        except OSError:
            continue
    return removed


def online(transport) -> bool:
    """Any HTTP answer from api.github.com within 5 s means the Mac is online."""
    try:
        status, _ = transport('GET', ONLINE_URL, {'User-Agent': 'tim-outside-watch',
                                                  'Accept': 'application/vnd.github+json'}, None, ONLINE_TIMEOUT)
    except _NotSent:
        return False
    except Exception:
        return False
    return isinstance(status, int) and 100 <= status < 600


# --- one pass ------------------------------------------------------------------------------------------------------

def _queue(state: dict, tag: str, text: str) -> None:
    if final_scan(text):
        raise WatchError('fixed text failed the final scan')        # cannot happen with the fixed texts
    if any(item.get('tag') == tag for item in state['pending']):
        return
    state['pending'] = (state['pending'] + [{'tag': tag, 'text': text}])[-MAX_PENDING:]


def _forbidden(state: dict, posted: int) -> tuple[str, int]:
    """HTTP 403 on the token or the comment. Retried on the next passes; after FORBIDDEN_LIMIT passes in a row the
    head entry is given up (and the caller notifies), so one refused comment cannot block every later alarm."""
    state['forbidden'] = int(state.get('forbidden') or 0) + 1
    if state['forbidden'] >= FORBIDDEN_LIMIT:
        state['forbidden'] = 0
        if state['pending']:
            state['pending'].pop(0)
        return 'forbidden_persistent', posted
    return 'forbidden', posted


def _deliver(state: dict, settings: WatchSettings, *, runner, transport, now: int, repository: str,
             tempdir: str | None) -> tuple[str, int]:
    """Post the queued comments in order. Returns (delivery, posted). Only a confirmed HTTP 401 or a key 2 missing
    from the keychain drops the queue; a refused W, a locked keychain, a failed signature or a refused token keep it
    for the next pass (bounded by MAX_PENDING), the caller notifies once. Network trouble keeps it silently."""
    if not state['pending']:
        return 'idle', 0
    name = repository.split('/', 1)[1]
    try:
        token = mint_token(settings, runner=runner, transport=transport, now=now, repository_name=name,
                           tempdir=tempdir)
    except github_app.AppTokenError as error:
        if error.kind == github_app.KEY_MISSING:
            state['pending'] = []
            return 'key_missing', 0
        if error.kind == github_app.TOKEN_INVALID:
            if '401' in str(error):
                state['pending'] = []                       # GitHub rejected the key: will not heal by waiting
                return 'unauthorized', 0
            return 'token_invalid', 0
        if error.kind == github_app.FORBIDDEN:
            return _forbidden(state, 0)
        return error.kind, 0
    gateway = IncidentGateway(repository, token, reporter_login=settings.reporter_login, owner_login=None,
                              authority_issue=None, watch_issue=settings.issue, transport=transport,
                              outside_watch=True)
    del token
    posted = 0
    while state['pending']:
        item = state['pending'][0]
        if final_scan(item['text']) or not _WATCH_TAG.match(item['tag']):
            state['pending'].pop(0)                          # a broken entry (state file edited) never heals
            continue
        try:
            if gateway.comment_once(settings.issue, item['tag'], item['text']):
                posted += 1
        except HTTPStatusError as error:
            if error.status == 401:
                state['pending'] = []
                return 'unauthorized', posted
            if error.status == 403:
                return _forbidden(state, posted)
            return 'rate_limited', posted
        except GuardError:
            return 'guard_refused', posted                   # W not usable now: kept until W is fixed
        except (NetworkDown, RepositoryNotVisible):
            return 'network_down', posted
        except Exception:
            return 'network_down', posted
        state['pending'].pop(0)
        state['forbidden'] = 0
    return 'ok', posted


def run_once(settings: WatchSettings, *, host: str = DEFAULT_HOST, repository: str, runner: Runner | None = None,
             transport=None, clock=time.time, state_path: Path | None = None, tempdir: str | None = None) -> dict:
    """One pass of the outside watch. Returns the watch_end record (exit_code inside); never raises for GitHub,
    ssh or keychain trouble."""
    if not settings.complete:
        return {'event': 'watch_end', 'state': UNKNOWN, 'exit_code': 2, 'problems': list(settings.problems)}
    if not valid_host(host):
        return {'event': 'watch_end', 'state': UNKNOWN, 'exit_code': 2, 'problems': ['host invalid']}
    runner = runner or default_runner(settings.home)
    transport = transport or incident_transport
    state_path = state_path or Path(settings.home) / STATE_DIR / 'state.json'
    if tempdir is None:                 # launchd sets no TMPDIR: keep the key file under the private state directory
        try:
            state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            tempdir = str(state_path.parent)
        except OSError:
            tempdir = None
    sweep_stale_keys(tempdir)
    now = float(clock())
    state, state_status = load_state(state_path)
    actions: list[str] = []
    record = {'event': 'watch_end', 'host': host, 'state_file': state_status}

    if not online(transport):
        decision = Decision(UNKNOWN, {'online': False})
    else:
        decision = decide(probe(runner, settings.home, host), state['runs'], now)

    if decision.state == UNKNOWN:
        # The Mac cannot reach GitHub: nothing counts either way, the queue waits. A watch blind for 2 h of awake
        # passes (no network, a proxy, a CA problem of the venv Python) says so once.
        state['unknown_passes'] = int(state.get('unknown_passes') or 0) + 1
        if state['unknown_passes'] == UNKNOWN_NOTIFY_AFTER:
            notify(runner, 'offline_long')
            actions.append('notify:offline_long')
    else:
        state['unknown_passes'] = 0

    if decision.state in DEVIATIONS:
        state['ok_streak'], state['ok_since'] = 0, None
        state['streak'] = int(state.get('streak') or 0) + 1
        if not state.get('deviation_since'):
            state['deviation_since'] = now
        episode = state.get('episode')
        if episode is None and (decision.state == IMPAIRED or state['streak'] >= ALARM_AFTER):
            started = float(state['deviation_since'])
            opened = [ts for ts in state.get('opened') or [] if 0 <= now - ts < 86400]
            muted = len(opened) >= MAX_EPISODES_PER_DAY
            episode = {'id': episode_id(started), 'kind': decision.state.lower(), 'started': started, 'muted': muted}
            state['episode'] = episode
            if muted:                                   # flapping: the cap was announced with the last comment
                actions.append(f"alarm:{episode['kind']}:muted")
            else:
                opened.append(now)
                text = alarm_text(decision, started)
                if len(opened) == MAX_EPISODES_PER_DAY:
                    text += (f'\n\nFlattern: das ist die {MAX_EPISODES_PER_DAY}. Episode in 24 h. Weitere Episoden '
                             f'bis {_utc(opened[0] + 86400)} stehen nur im Log, ohne Kommentar und Mitteilung.')
                _queue(state, watch_tag(episode['id'], episode['kind']), text)
                notify(runner, _notify_key(decision))
                actions.append(f"alarm:{episode['kind']}")
            state['opened'] = opened
    elif decision.state == OK:
        state['streak'] = 0
        state['deviation_since'] = None
        episode = state.get('episode')
        if episode is None:
            state['ok_streak'], state['ok_since'] = 0, None
        else:
            state['ok_streak'] = int(state.get('ok_streak') or 0) + 1
            if state.get('ok_since') is None:
                state['ok_since'] = now
            if state['ok_streak'] >= RECOVER_AFTER:     # hysteresis: one OK pass between failures is no recovery
                duration = max(0, int(float(state['ok_since']) - float(episode['started'])))
                if episode.get('muted'):
                    actions.append('recovered:muted')
                else:
                    _queue(state, watch_tag(episode['id'], 'recovered'),
                           recovery_text(episode['id'], episode['kind'], duration))
                    notify(runner, 'recovered')
                    actions.append('recovered')
                record['duration_s'] = duration
                state['episode'] = None
                state['ok_streak'], state['ok_since'] = 0, None

    delivery, posted = ('skipped', 0) if decision.state == UNKNOWN else _deliver(
        state, settings, runner=runner, transport=transport, now=int(now), repository=repository, tempdir=tempdir)
    if delivery in NOTIFY_ONLY:
        if delivery in DROP_OUTCOMES or state.get('problem') != delivery:
            notify(runner, delivery)
            actions.append(f'notify:{delivery}')
        state['problem'] = delivery
    elif delivery == 'ok':
        state['problem'] = None
    state['last'] = {'at': now, 'state': decision.state}
    try:
        save_state(state_path, state)
        saved = True
    except OSError:
        saved = False
    record.update(state=decision.state, streak=state['streak'],
                  episode=(state['episode'] or {}).get('id'), actions=actions, delivery=delivery, posted=posted,
                  pending=len(state['pending']), saved=saved,
                  **{key: value for key, value in decision.detail.items()
                     if key in ('checkup_age_s', 'health_age_s', 'status', 'online', 'ssh')})
    record['exit_code'] = 3 if delivery in NOTIFY_ONLY else (0 if saved else 1)
    return record
