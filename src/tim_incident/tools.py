"""Read-only tools for the Qwen incident diagnosis (design C.2 and C.3).

`build_toolbox(policy, request, root=..., runner=..., http=...)` returns a `Toolbox` with the Ollama tool schemas
and `call(name, args) -> str`. Every tool:
- validates its arguments against a typed spec (strings without a leading '-', '..' or control characters, real
  integers in range, enums from the policy); a violation gives a fixed error text, never the model's own input back;
- runs without a shell, with a fixed argv, the environment PATH/LANG/GIT_OPTIONAL_LOCKS=0 and a 15 s limit;
- returns text that passed `redaction.redact`, with '<<' and '>>' masked, framed with a per-run nonce and capped at
  `policy.agent.tool_output_chars`.

Nothing here writes, executes model text, restarts or repairs. `unit_journal` only reads the journal buffer the
checkup put into the (already redacted) request. The web part only sends words from a vocabulary, fetches only
link ids that came from earlier hits or documents on the domain list, connects only to the global IP it checked
(with SNI and Host for the name), and re-checks every redirect.

`Toolbox.call` never raises. `submit_result` is not part of this module (qwen.py appends it to `schemas`).
"""
from __future__ import annotations

import builtins
import errno
import fnmatch
import html
import http.client
import importlib
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit

from . import protocol
from .redaction import redact

UTC = timezone.utc
SERVER_ROOT = Path('/opt/tim')
PROC_MEMINFO = Path('/proc/meminfo')
DISK_PATHS = ('/', '/opt/tim', '/var', '/srv')

TOOL_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'GIT_OPTIONAL_LOCKS': '0'}
ALLOWED_COMMANDS = frozenset({'systemctl', 'timedatectl', 'git'})
COMMAND_TIMEOUT = 15.0
RAW_MAX_BYTES = 64 * 1024
FILE_MAX_BYTES = protocol.REPO_FILE_MAX_BYTES        # 1 MiB
READ_COUNT_MAX = 200
READ_COUNT_DEFAULT = 120
GREP_FILES_MAX = 2000
GREP_WALK_MAX = 50000
GREP_HITS_MAX = 50
GREP_SECONDS = 5.0
GREP_LINE_CHARS = 200
GIT_LOG_MAX = 20
JOURNAL_MINUTES_MAX = 1440
JOURNAL_LINES_MAX = 200

FETCH_MAX_BYTES = 1024 * 1024
FETCH_TIMEOUT = 15.0
MAX_REDIRECTS = 3
SEARCH_MAX_BYTES = 1024 * 1024
SEARCH_HITS_MAX = 10
SNIPPET_CHARS = 300
TITLE_CHARS = 160
WORDS_MAX = 10
WORD_CHARS = 40
DOC_LINKS_MAX = 15
LINKS_MAX = 200
CONTENT_TYPES = ('text/html', 'text/plain', 'application/json')
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64) tim-diagnose/1'
DDG_HOST = 'html.duckduckgo.com'
GITHUB_SEARCH_HOST = 'api.github.com'
BINANCE_HOST = 'api.binance.com'
BINANCE_PING = '/api/v3/ping'
DDG_FALLBACK_STATUSES = frozenset({202, 403, 429})

EXCEPTION_SCAN_FILES = 40000
EXCEPTION_SCAN_SECONDS = 20.0
EXCEPTION_CANDIDATES_MAX = 200
EXCEPTION_MODULES = ('socket', 'ssl', 'asyncio', 'concurrent.futures', 'json', 'http.client', 'subprocess',
                     'urllib.error', 'sqlite3', 'zlib', 'email.errors', 'tomllib', 'xml.parsers.expat')
SYSTEMD_RESULTS = ('success', 'protocol', 'timeout', 'exit-code', 'signal', 'core-dump', 'watchdog',
                   'start-limit-hit', 'resources', 'oom-kill', 'failed', 'activating', 'deactivating', 'inactive')

DIAGNOSE_NAMES = ('unit_status', 'list_timers', 'failed_units', 'disk_free', 'memory', 'time_sync', 'binance_ping')
DOC_KINDS = ('python_module', 'pypi_package')
TOOL_NAMES = ('read_file', 'grep_code', 'git_log', 'diagnose', 'unit_journal', 'web_search', 'web_fetch', 'web_doc')

Runner = Callable[[list[str], float], tuple[int, str]]

# Fixed texts returned to the model. `{arg}` is a key of our own argument spec, `{index}`/`{lines}` our own numbers.
ERRORS = {
    'unknown_tool': 'error: unknown tool',
    'bad_arguments': 'error: arguments must be a JSON object',
    'unknown_argument': 'error: unknown argument',
    'missing_argument': 'error: missing argument {arg}',
    'not_string': 'error: argument {arg} must be a string',
    'bad_string': 'error: argument {arg} has a forbidden form (leading "-", "..", control characters or charset)',
    'bad_length': 'error: argument {arg} has the wrong length',
    'not_integer': 'error: argument {arg} must be an integer',
    'out_of_range': 'error: argument {arg} is out of range',
    'not_allowed': 'error: argument {arg} is not one of the allowed values',
    'not_list': 'error: argument {arg} must be a list of strings',
    'path_syntax': 'error: path not allowed (form)',
    'path_prefix': 'error: path not allowed (only src/ scripts/ config/ ops/ tests/ docs/ main.py requirements*.txt '
                   '.venv/lib/)',
    'path_blocked': 'error: path not allowed (blocked name)',
    'path_missing': 'error: file not found',
    'path_symlink': 'error: path not allowed (symlink)',
    'path_not_regular': 'error: not a regular file',
    'path_outside_root': 'error: path not allowed (outside the repository)',
    'too_large': 'error: file too large',
    'unreadable': 'error: file not readable',
    'not_utf8': 'error: file is not UTF-8 text',
    'start_beyond_end': 'error: start is beyond the end of the file ({lines} lines)',
    'git_disabled': 'error: git_log is disabled (ownership of the repository not confirmed)',
    'unit_required': 'error: unit_status needs the argument unit',
    'command_timeout': 'error: command timed out',
    'command_missing': 'error: command not available',
    'command_failed': 'error: command failed',
    'no_journal': 'error: the request holds no journal for this unit',
    'search_limit': 'error: search limit reached',
    'search_vocabulary': 'error: word {index} is not in the allowed vocabulary',
    'search_failed': 'error: search failed',
    'fetch_limit': 'error: fetch limit reached',
    'unknown_link': 'error: unknown link id (use an id from an earlier search hit or document)',
    'fetch_blocked': 'error: fetch blocked (address or redirect target not allowed)',
    'fetch_failed': 'error: fetch failed',
    'fetch_status': 'error: fetch returned an unexpected HTTP status',
    'fetch_too_large': 'error: document too large',
    'fetch_type': 'error: content type not allowed',
    'too_many_redirects': 'error: too many redirects',
    'doc_unknown': 'error: unknown module or package name',
    'web_disabled': 'error: web tools are disabled',
    'internal': 'error: internal tool error',
}


