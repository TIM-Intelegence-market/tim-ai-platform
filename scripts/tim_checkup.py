#!/usr/bin/env python3
"""TIM checkup entry point (design parts A, B and C). OBSERVE only.

    tim_checkup.py run                  one checkup run (tim-checkup.service, user tim)
    tim_checkup.py status [--since 24h] what the checkup knows; reads files only, never writes
    tim_checkup.py diagnose             one Qwen diagnosis run (tim-qwen-diagnose.service, user tim-agent)
    tim_checkup.py calibrate [--endpoint URL]
                                        P2 measurement for the owner (as tim-server); prints values, writes nothing
    tim_checkup.py watch [--once] [--host HOST]
                                        outside watch on the Mac (launchd every 300 s, design part D)

`run` loads config/tim_checkup.json and the TIM_CHECKUP_* settings from the environment, builds the incident
reporter and calls `src.tim_incident.checkup.run`, which prints exactly one JSON line `{"event": "checkup_end", ...}`.
If the run cannot even start, this file prints one fixed JSON line of the same kind (exception type only, never its
text and never the environment) and exits 1. Exit codes: 0 normal, 3 reporting disturbed, 1 internal error.

`diagnose` calls `src.tim_incident.qwen.run` and prints its one JSON line `{"event": "diagnose_end", ...}`. It is
fail-closed: while a server-only value in config `agent` is null the line is `"outcome": "not_calibrated"` and the
exit code 0, before any self-check output, file read or network call. Then come the budget, `sandbox_selfcheck`
(exit 2 on a violation), PAUSE/HOLD, the queue, the gate and the model pin. It never reads TIM_CHECKUP_* (the unit
has no EnvironmentFile): whether it runs at all is decided by the installer enabling the timer.

`calibrate` performs the measurement of design section 7 against Ollama on 127.0.0.2 (default; 127.0.0.1 only
with a warning that the values lack the production limits) (only GET
/api/tags, POST /api/show and POST /api/chat; never a pull) and prints one JSON line with the values to paste into
config/tim_checkup.json by a reviewed PR. It writes nothing.

`watch` calls `src.tim_incident.watch.run_once`: one pass (online check, one ssh call with fixed argv, decision,
at most the comments of one episode on the watch issue W, macOS notifications) and one JSON line
`{"event": "watch_end", ...}`. It reads only HOME and TIM_WATCH_* from the environment. Without them it prints a fixed
German line and exits 2 before any network call. `--once` is the default (launchd repeats the pass); `--host` replaces
the ssh target for the simulation in design section 16 (`--host tim-server-unreachable.invalid`).
Exit codes: 0 normal (an alarm included), 2 not set up, 3 a comment cannot be delivered (notification: key rejected
with HTTP 401 or missing from the keychain, token refused, keychain or openssl failing, W not usable, HTTP 403 three
times), 1 internal error. SIGTERM (launchd at logout, `launchctl bootout`) ends the pass through SystemExit, so the
temporary key file is removed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UTC = timezone.utc
_WINDOW = re.compile(r'([1-9][0-9]{0,4})([mhd])')
_SPOOL_FILE = re.compile(r'^\d{12}-[a-z_]{1,20}-[0-9a-f]{12}\.json$')
TAIL_BYTES = 4 * 1024 * 1024
STATUS_LIST_MAX = 50
DEFAULT_ENDPOINT = 'http://127.0.0.2:11434'      # Ollama behind the TIM drop-in, as in production


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
                connect=None, health_collect=None, statvfs=None, proc_dir: Path | None = None, agent_dir=...,
                user_lookup=None, own_uid: int | None = None) -> int:
    """One checkup run; returns its exit code. Everything after `policy_path` is a test seam: production passes
    nothing (real clock, journalctl/systemctl runner, sockets, openssl, HTTPS transport, /var/lib/tim-agent, the
    pwd lookup of tim-agent and the own uid). `agent_dir=None` skips the diagnosis part."""
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
                           proc_dir=Path('/proc') if proc_dir is None else Path(proc_dir),
                           agent_dir=checkup.AGENT_DIR if agent_dir is ... else agent_dir, user_lookup=user_lookup,
                           own_uid=own_uid)
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


# --- diagnose (tim-agent) ----------------------------------------------------------------------------------------

def _diagnose_error(stage: str, error: BaseException) -> dict:
    """The fixed diagnose_end line for a run that could not start: stage and exception type only."""
    return {'event': 'diagnose_end', 'outcome': 'error', 'exit_code': 1, 'stage': stage,
            'error': type(error).__name__}


def run_diagnose(*, policy_path: Path | None = None, **seams) -> int:
    """One `tim_checkup.py diagnose` run: `qwen.run` (calibration and budget first, then `sandbox_selfcheck`, then
    PAUSE/HOLD, queue, gate, model pin, tool loop) and its one JSON line. `seams` go to `qwen.run` (tests only:
    directories, uid of the request owner, self-check, runner, /proc reader, Ollama transport, toolbox, clock)."""
    try:
        from src.tim_incident import qwen
        from src.tim_incident.policy import load_policy
        policy = load_policy() if policy_path is None else load_policy(policy_path)
    except Exception as error:
        _print_line(_diagnose_error('policy', error))
        return 1
    try:
        end = qwen.run(policy=policy, **seams)
    except Exception as error:      # qwen.run handles its own errors; this is the last line of defence
        _print_line(_diagnose_error('run', error))
        return 1
    _print_line(end)
    code = end.get('exit_code')
    return code if isinstance(code, int) and not isinstance(code, bool) else 1


# --- calibrate (owner, P2) ---------------------------------------------------------------------------------------

CALIBRATE_FILES = ('scripts/tim_server_health.py', 'src/operational/watchdog.py', 'src/data_ingestion/catchup.py')
CALIBRATE_TEXT_CHARS = 36000
CALIBRATE_TIMEOUT = 1500.0                  # seconds per call, as in design section 7 (cold model load included)
CALIBRATE_NUM_PREDICT = 128
_CALIBRATE_ENDPOINT = re.compile(r'^http://(127\.0\.0\.[12]):([1-9][0-9]{0,4})/?$')
_CALIBRATE_TOOL = {'type': 'function', 'function': {
    'name': 'read_file', 'description': 'read a file',
    'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}


class CalibrationError(Exception):
    """Fixed German texts only; never response text."""


def calibrate_endpoint(value: str) -> tuple[str, int]:
    """http://127.0.0.2:<port> (behind the drop-in) or http://127.0.0.1:<port> (without it, flagged); nothing else."""
    match = _CALIBRATE_ENDPOINT.match(value or '')
    if not match or not 1 <= int(match.group(2)) <= 65535:
        raise argparse.ArgumentTypeError('nur http://127.0.0.1:<port> oder http://127.0.0.2:<port>')
    return match.group(1), int(match.group(2))


