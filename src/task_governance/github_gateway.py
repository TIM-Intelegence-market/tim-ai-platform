"""GitHub REST gateway for `ensure_task` (#68). Nothing here can close an issue.

Contract kept on purpose:
- `find_issues` lists issues by REST (never the lagging search index) and filters by the fingerprint marker;
  more issues than the page cap allows raise instead of guessing.
- `get_issue` returns None only for a confirmed 404. Rate limits, permission errors, 5xx and network
  errors raise `GitHubError`, so a transient failure never looks like "does not exist".
- `create_issue` enforces `timeout` on the request; `CreateNotSent` only when no request can have left
  the process (connection refused, name resolution failed).
- `update_issue`, `mark_duplicate`, `reopen_issue` only change the managed body section, add a marker,
  comment, or reopen. No method changes an issue to closed.
The token is used only in the Authorization header and never appears in errors.
"""
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import hashlib
import json
import re
import socket

from .identity import TaskRequest, fingerprint_marker
from .sync import CreateNotSent, IssueRef

BODY_BEGIN = '<!-- TIM_TASK_BODY_BEGIN -->'
BODY_END = '<!-- TIM_TASK_BODY_END -->'
_MANAGED = re.compile(re.escape(BODY_BEGIN) + r'.*?' + re.escape(BODY_END), re.DOTALL)
PAGE_SIZE = 100
API = 'https://api.github.com'


class GitHubError(Exception):
    """A GitHub call failed or answered something unusable. Never carries the token or response bodies."""


class _NotSent(Exception):
    pass


def _urllib_transport(method, url, headers, body, timeout):
    request = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, b''
    except URLError as error:
        if isinstance(error.reason, (ConnectionRefusedError, socket.gaierror)):
            raise _NotSent() from None
        raise GitHubError(f'{method} failed: {type(error.reason).__name__}') from None
    except (TimeoutError, OSError) as error:
        raise GitHubError(f'{method} failed: {type(error).__name__}') from None


class GitHubRestGateway:
    def __init__(self, repository: str, token: str, *, max_create_seconds: float = 20.0, request_timeout: float = 20.0,
                 max_pages: int = 50, transport=_urllib_transport, api: str = API):
        if not re.fullmatch(r'[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+', repository or ''):
            raise ValueError('repository must look like owner/name')
        if not token:
            raise ValueError('a token is required')
        self.repository = repository
        self.max_create_seconds = float(max_create_seconds)
        self._token, self._timeout, self._max_pages = token, float(request_timeout), max_pages
        self._transport, self._api = transport, api.rstrip('/')

    def __repr__(self):
        return f'GitHubRestGateway({self.repository!r})'

    # -- plumbing ----------------------------------------------------------
    def _call(self, method, path, payload=None, *, timeout=None):
        headers = {'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {self._token}',
                   'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'tim-task-governance'}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        status, raw = self._transport(method, f'{self._api}{path}', headers, body, timeout or self._timeout)
        if status >= 400:
            if status == 404 and method == 'GET':
                return 404, None
            raise GitHubError(f'{method} {path}: HTTP {status}')
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

    @staticmethod
    def _ref(item) -> IssueRef:
        return IssueRef(int(item['number']), str(item.get('state', '')), item.get('title') or '',
                        ((item.get('user') or {}).get('login') or ''), is_pull_request='pull_request' in item)

    def _issue(self, number):
        status, item = self._call('GET', f'/repos/{self.repository}/issues/{int(number)}')
        return None if status == 404 else item

    def _comment(self, number, text):
        self._call('POST', f'/repos/{self.repository}/issues/{int(number)}/comments', {'body': text})

    # -- IssueGateway ------------------------------------------------------
    def find_issues(self, fingerprint, canonical_key):
        marker = fingerprint_marker(fingerprint)
        return [self._ref(item) for item in self._pages(f'/repos/{self.repository}/issues?state=all')
                if marker in (item.get('body') or '')]

    def get_issue(self, number):
        item = self._issue(number)
        return None if item is None else self._ref(item)

    def create_issue(self, request: TaskRequest, fingerprint, *, timeout):
        body = f'{_managed(request)}\n\n{fingerprint_marker(fingerprint)}'
        try:
            _, item = self._call('POST', f'/repos/{self.repository}/issues', {'title': request.title or request.key, 'body': body},
                                 timeout=timeout)
        except _NotSent:
            raise CreateNotSent('connection could not be opened') from None
        if not isinstance(item, dict) or 'number' not in item:
            raise GitHubError('create answered without an issue number')
        return self._ref(item)

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
            self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}', {'body': new})
        tag = f'<!-- TIM_TASK_AUDIT:{hashlib.sha256(reason.encode()).hexdigest()[:12]} -->'
        if not any(tag in (c.get('body') or '') for c in self._pages(f'/repos/{self.repository}/issues/{int(number)}/comments')):
            self._comment(number, f'{tag}\nTIM task governance: {reason}')

    def reopen_issue(self, number, request: TaskRequest, reason):
        self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}', {'state': 'open'})
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