class ToolError(Exception):
    """A tool refused; `text()` is the fixed message for the model."""

    def __init__(self, code: str, **values: Any):
        self.code = code if code in ERRORS else 'internal'
        self.values = values
        super().__init__(self.code)

    def text(self) -> str:
        try:
            return ERRORS[self.code].format(**self.values)
        except (KeyError, IndexError, ValueError):
            return ERRORS['internal']


# --- subprocess --------------------------------------------------------------------------------------------------------

def default_runner(argv: list[str], timeout: float) -> tuple[int, str]:
    """Fixed argv, no shell, environment TOOL_ENV only, stdin closed, stderr merged, output capped at RAW_MAX_BYTES.
    Never raises for a run: timeout gives (124, ''), a missing binary (127, '')."""
    if not isinstance(argv, list) or not argv or argv[0] not in ALLOWED_COMMANDS:
        raise ValueError('command not allowed')
    if not all(isinstance(part, str) and '\0' not in part for part in argv):
        raise ValueError('invalid argument')
    try:
        completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   env=dict(TOOL_ENV), timeout=timeout, check=False, cwd='/')
    except subprocess.TimeoutExpired:
        return 124, ''
    except OSError:
        return 127, ''
    return completed.returncode, completed.stdout[:RAW_MAX_BYTES].decode('utf-8', 'replace')


# --- HTTP layer ----------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]          # lower-case names
    body: bytes                         # at most max_bytes + 1 bytes