def _rate(count, nanoseconds) -> float:
    if type(count) is not int or type(nanoseconds) is not int or count <= 0 or nanoseconds <= 0:
        raise CalibrationError('Antwort ohne Zähler oder Dauer (prompt_eval_count/eval_count)')
    return count / (nanoseconds / 1e9)


def calibrate(*, endpoint: tuple[str, int], root: Path = ROOT, policy_path: Path | None = None, transport=None,
              read_text=None, out=None, err=None) -> int:
    """Design section 7 (P2): psi before, two chat calls with the same prefix (prompt and generation speed, cache),
    one tool-call probe, /api/tags digest and the sha256 over template/system/parameters of /api/show, psi after.
    Prints one JSON line {"event": "calibrate", "paste": {...}, "hint": {...}}; `paste` holds the measured values for
    config `agent`. Writes nothing. Exit 0 measured, 1 not measurable (fixed text on stderr)."""
    from src.tim_incident import qwen
    from src.tim_incident.policy import AGENT_MODEL, compute_budget, load_policy
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    host, port = endpoint
    send = transport or qwen.http_transport(host, port)
    read_text = read_text or qwen._read_text
    try:
        policy = load_policy() if policy_path is None else load_policy(policy_path)
    except Exception:
        print('calibrate: config/tim_checkup.json lässt sich nicht laden; erst die Konfiguration reparieren.', file=err)
        return 1
    agent = policy.agent

    def call(method: str, path: str, payload: dict | None) -> dict:
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        try:
            status, raw = send(method, path, body, CALIBRATE_TIMEOUT)
        except qwen.OllamaError:
            raise CalibrationError(f'Ollama auf {host}:{port} nicht erreichbar oder zu langsam ({path})') from None
        if status != 200:
            raise CalibrationError(f'Ollama antwortet auf {path} mit HTTP {int(status)}')
        try:
            value = qwen._json(bytes(raw).decode('utf-8'))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise CalibrationError(f'Antwort von {path} ist kein JSON') from None
        if not isinstance(value, dict):
            raise CalibrationError(f'Antwort von {path} ist kein Objekt')
        return value

    def psi():
        try:
            return qwen.read_psi(read_text)
        except (OSError, ValueError, KeyError):
            return None

    try:
        psi_before = psi()
        tags = call('GET', '/api/tags', None)
        models = tags.get('models') if isinstance(tags.get('models'), list) else []
        entries = [m for m in models if isinstance(m, dict) and AGENT_MODEL in (m.get('name'), m.get('model'))]
        digest = qwen.normalize_digest(entries[0].get('digest')) if len(entries) == 1 else None
        if digest is None:
            raise CalibrationError(f'{AGENT_MODEL} fehlt auf {host}:{port} oder hat keinen Digest. '
                                   'Nie "ollama pull" auf dem Server: den Inhaber fragen.')
        show = call('POST', '/api/show', {'model': AGENT_MODEL})
        config_sha = qwen.config_sha256(show)
        parts = []
        for name in CALIBRATE_FILES:
            try:
                parts.append(read_text_file(Path(root) / name))
            except OSError:
                raise CalibrationError(f'{name} unter {root} nicht lesbar') from None
        text = ''.join(parts)[:CALIBRATE_TEXT_CHARS]
        options = {'num_thread': agent.num_thread, 'num_ctx': agent.num_ctx, 'num_predict': CALIBRATE_NUM_PREDICT,
                   'temperature': 0.2}
        # A fresh mark at the very start: a repeat within keep_alive must not find call 1's prefix in the cache.
        base = [{'role': 'system', 'content': f'Lauf {secrets.token_hex(8)}. Du bist ein Diagnosewerkzeug. Nur lesen.'},
                {'role': 'user', 'content': 'Fasse zusammen:\n' + text}]
        runs = []
        for extra in ([], [{'role': 'user', 'content': 'Und jetzt in einem Satz.'}]):
            response = call('POST', '/api/chat', {'model': AGENT_MODEL, 'stream': False, 'tools': [_CALIBRATE_TOOL],
                                                  'options': options, 'keep_alive': '10m',
                                                  'messages': base + extra})
            runs.append({'prompt_tok_s': _rate(response.get('prompt_eval_count'),
                                               response.get('prompt_eval_duration')),
                         'gen_tok_s': _rate(response.get('eval_count'), response.get('eval_duration')),
                         'prompt_ns': response.get('prompt_eval_duration'),
                         'load_s': round((response.get('load_duration') or 0) / 1e9, 1)
                         if type(response.get('load_duration')) is int else None})
        probe = call('POST', '/api/chat', {'model': AGENT_MODEL, 'stream': False, 'tools': [_CALIBRATE_TOOL],
                                           'options': options, 'messages': [
                                               {'role': 'user',
                                                'content': 'Lies scripts/tim_server_health.py mit dem Werkzeug.'}]})
        message = probe.get('message') if isinstance(probe.get('message'), dict) else {}
        calls = message.get('tool_calls')
        tool_calls_ok = (isinstance(calls, list) and len(calls) >= 1 and isinstance(calls[0], dict)
                         and isinstance(calls[0].get('function'), dict)
                         and calls[0]['function'].get('name') == 'read_file')
        psi_after = psi()
    except CalibrationError as error:
        print(f'calibrate: {error}', file=err)
        return 1

    prompt_tok_s = round(runs[0]['prompt_tok_s'], 1)        # the first call is uncached: the real prompt speed
    gen_tok_s = round(min(run['gen_tok_s'] for run in runs), 1)
    cache_ok = runs[1]['prompt_ns'] <= 0.2 * runs[0]['prompt_ns']
    budget = compute_budget(prompt_tok_s, gen_tok_s, cache_ok=cache_ok, tool_calls_ok=tool_calls_ok,
                            per_call_timeout=agent.per_call_timeout_seconds, deadline=agent.deadline_seconds,
                            evidence_tokens_max=agent.evidence_tokens_max,
                            round_prompt_tokens=agent.round_prompt_tokens, num_predict_round=agent.num_predict_round,
                            num_predict_final=agent.num_predict_final, max_rounds_cap=agent.max_rounds_cap)
    paste = {'model_digest': digest, 'model_config_sha256': config_sha,
             'measured': {'prompt_tok_s': prompt_tok_s, 'gen_tok_s': gen_tok_s, 'cache_ok': cache_ok}}
    if budget.go:
        paste['tool_mode'] = budget.mode
    hint = {'budget_mode': budget.mode, 'max_rounds': budget.max_rounds, 'evidence_tokens': budget.evidence_tokens,
            'reason': budget.reason, 'tool_calls_ok': tool_calls_ok, 'load_seconds': [run['load_s'] for run in runs],
            'psi_before': psi_before, 'psi_after': psi_after,
            'still_from_p0': ['ollama_allowed_cpus', 'resolver'], 'valid_for_config': host != '127.0.0.1'}
    _print_line_to(out, {'event': 'calibrate', 'endpoint': f'http://{host}:{port}', 'model': AGENT_MODEL,
                         'paste': {'agent': paste}, 'hint': hint})
    print('calibrate: Werte unter "paste" per PR in config/tim_checkup.json -> agent eintragen; ollama_allowed_cpus '
          'und resolver kommen aus P0. Nur gültig, wenn tim-server-health und Watchdog während der Messung GREEN '
          'blieben (docs/TIM_CHECKUP.md, Kalibrieren).', file=err)
    if not budget.go:
        print(f'calibrate: No-Go ({budget.mode}): die Diagnose nicht einschalten.', file=err)
    if host == '127.0.0.1':
        print('calibrate: WARNUNG: gemessen gegen 127.0.0.1, also Ollama ohne TIM-Drop-in und ohne die Grenzen des '
              'Betriebs. Diese Werte nicht in die Konfiguration übernehmen; nach Qwen-Schritt 3 gegen '
              'http://127.0.0.2:11434 messen.', file=err)
    return 0


