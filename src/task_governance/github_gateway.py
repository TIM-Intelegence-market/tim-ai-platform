"""GitHub REST gateway for `ensure_task` (#68). Nothing here can close an issue.

Contract kept on purpose:
- `find_issues` lists issues by REST (never the lagging search index) and filters by the fingerprint marker;
  more issues than the page cap allows raise instead of guessing. The listing itself lags behind the newest
  issues (seen live: an issue created a moment earlier was missing), so every number the listing leaves out
  below its highest entry, and everything above it, is also read one by one (consistent right after a create).
  Above the highest entry the reads stop after PROBE_MISSES missing numbers in a row, but never below the highest
  number this gateway has created or seen, so the post-create check always reaches the issue it just made.
- `get_issue` returns None only for a confirmed 404. Rate limits, permission errors, 5xx and network
  errors raise `GitHubError`, so a transient failure never looks like "does not exist".
- `create_issue` enforces `timeout` as a wall-clock limit on the whole request (a server that drips bytes
  cannot stretch it); `CreateNotSent` only when no request can have left the process (connection refused,
  name resolution failed). A timeout is uncertain and raises `GitHubError`.
- Redirects are never followed (a moved or transferred issue must not redirect a write to another issue); every
  3xx is an error. An answer must carry the requested issue number and, when present, this repository's URL.
- `update_issue`, `mark_duplicate`, `reopen_issue` only change the managed body section, add a marker,
  comment, or reopen. No method changes an issue to closed.
The token is used only in the Authorization header and never appears in errors.
"""
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit
import hashlib
import ipaddress
import json
import re
import socket
import threading
import time

from .identity import TaskRequest, fingerprint_marker
from .sync import CreateNotSent, IssueRef

BODY_BEGIN = '<!-- TIM_TASK_BODY_BEGIN -->'
BODY_END = '<!-- TIM_TASK_BODY_END -->'
_MANAGED = re.compile(re.escape(BODY_BEGIN) + r'.*?' + re.escape(BODY_END), re.DOTALL)
PAGE_SIZE = 100
PROBE_WINDOW = 50       # the newest listed numbers are always re-read; older gaps that are gone for good are remembered
PROBE_MISSES = 3        # numbers above the highest one are read until this many in a row do not exist
PROBE_LIMIT = 500       # more direct reads than this in one lookup raise instead of guessing
OWED_LIMIT = 2000       # numbers up to the highest known one are owed and may be read this many times per lookup; a create
                        # answer further above the highest known number is used for the mapping but never raises the floor
CONFIRM_SECONDS = 120.0 # a missing old number is remembered when a second answer this much later agrees with the first
GONE_TTL = 3600.0       # a remembered number is read again after this long (two wrong answers must not hide an issue for good)
_NOT_AN_ISSUE = (301, 307, 308, 404, 410)   # deleted, transferred or not an issue (a discussion shares the numbers)
API = 'https://api.github.com'


class GitHubError(Exception):
    """A GitHub call failed or answered something unusable. Never carries the token or response bodies."""


class _TransportError(GitHubError):
    """Raised by the built-in transport only; its messages are fixed texts, so they may be shown as they are."""


class _NotSent(Exception):
    pass


MAX_ANSWER_BYTES = 16 * 1024 * 1024


def _is_loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback or host == 'localhost'
    except ValueError:
        return host == 'localhost'