class HttpTransport:
    """Network access for the web tools: `resolve(host)` -> list of IP strings, `get(ip, host, target, ...)` -> one
    HTTPS GET to exactly `ip` on port 443, TLS with SNI and certificate check for `host`, Host header `host`, no
    redirects followed, no proxy. Tests replace `get` (and patch getaddrinfo); the IP checks are in the toolbox."""

    def resolve(self, host: str) -> list[str]:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        return [str(info[4][0]) for info in infos]

    def get(self, ip: str, host: str, target: str, *, headers: Mapping[str, str], timeout: float,
            max_bytes: int) -> HttpResponse:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        deadline = time.monotonic() + timeout
        raw = socket.create_connection((ip, 443), timeout=timeout)
        try:
            sock = context.wrap_socket(raw, server_hostname=host)
        except BaseException:
            raw.close()
            raise
        connection = http.client.HTTPSConnection(host, 443, timeout=timeout, context=context)
        connection.sock = sock
        try:
            connection.request('GET', target, headers=dict(headers))
            response = connection.getresponse()
            names = {name.lower(): value for name, value in response.getheaders()}
            chunks, total = [], 0
            if response.status == 200:
                while total <= max_bytes:
                    if time.monotonic() > deadline:
                        raise TimeoutError('fetch deadline')
                    chunk = response.read(min(65536, max_bytes + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
            return HttpResponse(response.status, names, b''.join(chunks))
        finally:
            connection.close()


_NAT64 = ipaddress.ip_network('64:ff9b::/96')


def global_ip(text: Any) -> str | None:
    """The address as a string when it is a global unicast address (also through IPv4-mapped, 6to4, Teredo or NAT64
    forms), else None."""
    if not isinstance(text, str):
        return None
    try:
        address = ipaddress.ip_address(text.split('%', 1)[0])
    except ValueError:
        return None
    if address.version == 6:
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif address.sixtofour is not None or address.teredo is not None or address in _NAT64:
            return None
    if (not address.is_global or address.is_private or address.is_loopback or address.is_link_local
            or address.is_multicast or address.is_reserved or address.is_unspecified):
        return None
    return str(address)


def normalize_url(url: Any) -> str | None:
    """https://host/path with the fragment dropped and the host lower-cased; None for any other form (query string,
    port, userinfo, other scheme). The result still has to pass `protocol.url_ok`."""
    if not isinstance(url, str) or len(url) > 470:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() != 'https' or parts.query or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None or parts.netloc.lower() != parts.hostname:
        return None
    return f'https://{parts.hostname.lower()}{parts.path}'


# --- text helpers --------------------------------------------------------------------------------------------------------

_CONTROL = re.compile('[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2028\u2029\u2066-\u2069\ufeff]')
_OPEN = re.compile(r'<(?=<)')
_CLOSE = re.compile(r'>(?=>)')
_BLANKS = re.compile(r'\n[ \t]*\n(?:[ \t]*\n)+')
_SPACES = re.compile(r'[ \t\f\v\r]+')
TRUNCATED = '\n[truncated]'


def escape_delimiters(text: str) -> str:
    """'<<' and '>>' never survive, so content cannot close or fake a frame: '<<<' becomes '< < <'."""
    return _CLOSE.sub('> ', _OPEN.sub('< ', text))


def clean_text(text: str) -> str:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return _CONTROL.sub('', text)


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:max(0, limit - len(TRUNCATED))] + TRUNCATED


def frame(kind: str, nonce: str, label: str, body: str, limit: int) -> str:
    """Redact, mask delimiters, cap and frame `body`: <<KIND-nonce label>> ... <<END_KIND-nonce>>, at most `limit`
    characters in all. `kind` and `label` are our own words."""
    head = f'<<{kind}-{nonce} {label}>>\n'
    tail = f'\n<<END_{kind}-{nonce}>>'
    content = escape_delimiters(redact(clean_text(body)))
    return head + _cap(content, max(0, limit - len(head) - len(tail))) + tail


class _HtmlText(HTMLParser):
    """HTML to plain text plus the href of every <a>. Script, style and similar content is dropped."""

    SKIP = frozenset({'script', 'style', 'noscript', 'svg', 'template', 'iframe', 'object', 'canvas'})
    BLOCK = frozenset({'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'section', 'article',
                       'header', 'footer', 'table', 'ul', 'ol', 'dt', 'dd', 'blockquote', 'title', 'hr'})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append('\n')
        if tag == 'a' and len(self.links) < LINKS_MAX:
            href = dict(attrs).get('href')
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (_SPACES.sub(' ', line).strip() for line in ''.join(self.parts).split('\n'))
        return _BLANKS.sub('\n\n', '\n'.join(lines)).strip()


def html_to_text(markup: str) -> tuple[str, list[str]]:
    parser = _HtmlText()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:                   # malformed markup: keep what was parsed
        pass
    return parser.text(), parser.links


class _DdgResults(HTMLParser):
    """Hits of the DuckDuckGo HTML page: <a class="result__a" href=...>title</a> and class result__snippet."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hits: list[dict] = []
        self._field: str | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = (values.get('class') or '').split()
        if tag == 'a' and 'result__a' in classes:
            self.hits.append({'url': values.get('href') or '', 'title': '', 'snippet': ''})
            self._field = 'title'
        elif 'result__snippet' in classes and self.hits:
            self._field = 'snippet'

    def handle_endtag(self, tag):
        if tag in ('a', 'div', 'td'):
            self._field = None

    def handle_data(self, data):
        if self._field and self.hits:
            self.hits[-1][self._field] += data


def _ddg_target(href: str) -> str:
    if href.startswith('//'):
        href = 'https:' + href
    try:
        parts = urlsplit(href)
    except ValueError:
        return ''
    if parts.hostname and parts.hostname.endswith('duckduckgo.com') and parts.path.startswith('/l/'):
        return (parse_qs(parts.query).get('uddg') or [''])[0]
    return href


def parse_ddg(markup: str) -> list[dict]:
    parser = _DdgResults()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:
        pass
    hits = []
    for hit in parser.hits:
        url = _ddg_target(hit['url'])
        if 'duckduckgo.com/y.js' in url:            # advertising
            continue
        hits.append({'url': url, 'title': hit['title'].strip(), 'snippet': hit['snippet'].strip()})
    return hits[:SEARCH_HITS_MAX]


def parse_github_issues(data: bytes) -> list[dict]:
    try:
        value = json.loads(data.decode('utf-8', 'replace'))
    except ValueError:
        return []
    items = value.get('items') if isinstance(value, dict) else None
    hits = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        hits.append({'url': item.get('html_url') if isinstance(item.get('html_url'), str) else '',
                     'title': item.get('title') if isinstance(item.get('title'), str) else '',
                     'snippet': item.get('body') if isinstance(item.get('body'), str) else ''})
    return hits[:SEARCH_HITS_MAX]


def _charset(content_type: str) -> str:
    match = re.search(r'charset=["\']?([A-Za-z0-9._-]{1,40})', content_type or '')
    if match:
        try:
            b'x'.decode(match.group(1))             # also rejects codecs that are not text encodings (rot13)
            return match.group(1)
        except (LookupError, ValueError):
            pass
    return 'utf-8'


def text_lines(text: str) -> list[str]:
    """Lines split at '\\n' only, numbered like protocol.line_count (locations are verified with that count)."""
    if not text:
        return []
    lines = text.split('\n')
    return lines[:-1] if text.endswith('\n') else lines


# --- vocabulary (design C.3) -----------------------------------------------------------------------------------------------

_WORD = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.+-]{0,39}$')
_CANDIDATE = re.compile(r'(?<![A-Za-z0-9_])([A-Z][A-Za-z0-9_]{2,39}|[a-z][a-z0-9_]{0,30}error)(?![A-Za-z0-9_])')
ERRNO_NAMES = frozenset(errno.errorcode.values())


def exception_candidates(texts: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for text in texts:
        for match in _CANDIDATE.finditer(text):
            found.add(match.group(1))
            if len(found) >= EXCEPTION_CANDIDATES_MAX:
                return found
    return found


def _is_exception(value: Any) -> bool:
    return isinstance(value, type) and issubclass(value, BaseException)


def known_exceptions(candidates: set[str]) -> set[str]:
    """The candidates that are exception classes of builtins or a few stdlib modules."""
    known = {name for name in candidates if _is_exception(getattr(builtins, name, None))}
    for module_name in EXCEPTION_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        known.update(name for name in candidates if _is_exception(getattr(module, name, None)))
    return known


def _site_packages(root: Path) -> list[str]:
    lib = root / '.venv' / 'lib'
    try:
        names = sorted(entry for entry in os.listdir(lib) if re.match(r'^python3\.\d{1,2}$', entry))
    except OSError:
        return []
    return [f'.venv/lib/{name}/site-packages' for name in names]


def defined_classes(root: Path, candidates: set[str], *, clock: Callable[[], float] = time.monotonic,
                    max_files: int = EXCEPTION_SCAN_FILES, max_seconds: float = EXCEPTION_SCAN_SECONDS) -> set[str]:
    """The candidates defined as `class <Name>` in root/src or the .venv site-packages. One pass over the .py files,
    no symlinks followed, bounded in files and time (when a bound hits, fewer words are allowed: fail-closed)."""
    if not candidates:
        return set()
    pattern = re.compile(rb'^[ \t]*class[ \t]+(' + b'|'.join(re.escape(name.encode()) for name in
                                                              sorted(candidates)) + rb')\b', re.M)
    found: set[str] = set()
    started, seen = clock(), 0
    for top in ['src'] + _site_packages(root):
        for rel in _walk(root, top):
            if not rel.endswith('.py'):
                continue
            seen += 1
            if seen > max_files or clock() - started > max_seconds or found >= candidates:
                return found
            if protocol.check_path(rel, None) is not None:
                continue
            try:
                data = protocol.read_beneath(root, rel, FILE_MAX_BYTES)
            except protocol.ProtocolError:
                continue
            found.update(match.group(1).decode() for match in pattern.finditer(data))
    return found


def _walk(root: Path, top: str) -> Iterable[str]:
    """Relative file paths under root/top in sorted order; symlinked directories are not entered, blocked
    directory names are pruned."""
    base = root / top
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if _dir_ok(name))
        rel_dir = os.path.relpath(dirpath, root)
        for name in sorted(filenames):
            yield f'{rel_dir}/{name}'.replace(os.sep, '/')


def _dir_ok(name: str) -> bool:
    lower = name.lower()
    return name != '__pycache__' and not lower.startswith(('.env', '-')) and \
        protocol._path_rule(f'src/{name}/x.py', False) is None


# --- argument specs ------------------------------------------------------------------------------------------------------

_PATH_ARG = re.compile(r'^[A-Za-z0-9_./-]{1,200}$')
_GLOB_ARG = re.compile(r'^[A-Za-z0-9_*./-]{1,64}$')
_LINK_ARG = re.compile(r'^L[1-9][0-9]{0,3}$')
_NAME_ARG = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
_TEXT_BAD = re.compile('[\x00-\x1f\x7f\u2028\u2029]')


@dataclass(frozen=True)
class Arg:
    kind: str                       # 'str' | 'int' | 'enum' | 'words'
    low: int = 0
    high: int = 0
    pattern: re.Pattern[str] | None = None
    values: tuple[str, ...] = ()
    required: bool = True
    default: Any = None
    description: str = ''


def _check_string(name: str, value: Any, spec: Arg) -> str:
    if not isinstance(value, str):
        raise ToolError('not_string', arg=name)
    if not spec.low <= len(value) <= spec.high:
        raise ToolError('bad_length', arg=name)
    if value.startswith('-') or '..' in value or _TEXT_BAD.search(value) or value != value.strip():
        raise ToolError('bad_string', arg=name)
    if spec.pattern is not None and not spec.pattern.match(value):
        raise ToolError('bad_string', arg=name)
    return value


def validate_args(specs: Mapping[str, Arg], args: Any) -> dict:
    """Typed check of the model's arguments. Raises ToolError with a fixed text; returns a fresh dict with defaults."""
    if isinstance(args, (str, bytes)):
        if len(args) > 8192:
            raise ToolError('bad_arguments')
        try:
            args = json.loads(args)
        except ValueError:
            raise ToolError('bad_arguments') from None
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError('bad_arguments')
    if any(key not in specs for key in args):
        raise ToolError('unknown_argument')
    result = {}
    for name, spec in specs.items():
        if name not in args or args[name] is None:
            if spec.required:
                raise ToolError('missing_argument', arg=name)
            result[name] = spec.default
            continue
        value = args[name]
        if spec.kind == 'int':
            if isinstance(value, bool) or not isinstance(value, int):
                raise ToolError('not_integer', arg=name)
            if not spec.low <= value <= spec.high:
                raise ToolError('out_of_range', arg=name)
        elif spec.kind == 'enum':
            if not isinstance(value, str):
                raise ToolError('not_string', arg=name)
            if value not in spec.values:
                raise ToolError('not_allowed', arg=name)
        elif spec.kind == 'words':
            if not isinstance(value, list) or not spec.low <= len(value) <= spec.high:
                raise ToolError('not_list', arg=name)
            value = [_check_string(name, item, Arg('str', 1, WORD_CHARS, _WORD)) for item in value]
        else:
            value = _check_string(name, value, spec)
        result[name] = value
    return result


def _schema(name: str, description: str, specs: Mapping[str, Arg]) -> dict:
    properties = {}
    for arg, spec in specs.items():
        if spec.kind == 'int':
            prop = {'type': 'integer', 'minimum': spec.low, 'maximum': spec.high}
        elif spec.kind == 'enum':
            prop = {'type': 'string', 'enum': list(spec.values)}
        elif spec.kind == 'words':
            prop = {'type': 'array', 'items': {'type': 'string', 'maxLength': WORD_CHARS},
                    'minItems': spec.low, 'maxItems': spec.high}
        else:
            prop = {'type': 'string', 'minLength': spec.low, 'maxLength': spec.high}
        if spec.description:
            prop['description'] = spec.description
        properties[arg] = prop
    return {'type': 'function', 'function': {
        'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': properties,
                       'required': [arg for arg, spec in specs.items() if spec.required]}}}


