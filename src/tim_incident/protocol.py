"""Diagnosis protocol between tim-checkup (user tim) and tim-qwen-diagnose (user tim-agent), design C.1, C.5 and B.8.

The checkup writes requests to /var/lib/tim-agent/requests/<rid>.json, plus HOLD and PAUSE; the agent writes results to
/var/lib/tim-agent/results/<rid>.json; the checkup acknowledges with requests/<rid>.ack. Each side treats what the other
wrote as untrusted: files are opened with O_NOFOLLOW|O_NONBLOCK, checked with fstat (regular file, owner, link count,
size) before a byte is read, parsed as strict JSON (no duplicate keys, no NaN) and validated against a closed schema.

`check_path`/`path_allowed`/`read_beneath` implement the read_file allowlist of design C.2; the agent tools and the
checkup ingest (B.8, `locations`) use the same code.

Error messages are fixed texts chosen by code (`ProtocolError.code`); they never contain file content, model text or
a path from the other side.
"""
from __future__ import annotations

import errno
import json
import math
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .policy import CLASS_NAMES

UTC = timezone.utc
PROTOCOL_VERSION = 1

REQUEST_MAX_BYTES = 65536           # default; the checkup passes policy.limits.request_bytes
RESULT_MAX_BYTES = 32768            # design B.8
PAUSE_MAX_BYTES = 1024
REPO_FILE_MAX_BYTES = 1024 * 1024   # read_file and location checks (design C.2)

EVIDENCE_MAX_CHARS = 16384          # 3 * evidence_tokens_max (4096) with margin; the budget cuts further
JOURNAL_MAX_LINES = 200             # per unit (design A.4)
JOURNAL_LINE_MAX_CHARS = 2000
REQUEST_UNITS_MAX = 8
EXPECTED_PATHS_MAX = 10

HOLD = 'HOLD'
PAUSE = 'PAUSE'
PAUSE_REASONS = ('breaker', 'label')

FIX_KINDS = ('code_src', 'code_locked', 'ops_manual', 'external_network', 'transient', 'unknown')
RESULT_MODES = ('native', 'schema', 'einschuss')
RESULT_LIMITS = {'summary': 300, 'root_cause': 800, 'suggestion': 1200, 'verification': 600}
LOCATIONS_MAX = 5
LOCATION_WHY_MAX = 200
SOURCES_MAX = 5
FETCHED_URLS_MAX = 16
ROUNDS_MAX = 20
# A request without result this long after its file time (written, or re-dated by the checkup while HOLD/PAUSE
# stood) gets "Diagnose ausgefallen" and an .ack; the agent starts no request it cannot finish before that.
DIAGNOSIS_OVERDUE_SECONDS = 60 * 60

# Fixed German texts for the one comment "Diagnose nicht möglich: <Grund>" (design C.5). Keys are the result reasons.
FAILURE_TEXTS = {
    'model_mismatch': 'Modell weicht ab',
    'ollama_unavailable': 'Ollama nicht erreichbar',
    'timeout': 'Zeitlimit überschritten',
    'invalid_output': 'Antwort des Modells ungültig',
    'context_exhausted': 'Kontext erschöpft',
    'load': 'Abbruch wegen Last auf dem Server',
    'request_invalid': 'Auftrag ungültig',
    'internal': 'interner Fehler der Diagnose',
}
FAILURE_REASONS = tuple(FAILURE_TEXTS)

ERROR_TEXTS = {
    'unreadable': 'file cannot be opened',
    'symlink': 'file is a symbolic link',
    'not_regular': 'not a regular file',
    'wrong_owner': 'file has the wrong owner',
    'linked': 'file has more than one link',
    'too_large': 'file is too large',
    'not_json': 'file is not strict JSON',
    'schema': 'content does not match the schema',
    'bad_name': 'invalid file name',
    'write_failed': 'file cannot be written',
}