def read_text_file(path: Path) -> str:
    with open(path, encoding='utf-8', errors='replace') as handle:
        return handle.read(CALIBRATE_TEXT_CHARS)


def _print_line_to(out, value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), file=out, flush=True)


# --- watch (Mac, design D) ---------------------------------------------------------------------------------------

def run_watch(*, host: str, environ=None, policy_path: Path | None = None, **seams) -> int:
    """One pass of the outside watch and its one JSON line. `seams` go to `watch.run_once` (tests only: runner,
    transport, clock, state_path, tempdir)."""
    environ = os.environ if environ is None else environ
    try:
        from src.tim_incident import watch
        from src.tim_incident.policy import load_policy
        settings = watch.load_watch_settings(environ)
        if not settings.complete:
            print('tim_checkup.py watch: nicht eingerichtet (' + '; '.join(settings.problems) + '). '
                  'Siehe docs/TIM_CHECKUP.md, Außenwache vom Mac.', file=sys.stderr)
            _print_line({'event': 'watch_end', 'state': 'UNKNOWN', 'exit_code': 2, 'problems': list(settings.problems)})
            return 2
        repository = (load_policy() if policy_path is None else load_policy(policy_path)).repository
    except Exception as error:
        _print_line({'event': 'watch_end', 'state': 'UNKNOWN', 'exit_code': 1, 'stage': 'setup',
                     'error': type(error).__name__})
        return 1
    try:
        record = watch.run_once(settings, host=host, repository=repository, **seams)
    except Exception as error:      # run_once handles its own errors; this is the last line of defence
        _print_line({'event': 'watch_end', 'state': 'UNKNOWN', 'exit_code': 1, 'stage': 'run',
                     'error': type(error).__name__})
        return 1
    _print_line(record)
    code = record.get('exit_code')
    return code if isinstance(code, int) and not isinstance(code, bool) else 1


