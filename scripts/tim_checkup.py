#!/usr/bin/env python3
"""TIM checkup entry point (design parts A and B, PR-1). OBSERVE only.

    tim_checkup.py run                  one checkup run (tim-checkup.service, user tim)
    tim_checkup.py status [--since 24h] what the checkup knows; reads files only, never writes

`run` loads config/tim_checkup.json and the TIM_CHECKUP_* settings from the environment, builds the incident
reporter and calls `src.tim_incident.checkup.run`, which prints exactly one JSON line `{"event": "checkup_end", ...}`.
If the run cannot even start, this file prints one fixed JSON line of the same kind (exception type only, never its
text and never the environment) and exits 1. Exit codes: 0 normal, 3 reporting disturbed, 1 internal error.

`diagnose` (Qwen, PR-2) and `watch` (outside watch, PR-3) are not part of this release: fixed line, exit 2.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UTC = timezone.utc
LATER = {'diagnose': 'Qwen-Diagnose, PR-2', 'watch': 'Außenwache, PR-3'}
_WINDOW = re.compile(r'([1-9][0-9]{0,4})([mhd])')
_SPOOL_FILE = re.compile(r'^\d{12}-[a-z_]{1,20}-[0-9a-f]{12}\.json$')
TAIL_BYTES = 4 * 1024 * 1024
STATUS_LIST_MAX = 50


def _print_line(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def _setup_error(stage: str, error: BaseException, host: str | None) -> dict:
    """The fixed checkup_end line for a run that could not start: stage and exception type only, never the message
    (a PolicyError can quote a key of the file). The full message: load_policy() in a Python shell."""
    return {'event': 'checkup_end', 'host': host or 'unknown', 'exit_code': 1, 'error': type(error).__name__,
            'stage': stage, 'reporting': 'unknown', 'preflight': 'skipped', 'journal_access': 'unknown', 'open': []}


# --- run ---------------------------------------------------------------------------------------------------------

def run_checkup(*, root: Path = ROOT, data_dir: Path | None = None, environ=None, policy_path: Path | None = None,
                now=None, clock=time.time, monotonic=time.monotonic, transport=None, openssl=None, runner=None,
                connect=None, health_collect=None, statvfs=None, proc_dir: Path | None = None) -> int:
    """One checkup run; returns its exit code. Everything after `policy_path` is a test seam: production passes
    nothing (real clock, journalctl/systemctl runner, sockets, openssl, HTTPS transport)."""
    environ = os.environ if environ is None else environ
    data_dir = Path(root) / 'data' if data_dir is None else Path(data_dir)
    stage, host, reporter = 'import', None, None
    try:
        from src.tim_incident import checkup
        from src.tim_incident.github import build_reporter
        from src.tim_incident.policy import load_policy, load_settings
        stage = 'policy'
        policy = load_policy() if policy_path is None else load_policy(policy_path)
        host = policy.host
        stage = 'settings'
        settings = load_settings(environ)
        stage = 'reporter'
        credentials = Path(settings.credentials_directory) if settings.credentials_directory else None
        # The reporter and checkup.run share one monotonic clock: the delivery deadline is measured on it.
        reporter = build_reporter(settings, policy, data_dir=data_dir, credentials_dir=credentials,
                                  transport=transport, runner=openssl, clock=clock, monotonic=monotonic)
    except Exception as error:
        _print_line(_setup_error(stage, error, host))
        return 1
    try:
        return checkup.run(root=Path(root), data_dir=data_dir, policy=policy, settings=settings, reporter=reporter,
                           environ=environ, now=clock() if now is None else now, runner=runner, connect=connect,
                           monotonic=monotonic, health_collect=health_collect, statvfs=statvfs,
                           proc_dir=Path('/proc') if proc_dir is None else Path(proc_dir))
    except Exception as error:      # checkup.run handles its own errors; this is the last line of defence
        _print_line(_setup_error('run', error, host))
        return 1
    finally:
        try:
            reporter.close()
        except Exception:
            pass


# --- status (read only) ------------------------------------------------------------------------------------------

def parse_window(text: str) -> timedelta:
    match = _WINDOW.fullmatch(text or '')
    if not match:
        raise argparse.ArgumentTypeError('Dauer wie 90m, 24h oder 7d angeben')
    amount, unit = int(match.group(1)), match.group(2)
    return {'m': timedelta(minutes=amount), 'h': timedelta(hours=amount), 'd': timedelta(days=amount)}[unit]


def _time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _human(value) -> str:
    moment = _time(value) if isinstance(value, str) else value
    return moment.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC') if isinstance(moment, datetime) else 'unbekannt'


def _age(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return '-'
    minutes = int(max(0, seconds) // 60)
    return f'{minutes // 60} h {minutes % 60} min' if minutes >= 60 else f'{minutes} min'


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _jsonl_tail(path: Path) -> list[dict]:
    try:
        with open(path, 'rb') as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - TAIL_BYTES))
            data = handle.read(TAIL_BYTES)
    except OSError:
        return []
    lines = data.split(b'\n')
    if size > TAIL_BYTES:
        lines = lines[1:]           # the first line may be cut
    records = []
    for line in lines:
        try:
            value = json.loads(line.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _spool(outbox: Path, now: datetime) -> tuple[dict[str, int], float | None]:
    """Pending outbox entries by kind and the age of the oldest; read only (github.Spool would create directories)."""
    kinds: dict[str, int] = {}
    oldest = None
    try:
        names = sorted(path.name for path in outbox.iterdir())
    except OSError:
        return kinds, None
    for name in names:
        if not _SPOOL_FILE.match(name):
            continue
        kind = name.split('-')[1]
        kinds[kind] = kinds.get(kind, 0) + 1
        data = _read_json(outbox / name) or {}
        queued = data.get('queued_at')
        if not isinstance(queued, (int, float)) or isinstance(queued, bool):
            try:
                queued = (outbox / name).stat().st_mtime
            except OSError:
                continue
        oldest = queued if oldest is None else min(oldest, queued)
    return kinds, (now.timestamp() - oldest if oldest is not None else None)


def _in_window(value, start: datetime) -> bool:
    moment = _time(value)
    return moment is not None and moment >= start


def _strings(value) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _clean(value, limit: int = 120) -> str:
    """Text from our own files, shown on a terminal: one line, no control characters, bounded."""
    text = ''.join(char if char.isprintable() else ' ' for char in str(value))
    return ' '.join(text.split())[:limit]


def show_status(*, data_dir: Path, since: timedelta, now: datetime | None = None, out=None) -> int:
    """Open episodes, last run, outbox, minor gaps and would-be actions of the dry run within `since`."""
    from src.tim_incident import checkup
    out = sys.stdout if out is None else out
    now = (now or datetime.now(UTC)).astimezone(UTC)
    start = now - since
    paths = checkup.CheckupPaths(Path(data_dir))
    try:
        os.listdir(paths.incidents)
    except FileNotFoundError:
        print(f'Noch kein Checkup-Lauf: {paths.incidents} fehlt.', file=out)
        return 0
    except OSError:
        print(f'Kein Lesezugriff auf {paths.incidents}. Als Benutzer tim starten: '
              'sudo -u tim /opt/tim/.venv/bin/python /opt/tim/scripts/tim_checkup.py status', file=out)
        return 1
    lines = [f'TIM-Checkup Status, Stand {_human(now)}, Fenster {_human(start)} bis jetzt']

    last = _read_json(paths.last_run)
    if last is None:
        lines.append('Letzter Lauf: keiner aufgezeichnet')
    elif last.get('phase') == 'finished':
        lines.append(f"Letzter Lauf: beendet {_human(last.get('finished_at'))}, Exit {_clean(last.get('exit_code'))}, "
                     f"Melden {_clean(last.get('reporting'))}, Journal {_clean(last.get('journal_access'))}")
    else:
        lines.append(f"Letzter Lauf: gestartet {_human(last.get('started_at'))}, noch nicht beendet")

    state, state_status = checkup.load_state(paths.data, previous_run=last is not None)
    lines.append(f"Zustand: {state_status}, aktualisiert {_human(state.get('updated_at'))}")
    active = checkup.active_episodes(state)
    lines.append(f'Offene Episoden: {len(active)}')
    for _, episode in active:
        lines.append(f"  - {episode['class']} Episode {episode['episode']}, aktuell {episode['current']}, "
                     f"seit {_human(episode['opened_at'])}, gemeldet: {episode.get('announced_mode') or 'nein'}, "
                     f"saubere Läufe {episode['clean_runs']}, Wiederöffnungen {episode['reopen_count']}")
    episodes = ([state['chain']] if state.get('chain') else []) + list((state.get('independent') or {}).values())
    resolved = [episode for episode in episodes if episode and episode['status'] == 'resolved'
                and (_time(episode.get('resolved_at')) or now) >= start]
    for episode in resolved:
        lines.append(f"  - erholt: {episode['class']} Episode {episode['episode']}, "
                     f"erholt {_human(episode.get('resolved_at'))}")

    kinds, oldest = _spool(paths.outbox, now)
    detail = ', '.join(f'{kind} {count}' for kind, count in sorted(kinds.items()))
    lines.append(f"Puffer: {sum(kinds.values())} offen{f' ({detail})' if detail else ''}, "
                 f'ältester Eintrag {_age(oldest)}')
    delivery = _read_json(paths.incidents / 'delivery.json') or {}
    pause = delivery.get('pause') if isinstance(delivery.get('pause'), dict) else None
    if pause and isinstance(pause.get('until'), (int, float)) and pause['until'] > now.timestamp():
        lines.append(f"Melder pausiert ({_clean(pause.get('kind'))}) bis "
                     f"{_human(datetime.fromtimestamp(pause['until'], UTC))}")
    uncertain = sorted(delivery.get('uncertain') or {}) if isinstance(delivery.get('uncertain'), dict) else []
    if uncertain:
        lines.append(f"Anlegen unsicher (siehe confirm-not-created): {', '.join(_clean(ep, 40) for ep in uncertain)}")

    minor = [item for item in _jsonl_tail(paths.minor) if _in_window(item.get('at'), start)]
    lines.append(f'Kleine Lücken im Fenster (minor.jsonl): {len(minor)}')
    for item in minor[-STATUS_LIST_MAX:]:
        first, rules = _strings(item.get('first_missing')), ', '.join(_strings(item.get('rules')))
        lines.append(f"  - {_human(item.get('at'))}: {_clean(item.get('missing'))} min fehlen ab "
                     f"{_human(first[0]) if first else 'unbekannt'}, Regeln {_clean(rules)}")

    dry = [item for item in _jsonl_tail(paths.incidents / 'dryrun.jsonl') if _in_window(item.get('run_at'), start)]
    would: dict[str, int] = {}
    for item in dry:
        would[_clean(item.get('would'), 40)] = would.get(_clean(item.get('would'), 40), 0) + 1
    summary = ', '.join(f'{name} {count}' for name, count in sorted(would.items()))
    lines.append(f"Dry-run im Fenster (dryrun.jsonl): {len(dry)} Schreibzugriffe wären erfolgt"
                 f"{f' ({summary})' if summary else ''}")
    for item in [item for item in dry if item.get('would') in ('create_issue', 'adopt_issue')][-STATUS_LIST_MAX:]:
        lines.append(f"  - {_human(item.get('run_at'))} {_clean(item.get('would'), 20)}: {_clean(item.get('title'))} "
                     f"[{_clean(', '.join(_strings(item.get('labels'))))}]")
    print('\n'.join(lines), file=out)
    return 0


# --- command line ------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None, *, environ=None, root: Path = ROOT, data_dir: Path | None = None,
         now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(prog='tim_checkup.py', description='TIM checkup and incident reporter '
                                     '(OBSERVE only). Details: docs/TIM_CHECKUP.md')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('run', help='one checkup run (tim-checkup.service, user tim)')
    status = commands.add_parser('status', help='state, outbox and dry-run actions; reads files only')
    status.add_argument('--since', type=parse_window, default=timedelta(hours=24), metavar='DAUER',
                        help='window for minor gaps and dry-run actions, e.g. 90m, 24h, 7d (default 24h)')
    for name, part in LATER.items():
        commands.add_parser(name, help=f'not part of this release ({part})')
    args = parser.parse_args(argv)
    data_dir = Path(root) / 'data' if data_dir is None else Path(data_dir)
    if args.command in LATER:
        print(f'tim_checkup.py {args.command}: nicht Teil dieser Version ({LATER[args.command]}).', file=sys.stderr)
        return 2
    if args.command == 'status':
        return show_status(data_dir=data_dir, since=args.since, now=now)
    if os.geteuid() == 0:
        # Files written as root would lock the tim user out of its own state on the next timer run.
        print('tim_checkup.py run: nicht als root starten, sondern mit sudo systemctl start tim-checkup.service.',
              file=sys.stderr)
        return 1
    return run_checkup(root=Path(root), data_dir=data_dir, environ=environ)


if __name__ == '__main__':
    sys.exit(main())