def _http_transport(method, url, headers, body, timeout):
    """One request with a wall-clock deadline; no redirects (http.client never follows them)."""
    parts = urlsplit(url)
    if parts.scheme == 'https':
        factory = HTTPSConnection
    elif parts.scheme == 'http' and _is_loopback(parts.hostname or ''):
        factory = HTTPConnection            # plain http only for a local test server, never with a real host
    else:
        raise _TransportError('refusing a non-https url')
    target = parts.path + (f'?{parts.query}' if parts.query else '')
    box, cancelled = {}, threading.Event()

    def run():
        try:
            box['conn'] = conn = factory(parts.hostname, parts.port, timeout=timeout)
            conn.connect()
            if cancelled.is_set():
                return                      # the caller already gave up: send nothing
            conn.auto_open = 0              # a closed connection must fail, not silently reconnect and send late
            conn.request(method, target, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read(MAX_ANSWER_BYTES + 1)
            box['result'] = (response.status, data)
        except BaseException as error:      # reported to the caller thread below
            box['error'] = error
        finally:
            conn = box.get('conn')
            if conn is not None:
                conn.close()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        cancelled.set()                     # first: a worker that has not passed its own check yet will send nothing
        conn = box.get('conn')
        sock = getattr(conn, 'sock', None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)     # no further byte can leave, and a blocked send or read ends
            except OSError:
                pass
        if conn is not None:
            conn.close()                    # bytes that were already on the wire may still have reached GitHub
        raise _TransportError(f'{method} timed out after {timeout}s')
    error = box.get('error')
    if 'result' not in box and error is None:
        raise _TransportError(f'{method} did not complete')
    if error is not None:
        if isinstance(error, (ConnectionRefusedError, socket.gaierror)):
            raise _NotSent() from None
        raise _TransportError(f'{method} failed: {type(error).__name__}') from None
    status, data = box['result']
    if len(data) > MAX_ANSWER_BYTES:
        raise _TransportError(f'{method} answer too large')
    return status, data


class GitHubRestGateway:
    def __init__(self, repository: str, token: str, *, max_create_seconds: float = 20.0, request_timeout: float = 20.0,
                 max_pages: int = 50, transport=_http_transport, api: str = API, clock=time.monotonic):
        if not re.fullmatch(r'[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+', repository or ''):
            raise ValueError('repository must look like owner/name')
        if not token:
            raise ValueError('a token is required')
        self.repository = repository
        self.max_create_seconds = float(max_create_seconds)
        self._token, self._timeout, self._max_pages = token, float(request_timeout), max_pages
        self._transport, self._api = transport, api.rstrip('/')
        self._lock = threading.Lock()
        self._top = 0           # highest issue number this gateway has seen or created: lookups never stop below it
        self._clock = clock
        self._gone = {}         # old numbers (404, 410, redirect) that two answers at least CONFIRM_SECONDS apart called missing -> when
        self._gone_first = {}   # old number -> time of its first "missing" answer
        self._created = {}      # numbers this gateway created -> the fingerprint they carry: not read again for other fingerprints

    def __repr__(self):
        return f'GitHubRestGateway({self.repository!r})'

    # -- plumbing ----------------------------------------------------------
    def _call(self, method, path, payload=None, *, timeout=None, create=False, absent=()):
        headers = {'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {self._token}',
                   'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'tim-task-governance'}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        failure = None
        try:
            status, raw = self._transport(method, f'{self._api}{path}', headers, body, timeout or self._timeout)
        except _NotSent:
            if create:
                raise
            failure = f'{method} {path}: connection refused'
        except _TransportError as error:         # the built-in transport's own fixed texts stay readable
            failure = f'{method} {path}: {error}'
        except Exception as error:              # an injected transport may put headers (the token) into its message,
            failure = f'{method} {path}: transport failed ({type(error).__name__})'    # also a GitHubError of its own
        if failure is not None:
            raise GitHubError(failure)          # raised outside the except block: no __context__ keeps the original
        if status >= 300:
            if (status == 404 and method == 'GET') or status in absent:
                return status, None
            raise GitHubError(f'{method} {path}: HTTP {status}')      # includes 3xx: redirects are never followed
        try:
            return status, (json.loads(raw.decode('utf-8')) if raw else None)
        except ValueError:
            raise GitHubError(f'{method} {path}: unreadable answer') from None

    def _pages(self, path):
        sep = '&' if '?' in path else '?'
        for page in range(1, self._max_pages + 1):
            _, items = self._call('GET', f'{path}{sep}per_page={PAGE_SIZE}&page={page}')
            if not isinstance(items, list):
                raise GitHubError(f'GET {path}: expected a list')
            yield from items
            if len(items) < PAGE_SIZE:
                return
        raise GitHubError(f'GET {path}: more than {self._max_pages * PAGE_SIZE} entries, refusing to guess')

    def _ref(self, item, number=None) -> IssueRef:
        if not isinstance(item, dict) or 'number' not in item:
            raise GitHubError('answer without an issue number')
        try:
            found = int(item['number'])
        except (TypeError, ValueError):
            raise GitHubError('answer with an unusable issue number') from None
        if number is not None and found != int(number):
            raise GitHubError(f'asked for issue #{int(number)} but got #{found}')
        url = item.get('repository_url')
        if url is not None and not str(url).lower().rstrip('/').endswith(f'/repos/{self.repository}'.lower()):
            raise GitHubError(f'issue #{item["number"]} belongs to another repository')
        return IssueRef(found, str(item.get('state', '')), item.get('title') or '',
                        ((item.get('user') or {}).get('login') or ''), is_pull_request='pull_request' in item)

    def _issue(self, number):
        status, item = self._call('GET', f'/repos/{self.repository}/issues/{int(number)}')
        if status == 404:
            self._require_repository()          # 404 on a private or wrong repository must not read as "no such issue"
            return None
        self._ref(item, number)
        self._seen(int(number), floor=True)     # it exists: later lookups never stop below it (OWED_LIMIT bounds the walk)
        return item

    def _seen(self, number, *, floor=False):
        """A good answer for `number`: forget any "missing" answer for it; optionally make it the lookup floor."""
        with self._lock:
            self._gone.pop(number, None)
            self._gone_first.pop(number, None)
            if floor:
                self._top = max(self._top, number)

    def _require_repository(self):
        status, _ = self._call('GET', f'/repos/{self.repository}')       # not cached: access can be withdrawn
        if status == 404:
            raise GitHubError('repository not found or no access')

    def _comment(self, number, text):
        self._call('POST', f'/repos/{self.repository}/issues/{int(number)}/comments', {'body': text})

    # -- IssueGateway ------------------------------------------------------
    def find_issues(self, fingerprint, canonical_key):
        marker = fingerprint_marker(fingerprint)
        listed = list(self._pages(f'/repos/{self.repository}/issues?state=all'))
        items = {self._ref(item).number: item for item in listed}
        top, reads = max(items, default=0), 0
        now = self._clock()
        with self._lock:
            for number in [n for n, since in self._gone.items() if now - since >= GONE_TTL]:
                del self._gone[number]              # remembered long enough: ask again, and again require two answers
                self._gone_first.pop(number, None)
            known_top = self._top
        for number in items:                        # listed means it exists: an earlier "missing" answer was wrong
            self._seen(number)
        with self._lock:
            gone = set(self._gone)
        for number in range(1, top):                # gaps: deleted or transferred, or hidden by the lagging listing
            if number in items or number in gone:
                continue
            reads += 1
            if reads > PROBE_LIMIT:                 # before any create: nothing has been written yet
                raise GitHubError(f'more than {PROBE_LIMIT} unlisted issue numbers below #{top}, refusing to guess')
            status = self._probe(items, number)
            if status in _NOT_AN_ISSUE and number <= top - PROBE_WINDOW:
                self._note_missing(number)
        misses, number, floor, owed = 0, top, max(top, known_top), 0
        while misses < PROBE_MISSES or number < floor:      # above the listing's highest: fresh issues it does not show yet
            number += 1
            if number > floor:
                reads += 1
                if reads > PROBE_LIMIT:
                    raise GitHubError(f'more than {PROBE_LIMIT} unlisted issue numbers, refusing to guess')
            else:                                   # owed: up to the highest known number, bounded by OWED_LIMIT
                owed += 1
                if owed > OWED_LIMIT:
                    raise GitHubError(f'more than {OWED_LIMIT} issue numbers between the listing and #{floor}, refusing to guess')
                if self._created.get(number, fingerprint) != fingerprint:
                    misses = 0                      # our own issue for another task: it exists and cannot be this one
                    continue
            misses = 0 if self._probe(items, number) == 200 else misses + 1
        with self._lock:
            self._top = max(self._top, max(items, default=0))
        return [self._ref(item) for item in items.values() if marker in (item.get('body') or '')]

    def _probe(self, items, number):
        status, item = self._call('GET', f'/repos/{self.repository}/issues/{number}', absent=_NOT_AN_ISSUE)
        if status == 200:
            self._ref(item, number)
            items[number] = item
            self._seen(number)                  # it exists after all: an earlier "missing" answer was wrong
        elif status < 300:
            raise GitHubError(f'GET issue #{number}: unexpected HTTP {status}')
        return status

    def _note_missing(self, number):
        """Remember an old missing number only when two answers far enough apart agree, so no single wrong answer hides an issue."""
        now = self._clock()
        with self._lock:
            first = self._gone_first.setdefault(number, now)
            if now - first >= CONFIRM_SECONDS:
                self._gone[number] = now

    def carries_marker(self, number, fingerprint):
        """True when the issue exists and its body still carries the task's marker."""
        item = self._issue(number)
        return item is not None and fingerprint_marker(fingerprint) in (item.get('body') or '')

    def get_issue(self, number):
        item = self._issue(number)
        return None if item is None else self._ref(item, number)

    def create_issue(self, request: TaskRequest, fingerprint, *, timeout):
        body = f'{_managed(request)}\n\n{fingerprint_marker(fingerprint)}'
        try:
            _, item = self._call('POST', f'/repos/{self.repository}/issues', {'title': request.title or request.key, 'body': body},
                                 timeout=timeout, create=True)
        except _NotSent:
            raise CreateNotSent('connection could not be opened') from None
        ref = self._ref(item)
        with self._lock:
            self._created[ref.number] = fingerprint
            if ref.number <= self._top + OWED_LIMIT:    # an answer far above anything known maps, but must not make lookups walk to it
                self._top = max(self._top, ref.number)  # the next lookup reads every number up to this one, however the listing lags
        return ref

    def update_issue(self, number, request: TaskRequest, reason):
        item = self._issue(number)
        if item is None:
            raise GitHubError(f'issue #{number} does not exist')
        body = item.get('body') or ''
        wanted = _managed(request)
        marker = fingerprint_marker(request.fingerprint)
        new = _MANAGED.sub(lambda _: wanted, body) if _MANAGED.search(body) else f'{body}\n\n{wanted}'.strip()
        if marker not in new:
            new = f'{new}\n\n{marker}'
        if new != body:
            _, answer = self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}', {'body': new})
            self._ref(answer, number)
        tag = f'<!-- TIM_TASK_AUDIT:{hashlib.sha256(reason.encode()).hexdigest()[:12]} -->'
        if not any(tag in (c.get('body') or '') for c in self._pages(f'/repos/{self.repository}/issues/{int(number)}/comments')):
            self._comment(number, f'{tag}\nTIM task governance: {reason}')

    def reopen_issue(self, number, request: TaskRequest, reason):
        _, answer = self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}', {'state': 'open'})
        self._ref(answer, number)
        self._comment(number, f'TIM task governance: reopened ({reason}).')

    def is_documented_duplicate(self, number, authoritative):
        tag = _dup_tag(authoritative)
        return any(tag in (c.get('body') or '') for c in self._pages(f'/repos/{self.repository}/issues/{int(number)}/comments'))

    def mark_duplicate(self, number, authoritative):
        if not self.is_documented_duplicate(number, authoritative):
            self._comment(number, f'{_dup_tag(authoritative)}\nHistorical duplicate of #{int(authoritative)}, documented by TIM '
                                  'task governance. This issue is not closed or changed.')


def _managed(request: TaskRequest) -> str:
    return f'{BODY_BEGIN}\n{request.body}\n{BODY_END}'


def _dup_tag(authoritative) -> str:
    return f'<!-- TIM_DUPLICATE_OF:{int(authoritative)} -->'