def _exit_on_sigterm(signum, frame):
    raise SystemExit(143)


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
    commands.add_parser('diagnose', help='one Qwen diagnosis run (tim-qwen-diagnose.service, user tim-agent); '
                        'fail-closed while config agent is not calibrated')
    calibration = commands.add_parser('calibrate', help='P2 measurement against Ollama for the owner; prints the '
                                      'values for config agent, writes nothing')
    calibration.add_argument('--endpoint', type=calibrate_endpoint, default=calibrate_endpoint(DEFAULT_ENDPOINT),
                             metavar='URL', help='http://127.0.0.2:<port> (Ollama with the drop-in limits) or '
                             f'http://127.0.0.1:<port> (flagged: not for config) (default {DEFAULT_ENDPOINT})')
    watch = commands.add_parser('watch', help='outside watch from the Mac: one pass (launchd every 300 s)')
    watch.add_argument('--once', action='store_true', help='one pass and exit (the default; launchd repeats it)')
    watch.add_argument('--host', default='tim-server', metavar='HOST',
                       help='ssh target (default tim-server, the alias in ~/.ssh/config); '
                       'tim-server-unreachable.invalid simulates an outage')
    args = parser.parse_args(argv)
    data_dir = Path(root) / 'data' if data_dir is None else Path(data_dir)
    if args.command == 'watch':
        if environ is None:                         # the real process: let finally blocks run on SIGTERM
            import signal
            signal.signal(signal.SIGTERM, _exit_on_sigterm)
        return run_watch(host=args.host, environ=environ)
    if args.command == 'status':
        return show_status(data_dir=data_dir, since=args.since, now=now)
    if args.command == 'diagnose':
        return run_diagnose()
    if args.command == 'calibrate':
        return calibrate(endpoint=args.endpoint, root=Path(root))
    if os.geteuid() == 0:
        # Files written as root would lock the tim user out of its own state on the next timer run.
        print('tim_checkup.py run: nicht als root starten, sondern mit sudo systemctl start tim-checkup.service.',
              file=sys.stderr)
        return 1
    return run_checkup(root=Path(root), data_dir=data_dir, environ=environ)


if __name__ == '__main__':
    sys.exit(main())