# --- journal timestamps ------------------------------------------------------------------------------------------------

_JOURNAL_TIME = re.compile(r'^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:[.,]\d+)?(Z|[+-]\d{2}:?\d{2})?')


def journal_time(line: str) -> datetime | None:
    match = _JOURNAL_TIME.match(line)
    if not match:
        return None
    zone = match.group(3) or 'Z'
    if zone != 'Z' and ':' not in zone:
        zone = zone[:3] + ':' + zone[3:]
    try:
        return datetime.fromisoformat(f'{match.group(1)}T{match.group(2)}{"+00:00" if zone == "Z" else zone}')
    except ValueError:
        return None


# --- the toolbox -----------------------------------------------------------------------------------------------------------

class Toolbox:
    """The tools of one diagnosis run. Build it with `build_toolbox`.

    - `schemas`: list of Ollama tool definitions, in a fixed order (stable prompt prefix for the cache).
    - `call(name, args) -> str`: never raises; the text is framed and capped, or a fixed error.
    - `fetched_urls`: https URLs read so far (requested and final after redirects); `sources` must be a subset.
    - `last_status`: 'ok' or 'error:<code>' of the last call (for the agent log).
    """

    def __init__(self, policy, request: Mapping, *, root: Path, runner: Runner, http: HttpTransport | None,
                 root_owned: bool, web: bool, clock: Callable[[], float], sleep: Callable[[float], None],
                 nonce: str, distributions: Iterable[str] | None, statvfs: Callable[[str], Any],
                 exception_index: set[str] | None):
        agent = policy.agent
        self.agent = agent
        self.request = request
        self.root = Path(root)
        self.runner = runner
        self.http = http
        self.root_owned = root_owned
        self.web = web and http is not None
        self.clock = clock
        self.sleep = sleep
        self.nonce = nonce
        self.statvfs = statvfs
        self.limit = int(agent.tool_output_chars)
        self.domains = tuple(agent.fetch_domains)
        self.vocabulary = frozenset(agent.query_vocabulary)
        self.units = tuple(agent.units_allowlist)
        journal = request.get('journal') or {}
        self.journal_units = tuple(unit for unit in request.get('units') or () if unit in journal and
                                   unit in self.units)
        self.fetched_urls: list[str] = []
        self.searches = 0
        self.fetches = 0
        self.last_status = 'ok'
        self._last_search: float | None = None
        self._links: dict[str, str] = {}
        self._link_ids: dict[str, str] = {}
        self._distributions = None if distributions is None else frozenset(_dist_name(n) for n in distributions)
        self._exceptions = exception_index
        self._specs = self._build_specs()
        self.schemas = [_schema(name, description, specs) for name, (description, specs) in self._specs.items()]
        self.names = tuple(self._specs)

    # -- schema --------------------------------------------------------------------------------------------------------

    def _build_specs(self) -> dict[str, tuple[str, dict[str, Arg]]]:
        path = Arg('str', 1, 200, _PATH_ARG, description='repository path, e.g. src/data_ingestion/catchup.py')
        specs: dict[str, tuple[str, dict[str, Arg]]] = {
            'read_file': ('Read lines of a repository file (read-only, numbered).', {
                'path': path,
                'start': Arg('int', 1, 10 ** 6, required=False, default=1),
                'count': Arg('int', 1, READ_COUNT_MAX, required=False, default=READ_COUNT_DEFAULT)}),
            'grep_code': ('Search a fixed string (no regex) in repository files matching a glob.', {
                'text': Arg('str', 3, 100),
                'glob': Arg('str', 1, 64, _GLOB_ARG, required=False, default='*.py',
                            description='fnmatch pattern on the relative path, e.g. src/*.py')}),
        }
        if self.root_owned:
            specs['git_log'] = ('Recent commits touching a repository path.', {
                'path': path, 'n': Arg('int', 1, GIT_LOG_MAX, required=False, default=10)})
        specs['diagnose'] = ('Read-only system facts: ' + ', '.join(DIAGNOSE_NAMES) + '.', {
            'name': Arg('enum', values=DIAGNOSE_NAMES),
            'unit': Arg('enum', values=self.units, required=False)})
        if self.journal_units:
            specs['unit_journal'] = ('Journal lines of a unit from the incident evidence (already redacted).', {
                'unit': Arg('enum', values=self.journal_units),
                'since_minutes': Arg('int', 1, JOURNAL_MINUTES_MAX, required=False, default=60),
                'max_lines': Arg('int', 1, JOURNAL_LINES_MAX, required=False, default=100)})
        if self.web:
            specs['web_search'] = ('Web search with words from a fixed vocabulary (also errno names and exception '
                                   'names from the evidence). Hits get link ids.', {
                                       'words': Arg('words', 1, WORDS_MAX)})
            specs['web_fetch'] = ('Fetch a document by a link id from an earlier hit or document.', {
                'link_id': Arg('str', 2, 5, _LINK_ARG)})
            specs['web_doc'] = ('Fetch the Python docs page of a stdlib module or the PyPI page of an installed '
                                'package.', {
                                    'kind': Arg('enum', values=DOC_KINDS),
                                    'name': Arg('str', 1, 80, _NAME_ARG)})
        return specs

    # -- dispatch ------------------------------------------------------------------------------------------------------

    def call(self, name: Any, args: Any) -> str:
        try:
            if not isinstance(name, str) or name not in self._specs:
                if name == 'git_log':
                    raise ToolError('git_disabled')
                if name in TOOL_NAMES:
                    raise ToolError('web_disabled' if name.startswith('web_') else 'unknown_tool')
                raise ToolError('unknown_tool')
            values = validate_args(self._specs[name][1], args)
            text = getattr(self, '_tool_' + name)(**values)
        except ToolError as error:
            self.last_status = 'error:' + error.code
            return error.text()
        except Exception:
            self.last_status = 'error:internal'
            return ERRORS['internal']
        self.last_status = 'ok'
        return text

    def _frame(self, body: str, label: str, kind: str = 'UNTRUSTED_TOOL') -> str:
        return frame(kind, self.nonce, label, body, self.limit)

    # -- repository ----------------------------------------------------------------------------------------------------

    def _checked(self, path: str) -> None:
        code = protocol.check_path(path, self.root)
        if code is not None:
            raise ToolError('path_' + code)

    def _read(self, path: str) -> str:
        self._checked(path)
        try:
            data = protocol.read_beneath(self.root, path, FILE_MAX_BYTES)
        except protocol.ProtocolError as error:
            raise ToolError('too_large' if error.code == 'too_large' else
                            'path_symlink' if error.code == 'symlink' else 'unreadable') from None
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            raise ToolError('not_utf8') from None

    def _tool_read_file(self, path: str, start: int, count: int) -> str:
        lines = text_lines(self._read(path))
        if lines and start > len(lines):
            raise ToolError('start_beyond_end', lines=len(lines))
        chosen = lines[start - 1:start - 1 + count]
        body = '\n'.join(f'{start + index:>6}  {line}' for index, line in enumerate(chosen))
        end = start + len(chosen) - 1
        return self._frame(body, f'tool=read_file path={path} lines={start}-{end} of={len(lines)}')

    def _grep_files(self, glob: str) -> Iterable[str]:
        try:
            top_names = sorted(os.listdir(self.root))
        except OSError:
            top_names = []
        for name in top_names:
            if protocol._path_rule(name, False) is None:
                yield name
        tops = [prefix.rstrip('/') for prefix in protocol.TOOL_PREFIXES if prefix != '.venv/lib/']
        if glob.startswith('.venv/'):
            tops.append('.venv/lib')
        for top in tops:
            yield from _walk(self.root, top)

    def _tool_grep_code(self, text: str, glob: str) -> str:
        started = self.clock()
        hits, files, walked, stopped = [], 0, 0, ''
        for rel in self._grep_files(glob):
            walked += 1
            if walked > GREP_WALK_MAX or self.clock() - started > GREP_SECONDS:
                stopped = 'time or walk limit'
                break
            if not fnmatch.fnmatchcase(rel, glob) or protocol.check_path(rel, self.root) is not None:
                continue
            files += 1
            if files > GREP_FILES_MAX:
                stopped = 'file limit'
                break
            try:
                content = protocol.read_beneath(self.root, rel, FILE_MAX_BYTES).decode('utf-8')
            except (protocol.ProtocolError, UnicodeDecodeError):
                continue
            if text not in content:
                continue
            for number, line in enumerate(text_lines(content), 1):
                if text in line:
                    hits.append(f'{rel}:{number}: {line.strip()[:GREP_LINE_CHARS]}')
                    if len(hits) >= GREP_HITS_MAX:
                        break
            if len(hits) >= GREP_HITS_MAX:
                stopped = 'hit limit'
                break
        body = '\n'.join(hits) if hits else 'no matches'
        if stopped:
            body += f'\n[stopped: {stopped}]'
        return self._frame(body, f'tool=grep_code files={min(files, GREP_FILES_MAX)} hits={len(hits)}')

    def _tool_git_log(self, path: str, n: int) -> str:
        if not self.root_owned:
            raise ToolError('git_disabled')
        self._checked(path)
        root = str(self.root)
        argv = ['git', '--no-pager', '-c', f'safe.directory={root}', '-c', 'core.fsmonitor=false', '-c',
                'log.showSignature=false', '-C', root, 'log', '--oneline', '--no-color', '-n', str(n), '--', path]
        code, text = self._run(argv)
        if code != 0:
            raise ToolError('command_failed')
        return self._frame(text or 'no commits', f'tool=git_log path={path}')

    # -- system ----------------------------------------------------------------------------------------------------------

    def _run(self, argv: list[str]) -> tuple[int, str]:
        try:
            code, text = self.runner(list(argv), COMMAND_TIMEOUT)
        except Exception:
            raise ToolError('command_failed') from None
        if code == 124:
            raise ToolError('command_timeout')
        if code == 127:
            raise ToolError('command_missing')
        text = text if isinstance(text, str) else ''
        return (code if isinstance(code, int) else 1), text[:RAW_MAX_BYTES]

    def _tool_diagnose(self, name: str, unit: str | None) -> str:
        if name == 'unit_status':
            if unit is None:
                raise ToolError('unit_required')
            code, text = self._run(['systemctl', 'status', unit, '--no-pager', '--lines=0'])
            body = f'exit {code}\n{text}'
        elif name == 'list_timers':
            code, text = self._run(['systemctl', 'list-timers', '--all', '--no-pager'])
            body = f'exit {code}\n{text}'
        elif name == 'failed_units':
            code, text = self._run(['systemctl', 'list-units', '--failed', '--no-pager', '--plain'])
            body = f'exit {code}\n{text}'
        elif name == 'time_sync':
            code, text = self._run(['timedatectl', 'show'])
            body = f'exit {code}\n{text}'
        elif name == 'disk_free':
            body = self._disk_free()
        elif name == 'memory':
            body = self._memory()
        else:
            body = self._binance_ping()
        label = f'tool=diagnose name={name}' + (f' unit={unit}' if name == 'unit_status' else '')
        return self._frame(body, label)

    def _disk_free(self) -> str:
        lines = []
        for path in DISK_PATHS:
            try:
                info = self.statvfs(path)
                total, free = info.f_blocks * info.f_frsize, info.f_bavail * info.f_frsize
                inodes_free = info.f_favail
            except (OSError, AttributeError, TypeError):
                lines.append(f'{path}: not available')
                continue
            used = 0 if not total else round(100 * (total - free) / total, 1)
            lines.append(f'{path}: {used} % used, {free} bytes free, {inodes_free} inodes free')
        return '\n'.join(lines)

    def _memory(self) -> str:
        wanted = ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree', 'Dirty', 'Writeback')
        try:
            data = PROC_MEMINFO.read_bytes()[:RAW_MAX_BYTES].decode('ascii', 'replace')
        except OSError:
            raise ToolError('command_failed') from None
        lines = [line for line in data.splitlines() if line.split(':', 1)[0] in wanted]
        return '\n'.join(lines) or 'not available'

    def _binance_ping(self) -> str:
        if self.http is None:
            raise ToolError('web_disabled')
        started = self.clock()
        try:
            response = self._get_fixed(BINANCE_HOST, BINANCE_PING, accept='application/json', max_bytes=4096)
        except ToolError as error:
            return f'binance_ping: failed ({error.code})'
        return f'binance_ping: HTTP {response.status} after {int((self.clock() - started) * 1000)} ms'

    # -- journal from the request -------------------------------------------------------------------------------------

    def _tool_unit_journal(self, unit: str, since_minutes: int, max_lines: int) -> str:
        if unit not in self.journal_units:
            raise ToolError('no_journal')
        lines = [line for line in self.request['journal'].get(unit) or () if isinstance(line, str)]
        reference = protocol.parse_iso(self.request.get('created_at'))
        if reference is not None:
            cutoff = reference - timedelta(minutes=since_minutes)
            kept, current = [], None
            for line in lines:
                moment = journal_time(line)
                current = moment if moment is not None else current
                if current is None or current >= cutoff:
                    kept.append(line)
            lines = kept
        lines = lines[-max_lines:]
        return self._frame('\n'.join(lines) or 'no lines in this window',
                           f'tool=unit_journal unit={unit} lines={len(lines)}')

    # -- web ---------------------------------------------------------------------------------------------------------------

    def _resolve(self, host: str) -> str:
        try:
            addresses = self.http.resolve(host)
        except (OSError, UnicodeError, ValueError):
            raise ToolError('fetch_failed') from None
        if not addresses:
            raise ToolError('fetch_failed')
        checked = [global_ip(address) for address in addresses]
        if any(address is None for address in checked):          # one private answer spoils the name (rebinding)
            raise ToolError('fetch_blocked')
        return checked[0]

    def _exchange(self, host: str, target: str, *, accept: str, max_bytes: int) -> HttpResponse:
        ip = self._resolve(host)
        headers = {'User-Agent': USER_AGENT, 'Accept': accept, 'Accept-Encoding': 'identity', 'Connection': 'close'}
        try:
            response = self.http.get(ip, host, target, headers=headers, timeout=FETCH_TIMEOUT, max_bytes=max_bytes)
        except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError, ValueError):
            raise ToolError('fetch_failed') from None
        if not isinstance(response, HttpResponse):
            raise ToolError('fetch_failed')
        return response

    def _checked_body(self, response: HttpResponse, max_bytes: int) -> tuple[str, bytes]:
        if response.status != 200:
            raise ToolError('fetch_status')
        content_type = (response.headers.get('content-type') or '').strip()
        main = content_type.split(';', 1)[0].strip().lower()
        if main not in CONTENT_TYPES:
            raise ToolError('fetch_type')
        length = response.headers.get('content-length')
        if length is not None and (not length.strip().isdigit() or int(length) > max_bytes):
            raise ToolError('fetch_too_large')
        if len(response.body) > max_bytes:
            raise ToolError('fetch_too_large')
        return content_type, response.body

    def _get_fixed(self, host: str, target: str, *, accept: str, max_bytes: int) -> HttpResponse:
        """A request to a fixed host of our own (search, binance ping): no redirects followed."""
        return self._exchange(host, target, accept=accept, max_bytes=max_bytes)

    def _fetch(self, url: str) -> tuple[str, str, bytes]:
        """GET an allowed URL, following at most MAX_REDIRECTS redirects, each re-checked (domain list, path form,
        global IP). Returns (final URL, content type, body)."""
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            if not protocol.url_ok(current, self.domains):
                raise ToolError('fetch_blocked')
            parts = urlsplit(current)
            response = self._exchange(parts.hostname, parts.path or '/',
                                      accept='text/html, text/plain, application/json', max_bytes=FETCH_MAX_BYTES)
            if response.status in REDIRECT_STATUSES:
                if hop == MAX_REDIRECTS:
                    raise ToolError('too_many_redirects')
                location = response.headers.get('location')
                target = normalize_url(urljoin(current, location)) if isinstance(location, str) else None
                if target is None or not protocol.url_ok(target, self.domains):
                    raise ToolError('fetch_blocked')
                current = target
                continue
            content_type, body = self._checked_body(response, FETCH_MAX_BYTES)
            return current, content_type, body
        raise ToolError('too_many_redirects')

    def _link_id(self, url: str) -> str | None:
        """Id for an allowed URL (same URL, same id); None for anything off the list or after LINKS_MAX ids."""
        target = normalize_url(url)
        if target is None or not protocol.url_ok(target, self.domains):
            return None
        if target in self._link_ids:
            return self._link_ids[target]
        if len(self._links) >= LINKS_MAX:
            return None
        ident = f'L{len(self._links) + 1}'
        self._links[ident] = target
        self._link_ids[target] = ident
        return ident

    def allowed_words(self) -> tuple[frozenset[str], set[str]]:
        if self._exceptions is None:
            texts = [self.request.get('evidence') or '']
            for lines in (self.request.get('journal') or {}).values():
                texts.extend(line for line in lines if isinstance(line, str))
            candidates = exception_candidates(texts)
            index = known_exceptions(candidates)
            index |= defined_classes(self.root, candidates - index, clock=self.clock)
            self._exceptions = {name for name in index if len(name) <= WORD_CHARS}
        return self.vocabulary, self._exceptions

    def word_allowed(self, word: str) -> bool:
        vocabulary, exceptions = self.allowed_words()
        if word.lower() in vocabulary or word in exceptions or word in ERRNO_NAMES:
            return True
        return word.lower() in SYSTEMD_RESULTS and word == word.lower()

    def _tool_web_search(self, words: list[str]) -> str:
        if self.searches >= self.agent.max_searches:
            raise ToolError('search_limit')
        for index, word in enumerate(words, 1):
            if not self.word_allowed(word):
                raise ToolError('search_vocabulary', index=index)
        query = ' '.join(word if word in ERRNO_NAMES or word in (self._exceptions or ()) else word.lower()
                         for word in words)
        if self._last_search is not None:
            wait = self.agent.search_interval_seconds - (self.clock() - self._last_search)
            if wait > 0:
                self.sleep(wait)
        self.searches += 1
        self._last_search = self.clock()
        hits, engine = None, 'duckduckgo'
        try:
            response = self._get_fixed(DDG_HOST, '/html/?q=' + quote_plus(query), accept='text/html',
                                       max_bytes=SEARCH_MAX_BYTES)
            if response.status not in DDG_FALLBACK_STATUSES:
                content_type, body = self._checked_body(response, SEARCH_MAX_BYTES)
                hits = parse_ddg(body.decode(_charset(content_type), 'replace'))
        except ToolError:
            hits = None
        if hits is None:
            engine = 'github'
            try:
                response = self._get_fixed(GITHUB_SEARCH_HOST, '/search/issues?per_page=10&q=' + quote_plus(query),
                                           accept='application/vnd.github+json', max_bytes=SEARCH_MAX_BYTES)
                _, body = self._checked_body(response, SEARCH_MAX_BYTES)
                hits = parse_github_issues(body)
            except ToolError:
                raise ToolError('search_failed') from None
        blocks = []
        for hit in hits[:SEARCH_HITS_MAX]:
            title = _one_line(hit.get('title') or '')[:TITLE_CHARS]
            snippet = _one_line(hit.get('snippet') or '')[:SNIPPET_CHARS]
            ident = self._link_id(hit.get('url') or '')
            if ident is not None:
                blocks.append(f'[{ident}] {title}\n{self._links[ident]}\n{snippet}')
            else:
                blocks.append(f'[no link: not on the domain list] {title}\n{snippet}')
        body = '\n\n'.join(blocks) if blocks else 'no results'
        return self._frame(body, f'id=search-{self.searches} engine={engine} hits={len(blocks)}', 'UNTRUSTED_WEB')

    def _document(self, url: str, ident: str) -> str:
        if self.fetches >= self.agent.max_fetches:
            raise ToolError('fetch_limit')
        self.fetches += 1
        final, content_type, body = self._fetch(url)
        text = body.decode(_charset(content_type), 'replace')
        links: list[str] = []
        if content_type.lower().startswith('text/html'):
            text, hrefs = html_to_text(text)
            for href in hrefs:
                target = normalize_url(urljoin(final, href.strip()))
                link = self._link_id(target) if target else None
                if link and link not in links and self._links[link] not in (url, final):
                    links.append(link)
                if len(links) >= DOC_LINKS_MAX:
                    break
        for seen in (url, final):
            if seen not in self.fetched_urls:
                self.fetched_urls.append(seen)
        listing = '\n'.join(f'[{link}] {self._links[link]}' for link in links)
        # The link list goes first so the cap never cuts it off.
        content = (f'links:\n{listing}\n\n' if listing else '') + f'url: {final}\n\n{text}'
        return self._frame(content, f'id={ident}', 'UNTRUSTED_WEB')

    def _tool_web_fetch(self, link_id: str) -> str:
        url = self._links.get(link_id)
        if url is None:
            raise ToolError('unknown_link')
        return self._document(url, link_id)

    def _tool_web_doc(self, kind: str, name: str) -> str:
        if kind == 'python_module':
            if not re.match(r'^[a-z][a-z0-9_]{0,39}$', name) or name not in sys.stdlib_module_names:
                raise ToolError('doc_unknown')
            url = f'https://docs.python.org/3/library/{name}.html'
        else:
            normalized = _dist_name(name)
            if not re.match(r'^[a-z0-9][a-z0-9-]{0,79}$', normalized) or normalized not in self._installed():
                raise ToolError('doc_unknown')
            url = f'https://pypi.org/project/{normalized}/'
        ident = self._link_id(url)
        if ident is None:
            raise ToolError('fetch_blocked')
        return self._document(url, ident)

    def _installed(self) -> frozenset[str]:
        if self._distributions is None:
            from importlib import metadata
            names = set()
            for dist in metadata.distributions():
                try:
                    names.add(_dist_name(dist.metadata['Name'] or ''))
                except Exception:
                    continue
            self._distributions = frozenset(name for name in names if name)
        return self._distributions