# Path rules of the read_file tool (design C.2) and of result locations (B.8).
TOOL_PREFIXES = ('src/', 'scripts/', 'config/', 'ops/', 'tests/', 'docs/', '.venv/lib/')
LOCATION_PREFIXES = ('src/', 'scripts/', 'config/', 'ops/', 'tests/', 'docs/')
PATH_ERRORS = ('syntax', 'prefix', 'blocked', 'missing', 'symlink', 'not_regular', 'outside_root')
_PATH = re.compile(r'^[A-Za-z0-9_./-]{1,200}$')
_REQUIREMENTS = re.compile(r'^requirements[A-Za-z0-9_.-]{0,60}\.txt$')
_BLOCKED_DIRS = frozenset({'data', 'artifacts', '.git'})
_BLOCKED_WORDS = ('secret', 'token', 'password', 'credential')
_BLOCKED_SUFFIXES = frozenset({'pem', 'key'})

_EPISODE = r'\d{8}T\d{4}Z'
_RID = re.compile(rf'^({_EPISODE})-([a-z][a-z-]{{1,19}})-([1-9][0-9]{{0,2}})$')
_EPISODE_RE = re.compile(rf'^{_EPISODE}$')
_TIME = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
_UNIT = re.compile(r'^[A-Za-z0-9@_.:-]{1,120}\.(?:service|timer|path|socket|target|mount)$')
_URL = re.compile(r'^https://([a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?)(/[A-Za-z0-9._~/-]{0,200})?$')
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
_BAD_CHARS = re.compile(r'[\x00-\x08\x0b-\x1f\x7f  ]')


class ProtocolError(ValueError):
    """A file or object of the other side is not acceptable. `code` is a key of ERROR_TEXTS; the message is the fixed
    text for it and never contains file content."""

    def __init__(self, code: str):
        self.code = code if code in ERROR_TEXTS else 'schema'
        super().__init__(ERROR_TEXTS[self.code])


# --- names ---------------------------------------------------------------------------------------------------------

def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError('datetime expected')
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def iso(moment: datetime) -> str:
    return _utc(moment).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not _TIME.match(value):
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=UTC)
    except ValueError:
        return None


def class_slug(cls: str) -> str:
    """'DATA_FLOW' -> 'data-flow' (the class part of a rid)."""
    if cls not in CLASS_NAMES:
        raise ValueError('unknown class')
    return cls.lower().replace('_', '-')


def make_rid(episode: str, cls: str, seq: int) -> str:
    """Request id '<episode>-<class slug>-<seq>', e.g. '20260930T0312Z-data-flow-1'. Sorting rids sorts by episode."""
    if not isinstance(episode, str) or not _EPISODE_RE.match(episode):
        raise ValueError('invalid episode')
    if isinstance(seq, bool) or not isinstance(seq, int) or not 1 <= seq <= 999:
        raise ValueError('invalid sequence number')
    return f'{episode}-{class_slug(cls)}-{seq}'


def parse_rid(rid: Any) -> tuple[str, str, int] | None:
    """(episode, class, seq) or None."""
    if not isinstance(rid, str):
        return None
    match = _RID.match(rid)
    if not match:
        return None
    cls = match.group(2).upper().replace('-', '_')
    if cls not in CLASS_NAMES:
        return None
    return match.group(1), cls, int(match.group(3))


def request_name(rid: str) -> str:
    return _checked_rid(rid) + '.json'


def result_name(rid: str) -> str:
    return _checked_rid(rid) + '.json'


def ack_name(rid: str) -> str:
    return _checked_rid(rid) + '.ack'


def _checked_rid(rid: str) -> str:
    if parse_rid(rid) is None:
        raise ProtocolError('bad_name')
    return rid


# --- strict JSON -----------------------------------------------------------------------------------------------------

def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError('not_json')
        result[key] = value
    return result


def _no_constant(_name):
    raise ProtocolError('not_json')