def _dist_name(name: str) -> str:
    return re.sub(r'[-_.]+', '-', str(name)).lower()


def _one_line(text: str) -> str:
    return _SPACES.sub(' ', html.unescape(clean_text(text)).replace('\n', ' ')).strip()


def build_toolbox(policy, request: Mapping, *, root: Path | str = SERVER_ROOT, runner: Runner | None = None,
                  http: HttpTransport | None = None, root_owned: bool | None = None, web: bool = True,
                  clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                  nonce: str | None = None, distributions: Iterable[str] | None = None,
                  statvfs: Callable[[str], Any] = os.statvfs,
                  exception_index: Iterable[str] | None = None) -> Toolbox:
    """Tools for one run over a validated request (protocol.validate_request output).

    - `runner(argv, timeout) -> (code, text)`: subprocesses (default `default_runner`).
    - `http`: the HTTP layer (default `HttpTransport()`); `web=False` drops the web tools.
    - `root_owned`: git_log only when True; None reads `policy.agent.root_owned` (False when absent).
    - `clock`/`sleep`: monotonic clock and sleep for the search interval and grep/scan limits (tests inject both).
    - `nonce`: frame nonce (default 16 random hex characters per run).
    - `exception_index`: precomputed exception names (tests); default: built from the request on first web_search.
    """
    if root_owned is None:
        root_owned = getattr(policy.agent, 'root_owned', False) is True
    return Toolbox(policy, request, root=Path(root), runner=runner or default_runner,
                   http=http if http is not None else (HttpTransport() if web else None), root_owned=root_owned,
                   web=web, clock=clock, sleep=sleep, nonce=nonce or secrets.token_hex(8),
                   distributions=distributions, statvfs=statvfs,
                   exception_index=None if exception_index is None else set(exception_index))