def loads_strict(data: bytes, max_bytes: int) -> dict:
    """Parse one JSON object from bytes: size first, strict UTF-8, no duplicate keys, no NaN/Infinity."""
    if not isinstance(data, (bytes, bytearray)):
        raise ProtocolError('not_json')
    if len(data) > max_bytes:
        raise ProtocolError('too_large')
    try:
        value = json.loads(bytes(data).decode('utf-8'), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except ProtocolError:
        raise
    except (ValueError, RecursionError):
        raise ProtocolError('not_json') from None
    if not isinstance(value, dict):
        raise ProtocolError('schema')
    return value


def _size(value: Any) -> int:
    try:
        return len(dumps(value))
    except (TypeError, ValueError, RecursionError):
        raise ProtocolError('schema') from None


def dumps(value: Mapping) -> bytes:
    """Canonical encoding for requests, results and PAUSE (sorted keys, UTF-8, no NaN)."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
            + '\n').encode('utf-8')


# --- schema helpers --------------------------------------------------------------------------------------------------

def _keys(value: Any, required: Iterable[str], optional: Iterable[str] = ()) -> dict:
    if not isinstance(value, dict):
        raise ProtocolError('schema')
    required, optional = set(required), set(optional)
    if not required <= set(value) <= required | optional:
        raise ProtocolError('schema')
    return value


def _text(value: Any, high: int, low: int = 0) -> str:
    if not isinstance(value, str) or not low <= len(value) <= high or _BAD_CHARS.search(value):
        raise ProtocolError('schema')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:              # lone surrogates from \ud800 escapes
        raise ProtocolError('schema') from None
    return value


def _integer(value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ProtocolError('schema')
    return value


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ProtocolError('schema')
    return value


def _array(value: Any, high: int, low: int = 0) -> list:
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise ProtocolError('schema')
    return value


def _unique(items: list) -> list:
    if len(items) != len(set(items)):
        raise ProtocolError('schema')
    return items


def url_ok(url: Any, domains: Iterable[str] | None = None) -> bool:
    """https URL in the fetch form of design C.3 (port 443, no userinfo, query or fragment, path charset
    [A-Za-z0-9._~/-] up to 200 characters); with `domains`, the host must be one of them exactly."""
    if not isinstance(url, str) or len(url) > 470:
        return False
    match = _URL.match(url)
    if not match or '..' in match.group(1):
        return False
    return domains is None or match.group(1) in set(domains)


# --- requests --------------------------------------------------------------------------------------------------------

REQUEST_KEYS = ('version', 'rid', 'episode', 'class', 'created_at', 'selftest', 'evidence', 'units', 'journal')
REQUEST_OPTIONAL = ('expected_paths',)


def validate_request(value: Any, *, allowed_units: Iterable[str] | None = None,
                     max_bytes: int = REQUEST_MAX_BYTES) -> dict:
    """Validate a request (bytes or a parsed object) and return a fresh copy.

    Schema: {"version": 1, "rid", "episode", "class", "created_at": "YYYY-MM-DDTHH:MM:SSZ", "selftest": bool,
    "evidence": redacted text, "units": [unit, ...] (1..8, unique, subset of `allowed_units` when given),
    "journal": {unit: [line, ...] (<= 200 lines)} with units from "units", optional "expected_paths" (selftest only)}.
    The rid must name the same episode and class. The encoded size must not exceed `max_bytes`.
    """
    if isinstance(value, (bytes, bytearray)):
        value = loads_strict(value, max_bytes)
    data = _keys(value, REQUEST_KEYS, REQUEST_OPTIONAL)
    if _size(data) > max_bytes:
        raise ProtocolError('too_large')
    if _integer(data['version'], 1, 1000) != PROTOCOL_VERSION:
        raise ProtocolError('schema')
    parsed = parse_rid(data['rid'])
    if parsed is None or (parsed[0], parsed[1]) != (data['episode'], data['class']):
        raise ProtocolError('schema')
    if parse_iso(data['created_at']) is None:
        raise ProtocolError('schema')
    selftest = _boolean(data['selftest'])
    if selftest != (data['class'] == 'SELFTEST'):
        raise ProtocolError('schema')
    evidence = _text(data['evidence'], EVIDENCE_MAX_CHARS, 1)
    units = _unique([_text(unit, 130, 1) for unit in _array(data['units'], REQUEST_UNITS_MAX)])
    if not units and not selftest:
        raise ProtocolError('schema')
    if not all(_UNIT.match(unit) for unit in units):
        raise ProtocolError('schema')
    if allowed_units is not None and not set(units) <= set(allowed_units):
        raise ProtocolError('schema')
    if not isinstance(data['journal'], dict) or not set(data['journal']) <= set(units):
        raise ProtocolError('schema')
    journal = {unit: [_text(line, JOURNAL_LINE_MAX_CHARS) for line in _array(lines, JOURNAL_MAX_LINES)]
               for unit, lines in data['journal'].items()}
    result = {'version': PROTOCOL_VERSION, 'rid': data['rid'], 'episode': data['episode'], 'class': data['class'],
              'created_at': data['created_at'], 'selftest': selftest, 'evidence': evidence, 'units': units,
              'journal': journal}
    if 'expected_paths' in data:
        if not selftest:
            raise ProtocolError('schema')
        paths = _unique(_array(data['expected_paths'], EXPECTED_PATHS_MAX, 1))
        if not all(check_path(path, None, location=True) is None for path in paths):
            raise ProtocolError('schema')
        result['expected_paths'] = list(paths)
    return result


def build_request(*, episode: str, cls: str, seq: int, created_at: datetime, evidence: str, units: Iterable[str],
                  journal: Mapping[str, Iterable[str]], expected_paths: Iterable[str] | None = None,
                  allowed_units: Iterable[str] | None = None, max_bytes: int = REQUEST_MAX_BYTES) -> dict:
    """Build and validate a request. The caller passes already redacted evidence and journal lines; journal lists are
    cut to their last JOURNAL_MAX_LINES lines here, nothing else is shortened (a too large request raises)."""
    request = {'version': PROTOCOL_VERSION, 'rid': make_rid(episode, cls, seq), 'episode': episode, 'class': cls,
               'created_at': iso(created_at), 'selftest': cls == 'SELFTEST', 'evidence': evidence,
               'units': list(units), 'journal': {unit: list(lines)[-JOURNAL_MAX_LINES:] for unit, lines in
                                                 journal.items()}}
    if expected_paths is not None:
        request['expected_paths'] = list(expected_paths)
    return validate_request(request, allowed_units=allowed_units, max_bytes=max_bytes)


# --- results ---------------------------------------------------------------------------------------------------------

RESULT_OK_KEYS = ('version', 'rid', 'status', 'summary', 'root_cause', 'confidence', 'fix_kind', 'locations',
                  'suggestion', 'verification', 'sources', 'fetched_urls', 'needs_human', 'unverified_locations',
                  'mode', 'rounds')
RESULT_FAILED_KEYS = ('version', 'rid', 'status', 'reason')
LOCATION_KEYS = ('path', 'line', 'why')


def validate_result(value: Any, *, expected_rid: str | None = None, fetch_domains: Iterable[str] | None = None,
                    max_bytes: int = RESULT_MAX_BYTES) -> dict:
    """Validate a result (bytes or a parsed object) strictly and return a fresh copy. No file system access: the
    location paths are checked for syntax and prefix only; `verify_locations` does the file checks.

    status "ok": summary (1..300), root_cause (..800), confidence (0..1), fix_kind (FIX_KINDS), locations (<= 5 of
    {path, line >= 1, why <= 200}), suggestion (..1200), verification (..600), sources (<= 5, subset of fetched_urls),
    fetched_urls (<= 16, https URLs, hosts in `fetch_domains` when given), needs_human, unverified_locations (count of
    removed locations), mode (RESULT_MODES), rounds (0..20).
    status "failed": reason (FAILURE_REASONS).
    """
    domains = None if fetch_domains is None else tuple(fetch_domains)
    if isinstance(value, (bytes, bytearray)):
        value = loads_strict(value, max_bytes)
    if not isinstance(value, dict) or value.get('status') not in ('ok', 'failed'):
        raise ProtocolError('schema')
    if _size(value) > max_bytes:
        raise ProtocolError('too_large')
    if value['status'] == 'failed':
        data = _keys(value, RESULT_FAILED_KEYS)
    else:
        data = _keys(value, RESULT_OK_KEYS)
    if _integer(data['version'], 1, 1000) != PROTOCOL_VERSION or parse_rid(data['rid']) is None:
        raise ProtocolError('schema')
    if expected_rid is not None and data['rid'] != expected_rid:
        raise ProtocolError('schema')
    if data['status'] == 'failed':
        if data['reason'] not in FAILURE_REASONS:
            raise ProtocolError('schema')
        return {'version': PROTOCOL_VERSION, 'rid': data['rid'], 'status': 'failed', 'reason': data['reason']}

    result = {'version': PROTOCOL_VERSION, 'rid': data['rid'], 'status': 'ok'}
    for key, high in RESULT_LIMITS.items():
        result[key] = _text(data[key], high, 1 if key == 'summary' else 0)
    confidence = data['confidence']
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) \
            or not 0 <= confidence <= 1:
        raise ProtocolError('schema')
    result['confidence'] = float(confidence)
    if data['fix_kind'] not in FIX_KINDS:
        raise ProtocolError('schema')
    result['fix_kind'] = data['fix_kind']
    locations = []
    for item in _array(data['locations'], LOCATIONS_MAX):
        item = _keys(item, LOCATION_KEYS)
        if check_path(item['path'], None, location=True) is not None:
            raise ProtocolError('schema')
        locations.append({'path': item['path'], 'line': _integer(item['line'], 1, 10 ** 6),
                          'why': _text(item['why'], LOCATION_WHY_MAX)})
    result['locations'] = locations
    fetched = _unique(_array(data['fetched_urls'], FETCHED_URLS_MAX))
    sources = _unique(_array(data['sources'], SOURCES_MAX))
    if not all(url_ok(url, domains) for url in fetched) or not set(sources) <= set(fetched):
        raise ProtocolError('schema')
    result['sources'], result['fetched_urls'] = list(sources), list(fetched)
    result['needs_human'] = _boolean(data['needs_human'])
    result['unverified_locations'] = _integer(data['unverified_locations'], 0, 100)
    if data['mode'] not in RESULT_MODES:
        raise ProtocolError('schema')
    result['mode'] = data['mode']
    result['rounds'] = _integer(data['rounds'], 0, ROUNDS_MAX)
    return result


def failed_result(rid: str, reason: str) -> dict:
    if reason not in FAILURE_REASONS:
        raise ValueError('unknown failure reason')
    return validate_result({'version': PROTOCOL_VERSION, 'rid': rid, 'status': 'failed', 'reason': reason})


def verify_locations(locations: Iterable[Mapping], root: Path | str) -> tuple[list[dict], int]:
    """Keep the locations whose path passes `check_path(..., location=True)` under `root` and whose line is within the
    file; return (kept, number removed). The file content is only counted, never returned."""
    kept, removed = [], 0
    for item in locations:
        path, line = item.get('path'), item.get('line')
        ok = check_path(path, root, location=True) is None and isinstance(line, int) and not isinstance(line, bool)
        if ok:
            try:
                lines = line_count(read_beneath(root, path, REPO_FILE_MAX_BYTES))
            except ProtocolError:
                ok = False
            else:
                ok = 1 <= line <= lines
        if ok:
            kept.append(dict(item))
        else:
            removed += 1
    return kept, removed


def line_count(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b'\n') + (0 if data.endswith(b'\n') else 1)


# --- path allowlist (design C.2 read_file, B.8 locations) --------------------------------------------------------------

def _path_rule(rel_path: Any, location: bool) -> str | None:
    if not isinstance(rel_path, str) or not _PATH.match(rel_path):
        return 'syntax'
    if rel_path.startswith(('-', '/')) or '..' in rel_path or '//' in rel_path or rel_path.endswith('/'):
        return 'syntax'
    parts = rel_path.split('/')
    if any(part in ('', '.') or part.startswith('-') for part in parts):
        return 'syntax'
    if len(parts) == 1:
        if not (rel_path == 'main.py' or (not location and _REQUIREMENTS.match(rel_path))):
            return 'prefix'
    elif not rel_path.startswith(LOCATION_PREFIXES if location else TOOL_PREFIXES):
        return 'prefix'
    name = parts[-1].lower()
    for part in (p.lower() for p in parts):
        if part in _BLOCKED_DIRS or any(word in part for word in _BLOCKED_WORDS):
            return 'blocked'
        if set(part.split('.')[1:]) & _BLOCKED_SUFFIXES:        # x.pem, x.key, also x.pem.bak, x.key.example
            return 'blocked'
        if (part.startswith('.env') or part.endswith('.env') or '.env.' in part) \
                and not (part == name and name.endswith('.example')):
            return 'blocked'
    return None


def check_path(rel_path: Any, root: Path | str | None, *, location: bool = False) -> str | None:
    """None when `rel_path` may be read, else a code from PATH_ERRORS.

    Rules: relative, ^[A-Za-z0-9_./-]{1,200}$, no '..', no empty or '.' component, no leading '-' or '/'; prefixes
    src/ scripts/ config/ ops/ tests/ docs/ or main.py, for the tool also requirements*.txt and .venv/lib/ (locations
    never); blocked anywhere: data/, artifacts/, .git/, names with secret, token, password, credential, a .pem or
    .key name part (also x.pem.bak), .env (a final name ending in .example is allowed). With `root`: lstat of every component, no symlink, directories
    on the way, a regular file at the end, realpath under realpath(root). `root=None` checks the rules only.
    """
    rule = _path_rule(rel_path, location)
    if rule is not None or root is None:
        return rule
    base = Path(root)
    current = base
    parts = rel_path.split('/')
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            return 'missing'
        if stat.S_ISLNK(info.st_mode):
            return 'symlink'
        last = index == len(parts) - 1
        if (last and not stat.S_ISREG(info.st_mode)) or (not last and not stat.S_ISDIR(info.st_mode)):
            return 'not_regular'
    try:
        real_root = os.path.realpath(base, strict=True)
        real = os.path.realpath(current, strict=True)
    except OSError:
        return 'missing'
    if os.path.commonpath([real_root, real]) != real_root or real == real_root:
        return 'outside_root'
    return None


def path_allowed(rel_path: Any, root: Path | str | None, *, location: bool = False) -> bool:
    return check_path(rel_path, root, location=location) is None


# --- safe file I/O ---------------------------------------------------------------------------------------------------

_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)


def _open_error(error: OSError) -> ProtocolError:
    if error.errno == errno.ELOOP:
        return ProtocolError('symlink')
    if error.errno == errno.ENOTDIR:
        return ProtocolError('not_regular')
    return ProtocolError('unreadable')


def _read_fd(fd: int, *, expected_uid: int | None, max_bytes: int, single_link: bool) -> bytes:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise ProtocolError('not_regular')
    if expected_uid is not None and info.st_uid != expected_uid:
        raise ProtocolError('wrong_owner')
    if single_link and info.st_nlink != 1:
        raise ProtocolError('linked')
    if info.st_size > max_bytes:
        raise ProtocolError('too_large')
    chunks, total = [], 0
    while True:
        try:
            chunk = os.read(fd, min(65536, max_bytes + 1 - total))
        except OSError:
            raise ProtocolError('unreadable') from None
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:               # grew after fstat
            raise ProtocolError('too_large')
    return b''.join(chunks)


def safe_read(path: Path | str, expected_uid: int | None, max_bytes: int, *, single_link: bool = True) -> bytes:
    """Read a file the other side wrote: open with O_RDONLY|O_NOFOLLOW|O_NONBLOCK, then fstat: regular file, owner
    `expected_uid` (None skips that check, tests only), one link (no hard link to a foreign file), size <= max_bytes,
    all before reading; the read itself stops at max_bytes + 1. Raises ProtocolError with a fixed text."""
    try:
        fd = os.open(path, _READ_FLAGS)
    except OSError as error:
        raise _open_error(error) from None
    try:
        return _read_fd(fd, expected_uid=expected_uid, max_bytes=max_bytes, single_link=single_link)
    finally:
        os.close(fd)


def read_beneath(root: Path | str, rel_path: str, max_bytes: int = REPO_FILE_MAX_BYTES, *,
                 expected_uid: int | None = None) -> bytes:
    """Read root/rel_path walking one component at a time with O_NOFOLLOW (directories with O_DIRECTORY), so no
    component may be a symlink even if one appears after `check_path`. The path rules must pass first (tool rules,
    which include the location rules). Hard links are allowed (uv links .venv files)."""
    if _path_rule(rel_path, False) is not None:
        raise ProtocolError('bad_name')
    parts = rel_path.split('/')
    try:
        fd = os.open(root, _DIR_FLAGS)
    except OSError as error:
        raise _open_error(error) from None
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except OSError as error:
                raise _open_error(error) from None
            os.close(fd)
            fd = next_fd
        try:
            file_fd = os.open(parts[-1], _READ_FLAGS, dir_fd=fd)
        except OSError as error:
            raise _open_error(error) from None
        try:
            return _read_fd(file_fd, expected_uid=expected_uid, max_bytes=max_bytes, single_link=False)
        finally:
            os.close(file_fd)
    finally:
        os.close(fd)


def atomic_write(directory: Path | str, name: str, data: bytes, mode: int = 0o640) -> Path:
    """Write directory/name atomically: a new temp file (O_CREAT|O_EXCL|O_NOFOLLOW, `mode`, fsync) in the same
    directory, then rename over `name` and fsync the directory. The directory is opened with O_NOFOLLOW; group
    ownership follows the directory (setgid). Raises ProtocolError('bad_name' | 'write_failed')."""
    if not isinstance(name, str) or not _NAME.match(name) or not isinstance(data, (bytes, bytearray)):
        raise ProtocolError('bad_name')
    temporary = f'.{name}.{secrets.token_hex(6)}.tmp'
    try:
        dir_fd = os.open(directory, _DIR_FLAGS)
    except OSError:
        raise ProtocolError('write_failed') from None
    try:
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0),
                         mode, dir_fd=dir_fd)
        except OSError:
            raise ProtocolError('write_failed') from None
        try:
            try:
                os.fchmod(fd, mode)
                view = memoryview(bytes(data))
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.rename(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except OSError:
            try:
                os.unlink(temporary, dir_fd=dir_fd)
            except OSError:
                pass
            raise ProtocolError('write_failed') from None
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
    finally:
        os.close(dir_fd)
    return Path(directory) / name


def remove(directory: Path | str, name: str) -> bool:
    """Remove directory/name (never follows a symlink: unlink removes the link itself). True if it existed."""
    if not isinstance(name, str) or not _NAME.match(name):
        raise ProtocolError('bad_name')
    try:
        os.unlink(Path(directory) / name)
    except FileNotFoundError:
        return False
    except OSError:
        raise ProtocolError('write_failed') from None
    return True


# --- requests/ and results/ ----------------------------------------------------------------------------------------

def _names(directory: Path | str) -> list[str]:
    try:
        return os.listdir(directory)
    except OSError:
        return []


def _exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True                         # cannot tell: count it as present (fail-closed)
    return True


def list_rids(directory: Path | str, suffix: str = '.json') -> list[str]:
    """Valid rids with a `<rid><suffix>` entry in `directory`, sorted (oldest episode first). Other names are
    ignored, temp files included."""
    rids = []
    for name in _names(directory):
        if name.endswith(suffix) and parse_rid(name[:-len(suffix)]) is not None:
            rids.append(name[:-len(suffix)])
    return sorted(rids)


def pending_rids(requests_dir: Path | str, results_dir: Path | str) -> list[str]:
    """Requests without a result and without an acknowledgement, oldest first (the agent's queue)."""
    requests_dir, results_dir = Path(requests_dir), Path(results_dir)
    return [rid for rid in list_rids(requests_dir)
            if not _exists(results_dir / result_name(rid)) and not _exists(requests_dir / ack_name(rid))]


def read_request(requests_dir: Path | str, rid: str, *, expected_uid: int | None,
                 allowed_units: Iterable[str] | None = None, max_bytes: int = REQUEST_MAX_BYTES) -> dict:
    data = safe_read(Path(requests_dir) / request_name(rid), expected_uid, max_bytes)
    request = validate_request(data, allowed_units=allowed_units, max_bytes=max_bytes)
    if request['rid'] != rid:
        raise ProtocolError('schema')
    return request


def read_result(results_dir: Path | str, rid: str, *, expected_uid: int | None,
                fetch_domains: Iterable[str] | None = None, max_bytes: int = RESULT_MAX_BYTES) -> dict:
    data = safe_read(Path(results_dir) / result_name(rid), expected_uid, max_bytes)
    return validate_result(data, expected_rid=rid, fetch_domains=fetch_domains, max_bytes=max_bytes)


def write_request(requests_dir: Path | str, request: Mapping, *, allowed_units: Iterable[str] | None = None,
                  max_bytes: int = REQUEST_MAX_BYTES, mode: int = 0o640) -> Path:
    request = validate_request(dict(request), allowed_units=allowed_units, max_bytes=max_bytes)
    return atomic_write(requests_dir, request_name(request['rid']), dumps(request), mode)


def write_result(results_dir: Path | str, result: Mapping, *, fetch_domains: Iterable[str] | None = None,
                 mode: int = 0o640) -> Path:
    result = validate_result(dict(result), fetch_domains=fetch_domains)
    return atomic_write(results_dir, result_name(result['rid']), dumps(result), mode)


def write_ack(requests_dir: Path | str, rid: str, now: datetime, mode: int = 0o640) -> Path:
    return atomic_write(requests_dir, ack_name(rid), dumps({'version': PROTOCOL_VERSION, 'rid': rid,
                                                             'acked_at': iso(now)}), mode)


# --- HOLD and PAUSE ----------------------------------------------------------------------------------------------------

def hold_active(requests_dir: Path | str) -> bool:
    """requests/HOLD present in any form (even a symlink or unreadable entry): hold."""
    return _exists(Path(requests_dir) / HOLD)


def write_hold(requests_dir: Path | str, now: datetime, mode: int = 0o640) -> Path:
    return atomic_write(requests_dir, HOLD, dumps({'version': PROTOCOL_VERSION, 'at': iso(now)}), mode)


def clear_hold(requests_dir: Path | str) -> bool:
    return remove(requests_dir, HOLD)


def pause_payload(until: datetime, reason: str) -> dict:
    if reason not in PAUSE_REASONS:
        raise ValueError('unknown pause reason')
    return {'version': PROTOCOL_VERSION, 'reason': reason, 'until': iso(until)}


def write_pause(requests_dir: Path | str, until: datetime, reason: str, mode: int = 0o640) -> Path:
    return atomic_write(requests_dir, PAUSE, dumps(pause_payload(until, reason)), mode)


def clear_pause(requests_dir: Path | str) -> bool:
    return remove(requests_dir, PAUSE)


def read_pause(requests_dir: Path | str, *, expected_uid: int | None) -> dict | None:
    """The PAUSE payload, None when there is no PAUSE file. Raises ProtocolError when it exists but is not acceptable
    (callers treat that as paused)."""
    path = Path(requests_dir) / PAUSE
    if not _exists(path):
        return None
    data = _keys(loads_strict(safe_read(path, expected_uid, PAUSE_MAX_BYTES), PAUSE_MAX_BYTES),
                 ('version', 'reason', 'until'))
    if data['version'] != PROTOCOL_VERSION or data['reason'] not in PAUSE_REASONS or parse_iso(data['until']) is None:
        raise ProtocolError('schema')
    return dict(data)


def pause_active(requests_dir: Path | str, now: datetime, *, expected_uid: int | None) -> bool:
    """Fail-closed: a PAUSE that cannot be read or validated counts as active; a valid one until its 'until'."""
    try:
        pause = read_pause(requests_dir, expected_uid=expected_uid)
    except ProtocolError:
        return True
    return pause is not None and _utc(now) < parse_iso(pause['until'])
