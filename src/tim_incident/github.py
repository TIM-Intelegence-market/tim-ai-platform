"""Incident reporter (design B.2-B.7): spool, write-guarded gateway and delivery to GitHub.

Contract kept on purpose:
- Issues are created only through `ensure_task` (#68) with `OwnerOnlyAuthority`: only an open authority issue opened by
  the owner, naming this registry, lets the reporter create. Closing it stops every write at once (`revoked`).
- `IncidentGateway._guard` runs before every write: the issue carries exactly one TIM_INCIDENT_V1 marker, was opened by
  the reporter login, is not a pull request and is neither the authority nor the watch issue. Only `post_summary`
  comments on the authority issue, with a text built here from structured data.
- Labels come only from `policy.LABEL_ALLOWLIST`; `status:*`, `agent:*`, `checkup:*`, `priority:p0`, `governance` never.
- The body is fixed text from the checkup and is never rewritten; only the STATUS section outside the managed part
  changes, and not at all once `status:ready` or an `agent:*` label is set (E6).
- Every outgoing text is checked again for the known secrets (installation token, app key lines, DB password) and
  must pass `final_scan`; a comment with a hit is replaced whole, fixed texts are redacted. The token appears only in the Authorization header: never in spool, state, logs or errors.
- The spool never deletes: delivered entries move to `outbox/done/`. A failure before sending stops the run and keeps
  the spool; nothing is retried blindly after an uncertain create (`CREATE_UNCERTAIN` waits for the owner).
- Qwen results (PR-2, design B.8) cross the trust boundary only in `ingest_diagnoses`: opened with O_NOFOLLOW, owner
  tim-agent, at most 32 KB, strict schema, locations re-verified under /opt/tim, file content never quoted, all model
  text redacted again and fenced. The body gets only the FIELDS section (`set_fields`: fix_kind enum and verified
  path:line), never model text, and nothing once the body is frozen.
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import socket
import stat
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from urllib.parse import urlsplit

from src.task_governance.create_authority import CreateNotAuthorized, IssueCreateAuthority, parse_authority
from src.task_governance.github_gateway import (MAX_ANSWER_BYTES, GitHubError, GitHubRestGateway, _NotSent,
                                                _TransportError, _dup_tag, _is_loopback)
from src.task_governance.identity import TaskRequest, fingerprint_marker
from src.task_governance.registry import MappingState, TaskRegistry
from src.task_governance.repository_names import normalize_repository
from src.task_governance.sync import CreateNotSent, EnsureOutcome, ensure_task

from . import github_app, protocol
from .policy import CLASS_NAMES, LABEL_ALLOWLIST, NOT_CONFIGURED, Controls
from .redaction import final_scan, literal_variants, redact, untrusted_block

INCIDENT_MARKER = 'TIM_INCIDENT_V1'
_INCIDENT = re.compile(r'<!-- TIM_INCIDENT_V1 class=([A-Z_]{1,32}) episode=(\d{8}T\d{4}Z) '
                       r'host=([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?) -->')
STATUS_BEGIN = '<!-- TIM_INCIDENT_STATUS_BEGIN -->'
STATUS_END = '<!-- TIM_INCIDENT_STATUS_END -->'
_STATUS = re.compile(re.escape(STATUS_BEGIN) + r'.*?' + re.escape(STATUS_END), re.S)
FIELDS_BEGIN = '<!-- TIM_INCIDENT_FIELDS_BEGIN -->'
FIELDS_END = '<!-- TIM_INCIDENT_FIELDS_END -->'
_FIELDS = re.compile(re.escape(FIELDS_BEGIN) + r'.*?' + re.escape(FIELDS_END), re.S)
_FIELD_LOCATION = re.compile(r'^([A-Za-z0-9_./-]{1,200}):([1-9][0-9]{0,6})$')
FIELD_LABELS = frozenset({'incident:code'})     # the only label a diagnosis may add (B.6)
_FORBIDDEN_LABEL = re.compile(r'^(?:status:|agent:|checkup:)|^(?:priority:p0|governance)$')
_SUMMARY_PREFIX = '<!-- TIM_INCIDENT_SUMMARY id='

KINDS = ('open', 'comment', 'status_line', 'resolve', 'reopen', 'fields')
_EPISODE = re.compile(r'^\d{8}T\d{4}Z$')
_HOSTNAME = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
_TAG = re.compile(r'^[a-z0-9][a-z0-9-]{0,40}$')
_COMMIT = re.compile(r'^[0-9a-f]{7,40}$')
_ENTRY_ID = re.compile(r'^\d{12}-[a-z_]{1,20}-[0-9a-f]{12}$')
MAX_TITLE = 256
MAX_BODY = 60000
MAX_TEXT = 60000
MAX_STATUS = 300
MAX_STATUS_LINE = 500
MAX_ENTRY_BYTES = 256 * 1024

CREATE_UNCERTAIN_NOTE_SECONDS = 3600.0      # B.4: after this long the journal names the confirm-not-created line
CONFIRM_QUIET_SECONDS = 3600.0
STATE_KEEP_SECONDS = 30 * 86400             # per-episode bookkeeping older than this is dropped
CREATE_WRITES = 3                           # create, labels, possibly the marker back-fill

PREFLIGHT_OK = 'ok'
PREFLIGHT_SKIPPED = 'skipped'
_FAILURE_TEXT = {
    github_app.KEY_MISSING: 'app key missing',
    github_app.TOKEN_INVALID: 'token invalid',
    github_app.FORBIDDEN: 'github forbidden',
    github_app.RATE_LIMITED: 'github rate limited',
    github_app.NETWORK_DOWN: 'github not reachable',
}
_TEXT_REPLACED = ('[Text entfernt: Die Schlussprüfung des Melders hat einen Geheimnisverdacht gefunden. '
                  'Die Evidenz liegt nur auf dem Server.]')


# -- errors ------------------------------------------------------------------------------------------------------

class GuardError(Exception):
    """A write was refused before anything was sent (fixed text)."""


class LabelRefused(GuardError):
    """A label outside the allowlist (design E4, B.6)."""


class CreateRefused(CreateNotSent):
    """`create_issue` refused the request before sending (no marker, final_scan hit)."""


class CreateRejected(CreateNotSent):
    """GitHub answered the create with 4xx: it did not create the issue. `status` says which."""

    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status = status


class NetworkDown(GitHubError):
    """The request never left the process (unreachable, DNS, connect timeout, TLS handshake)."""


class HTTPStatusError(GitHubError):
    """GitHub answered 401, 403 or 429; `status` says which."""

    def __init__(self, status: int, text: str):
        super().__init__(text)
        self.status = status


class RepositoryNotVisible(GitHubError):
    """The token cannot see the repository (installation or repository selection wrong)."""


class WriteBudgetExceeded(GitHubError):
    """`rate_limits.writes_per_run` is used up for this run."""


# -- markers and identity ----------------------------------------------------------------------------------------

def incident_marker(cls: str, episode: str, host: str) -> str:
    return f'<!-- {INCIDENT_MARKER} class={cls} episode={episode} host={host} -->'


def parse_incident_marker(body) -> tuple[str, str, str] | None:
    """(class, episode, host) of the single incident marker in `body`; None for none or more than one."""
    found = _INCIDENT.findall(body or '')
    return found[0] if len(found) == 1 else None


def tag_marker(episode: str, tag: str) -> str:
    return f'<!-- TIM_INCIDENT_TAG episode={episode} tag={tag} -->'


def entry_key(entry) -> str:
    """Per-episode bookkeeping key. Classes opened in the same run share the episode id, so the class is part of it."""
    return f"{entry['class']}/{entry['episode']}"


def task_request(cls: str, episode: str, host: str, title: str = '', body: str = '') -> TaskRequest:
    """The task identity of one episode (contract 3)."""
    return TaskRequest('TIM', 'INCIDENT', cls, f'{host.upper()}.{episode}', 'v1', title, body)


def _label_names(item) -> list[str]:
    names = []
    for label in item.get('labels') or []:
        name = label.get('name') if isinstance(label, dict) else label
        if isinstance(name, str):
            names.append(name)
    return names


def frozen(labels) -> bool:
    """E6: the body stays as it is once the owner set status:ready or an agent took the issue."""
    return any(label == 'status:ready' or label.startswith('agent:') for label in labels)


def label_allowed(label) -> bool:
    return isinstance(label, str) and label in LABEL_ALLOWLIST and not _FORBIDDEN_LABEL.match(label)


# -- transport ---------------------------------------------------------------------------------------------------

def incident_transport(method, url, headers, body, timeout):
    """Copy of `github_gateway._http_transport` that knows whether the request started.

    Everything that fails before the first byte of the request (unreachable, DNS, refused, connect timeout, TLS
    handshake, a deadline hit while still connecting) raises `_NotSent`, so a create becomes `CreateNotSent`. A failure
    after that stays uncertain, as in the base transport."""
    parts = urlsplit(url)
    if parts.scheme == 'https':
        factory = HTTPSConnection
    elif parts.scheme == 'http' and _is_loopback(parts.hostname or ''):
        factory = HTTPConnection            # plain http only for a local test server
    else:
        raise _TransportError('refusing a non-https url')
    target = parts.path + (f'?{parts.query}' if parts.query else '')
    box, gate = {}, threading.Lock()
    flags = {'cancelled': False, 'started': False}

    def run():
        try:
            box['conn'] = conn = factory(parts.hostname, parts.port, timeout=timeout)
            conn.connect()                  # TCP and, for https, the TLS handshake: no request byte has left yet
            with gate:
                if flags['cancelled']:
                    return                  # the caller gave up while we connected: send nothing
                flags['started'] = True
            conn.auto_open = 0              # a closed connection must fail, not reconnect and send late
            conn.request(method, target, body=body, headers=headers)
            response = conn.getresponse()
            box['result'] = (response.status, response.read(MAX_ANSWER_BYTES + 1))
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
        with gate:
            flags['cancelled'] = True
            started = flags['started']
        conn = box.get('conn')
        sock = getattr(conn, 'sock', None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if conn is not None:
            conn.close()
        if not started:
            raise _NotSent()
        raise _TransportError(f'{method} timed out after {timeout}s')
    error = box.get('error')
    if not flags['started']:
        raise _NotSent()                    # connect failed, or nothing happened at all
    if error is not None:
        raise _TransportError(f'{method} failed: {type(error).__name__}') from None
    if 'result' not in box:
        raise _TransportError(f'{method} did not complete')
    status, data = box['result']
    if len(data) > MAX_ANSWER_BYTES:
        raise _TransportError(f'{method} answer too large')
    return status, data


# -- authority ---------------------------------------------------------------------------------------------------

class OwnerOnlyAuthority(IssueCreateAuthority):
    """Only an authority issue opened by the owner counts; one opened by the bot itself never does."""

    def __init__(self, issue_number: int, owner_login: str):
        super().__init__(issue_number)
        if not owner_login:
            raise ValueError('owner_login is required')
        self.owner_login = owner_login

    def check(self, gateway, registry_id: str, trusted_authors) -> None:
        super().check(gateway, registry_id, [self.owner_login])


# -- gateway -----------------------------------------------------------------------------------------------------

_NOT_SENT = 'not_sent'


class IncidentGateway(GitHubRestGateway):
    """`GitHubRestGateway` with the write guard, the label allowlist and the incident-only write methods."""

    def __init__(self, repository: str, token: str, *, reporter_login: str, owner_login: str, authority_issue: int,
                 watch_issue: int | None = None, transport=None, write_budget: int | None = None, **kwargs):
        if not reporter_login or not owner_login:
            raise ValueError('reporter_login and owner_login are required')
        self.reporter_login, self.owner_login = reporter_login, owner_login
        self.authority_issue = int(authority_issue)
        self.watch_issue = int(watch_issue) if watch_issue else None
        self._protected = frozenset(n for n in (self.authority_issue, self.watch_issue) if n)
        self._inner = incident_transport if transport is None else transport
        self._last = None
        self.writes = 0             # write calls attempted in this run
        self.writes_ok = 0          # write calls GitHub accepted
        self.write_budget = write_budget
        self.authority_problem = 'authority not read'
        super().__init__(repository, token, transport=self._send,
                         create_authority=OwnerOnlyAuthority(self.authority_issue, owner_login), **kwargs)

    def __repr__(self):
        return f'IncidentGateway({self.repository!r})'

    # -- plumbing ----------------------------------------------------------
    def _send(self, method, url, headers, body, timeout):
        try:
            status, raw = self._inner(method, url, headers, body, timeout)
        except _NotSent:
            self._last = _NOT_SENT
            raise
        self._last = status
        return status, raw

    def _call(self, method, path, payload=None, *, timeout=None, create=False, absent=()):
        if method != 'GET':
            if not create and self.write_budget is not None and self.writes >= self.write_budget:
                raise WriteBudgetExceeded('write budget of this run used up')
            self.writes += 1
        self._last = None
        try:
            answer = super()._call(method, path, payload, timeout=timeout, create=create, absent=absent)
        except GitHubError as error:
            last, text = self._last, str(error)
            if last == _NOT_SENT:
                failure = NetworkDown(f'{method}: github not reachable')
            elif create and isinstance(last, int) and 400 <= last < 500:
                failure = CreateRejected(last, f'create refused by github (HTTP {last})')   # a 4xx created nothing
            elif last in (401, 403, 429):
                failure = HTTPStatusError(last, text)
            else:
                raise
            raise failure from None
        if method != 'GET':
            self.writes_ok += 1
        return answer

    def _is_reporter(self, login) -> bool:
        return (login or '').strip().lower() == self.reporter_login.strip().lower()

    def _guard(self, number, episode: str | None = None) -> dict:
        """The fresh issue, or GuardError: our marker, our author, no PR, not the authority or watch issue."""
        n = int(number)
        if n in self._protected:
            raise GuardError(f'issue #{n} is the authority or watch issue')
        item = self._issue(n)
        if item is None:
            raise GuardError(f'issue #{n} does not exist')
        if 'pull_request' in item:
            raise GuardError(f'issue #{n} is a pull request')
        if not self._is_reporter((item.get('user') or {}).get('login')):
            raise GuardError(f'issue #{n} was not opened by the reporter')
        marker = parse_incident_marker(item.get('body'))
        if marker is None:
            raise GuardError(f'issue #{n} has no single {INCIDENT_MARKER} marker')
        if episode is not None and marker[1] != episode:
            raise GuardError(f'issue #{n} belongs to another episode')
        return item

    def _state(self, item) -> dict:
        labels = _label_names(item)
        closed_by = ((item.get('closed_by') or {}).get('login') or '')
        return {'number': int(item['number']), 'state': str(item.get('state') or ''),
                'state_reason': str(item.get('state_reason') or ''), 'closed_by': closed_by,
                'closed_by_reporter': self._is_reporter(closed_by), 'labels': labels,
                'author': ((item.get('user') or {}).get('login') or ''), 'is_pull_request': 'pull_request' in item,
                'frozen': frozen(labels), 'marker': parse_incident_marker(item.get('body'))}

    # -- reads -------------------------------------------------------------
    def issue_state(self, number) -> dict | None:
        item = self._issue(number)
        return None if item is None else self._state(item)

    def read_controls(self, registry_id: str) -> Controls:
        """One GET of the authority issue. 'open' only for an open issue by the owner whose marker names this registry
        and repository; anything else that exists but does not qualify counts as 'missing'."""
        status, item = self._call('GET', f'/repos/{self.repository}/issues/{self.authority_issue}')
        if status == 404:
            if not self.repository_visible():
                raise RepositoryNotVisible('repository not visible')
            self.authority_problem = 'authority missing'
            return Controls('missing', frozenset())
        self._ref(item, self.authority_issue)
        labels = frozenset(_label_names(item))
        author = ((item.get('user') or {}).get('login') or '')
        if 'pull_request' in item:
            self.authority_problem = 'authority is a pull request'
            return Controls('missing', labels)
        if author.strip().lower() != self.owner_login.strip().lower():
            self.authority_problem = 'authority not opened by the owner'
            return Controls('missing', labels)
        if item.get('state') != 'open':
            self.authority_problem = 'authority closed'
            return Controls('closed', labels)
        marker = parse_authority(item.get('body') or '')
        if marker is None or marker[0] != registry_id \
                or normalize_repository(marker[1]) != normalize_repository(self.repository):
            self.authority_problem = 'authority marker invalid'
            return Controls('missing', labels)
        self.authority_problem = PREFLIGHT_OK
        return Controls('open', labels)

    def repository_visible(self) -> bool:
        status, _ = self._call('GET', f'/repos/{self.repository}')
        return status == 200

    def missing_labels(self, wanted) -> list[str]:
        have = {item.get('name') for item in self._pages(f'/repos/{self.repository}/labels') if isinstance(item, dict)}
        return sorted(set(wanted) - have)

    def open_incidents(self) -> list[dict]:
        """Open issues of the reporter with an incident marker (adoption after a lost state.json, A.3)."""
        found = []
        for item in self._pages(f'/repos/{self.repository}/issues?state=open'):
            if not isinstance(item, dict) or 'pull_request' in item or item.get('state') != 'open':
                continue
            if not self._is_reporter((item.get('user') or {}).get('login')):
                continue
            marker = parse_incident_marker(item.get('body'))
            if marker is not None:
                found.append({'number': self._ref(item).number, 'class': marker[0], 'episode': marker[1],
                              'host': marker[2], 'labels': _label_names(item)})
        return found

    # -- IssueGateway overrides used by ensure_task -------------------------
    def create_issue(self, request: TaskRequest, fingerprint, *, timeout):
        marker = parse_incident_marker(request.body)
        if marker is None or marker[0] != request.task_type.upper():
            raise CreateRefused('incident body without its marker')
        if '\n' in (request.title or '') or final_scan(request.title or '') or final_scan(request.body):
            raise CreateRefused('incident text failed the final scan')
        return super().create_issue(request, fingerprint, timeout=timeout)

    def update_issue(self, number, request: TaskRequest, reason):
        """Never rewrites the incident text and never comments (no English audit comment, no push): it only puts the
        task marker back when it is missing and the body is not frozen."""
        item = self._guard(number)
        body = item.get('body') or ''
        marker = fingerprint_marker(request.fingerprint)
        if marker in body or frozen(_label_names(item)):
            return
        _, answer = self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}',
                               {'body': f'{body.rstrip()}\n\n{marker}'})
        self._ref(answer, number)

    def reopen_issue(self, number, request: TaskRequest, reason):
        raise GuardError('incident issues are reopened only through reopen_incident')

    def mark_duplicate(self, number, authoritative):
        self._guard(number)
        if not self.is_documented_duplicate(number, authoritative):
            self._comment(number, f'{_dup_tag(authoritative)}\nDoppelte Vorfallmeldung, maßgeblich ist Issue Nr. '
                                  f'{int(authoritative)}. Dieses Issue wird nicht geändert und nicht geschlossen.')

    # -- incident writes ---------------------------------------------------
    def add_labels(self, number, labels, *, episode: str | None = None) -> list[str]:
        wanted = list(dict.fromkeys(labels))
        for label in wanted:
            if not label_allowed(label):
                raise LabelRefused('label outside the allowlist')
        item = self._guard(number, episode)
        have = set(_label_names(item))
        missing = [label for label in wanted if label not in have]
        if missing:
            self._call('POST', f'/repos/{self.repository}/issues/{int(number)}/labels', {'labels': missing})
        return missing

    def comment_once(self, number, tag: str, text: str, *, episode: str | None = None) -> bool:
        """Post `text` under `tag` unless a comment of the reporter already starts with that tag. True if posted."""
        if not _TAG.match(tag or ''):
            raise GuardError('invalid comment tag')
        if not isinstance(text, str) or not text.strip() or final_scan(text):
            raise GuardError('comment text failed the final scan')
        item = self._guard(number, episode)
        head = tag_marker(parse_incident_marker(item.get('body'))[1], tag)
        for comment in self._pages(f'/repos/{self.repository}/issues/{int(number)}/comments'):
            if not isinstance(comment, dict):
                continue
            if self._is_reporter((comment.get('user') or {}).get('login')) and (comment.get('body') or '').startswith(head):
                return False
        self._comment(number, f'{head}\n{text}')
        return True

    def close_incident(self, number, *, episode: str | None = None) -> bool:
        item = self._guard(number, episode)
        if item.get('state') == 'closed':
            return False
        _, answer = self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}',
                               {'state': 'closed', 'state_reason': 'completed'})
        self._ref(answer, number)
        return True

    def reopen_incident(self, number, *, episode: str | None = None) -> bool:
        """Reopen only what the reporter itself closed as completed; a person's close stands."""
        item = self._guard(number, episode)
        state = self._state(item)
        if state['state'] != 'closed' or not state['closed_by_reporter'] or state['state_reason'] != 'completed':
            return False
        _, answer = self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}', {'state': 'open'})
        self._ref(answer, number)
        return True

    def set_status_line(self, number, text: str, *, episode: str | None = None) -> bool:
        """Replace only the STATUS section (added at the end if missing). No-op once the body is frozen."""
        line = ' '.join(str(text).split())
        if not line or len(line) > MAX_STATUS_LINE or '<!--' in line or '-->' in line or final_scan(line):
            raise GuardError('status line refused')
        item = self._guard(number, episode)
        if frozen(_label_names(item)):
            return False
        body = item.get('body') or ''
        section = f'{STATUS_BEGIN}\n{line}\n{STATUS_END}'
        new = _STATUS.sub(lambda _: section, body, count=1) if _STATUS.search(body) else f'{body.rstrip()}\n{section}'
        if new == body:
            return False
        _, answer = self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}', {'body': new})
        self._ref(answer, number)
        return True

    def set_fields(self, number, fields, *, episode: str | None = None) -> bool:
        """Replace only the FIELDS section (design B.5): the Diagnose-Art enum and verified path:line locations, no
        free text. Inserted before the STATUS section (or at the end) when missing. No-op once the body is frozen."""
        section = fields_section(check_fields(fields))
        item = self._guard(number, episode)
        if frozen(_label_names(item)):
            return False
        body = item.get('body') or ''
        if _FIELDS.search(body):
            new = _FIELDS.sub(lambda _: section, body, count=1)
        elif STATUS_BEGIN in body:
            head, tail = body.split(STATUS_BEGIN, 1)
            new = f'{head.rstrip()}\n{section}\n{STATUS_BEGIN}{tail}'
        else:
            new = f'{body.rstrip()}\n{section}'
        if new == body:
            return False
        _, answer = self._call('PATCH', f'/repos/{self.repository}/issues/{int(number)}', {'body': new})
        self._ref(answer, number)
        return True

    def post_summary(self, items) -> bool:
        """The only comment on the authority issue: a fixed text listing episodes that resolved while reporting was
        silenced or revoked. Idempotent per set of episodes."""
        head, text = summary_text(items)
        if final_scan(text):
            raise GuardError('summary failed the final scan')
        item = self._issue(self.authority_issue)
        if item is None or 'pull_request' in item or item.get('state') != 'open' \
                or ((item.get('user') or {}).get('login') or '').strip().lower() != self.owner_login.strip().lower():
            raise GuardError('authority issue not usable for a summary')
        for comment in self._pages(f'/repos/{self.repository}/issues/{self.authority_issue}/comments'):
            if isinstance(comment, dict) and self._is_reporter((comment.get('user') or {}).get('login')) \
                    and (comment.get('body') or '').startswith(head):
                return False
        self._comment(self.authority_issue, f'{head}\n{text}')
        return True


class _AdoptOnly:
    """Gateway view for `adopt_only` entries: ensure_task may look up and adopt, never create."""

    def __init__(self, gateway: IncidentGateway):
        self._gateway = gateway

    def __getattr__(self, name):
        return getattr(self._gateway, name)

    def authorize_create(self, registry_id, trusted_authors):
        raise CreateNotAuthorized('adopt only: this entry never creates')

    def create_issue(self, request, fingerprint, *, timeout):
        raise CreateRefused('adopt only: this entry never creates')


# -- texts (German, fixed) ---------------------------------------------------------------------------------------

def _when(at: str) -> str:
    return _parse_time(at).strftime('%Y-%m-%d %H:%M UTC')


def summary_text(items) -> tuple[str, str]:
    lines, episodes = [], []
    for item in items:
        cls, episode = item['class'], item['episode']
        if cls not in CLASS_NAMES or not _EPISODE.match(episode):
            raise GuardError('summary item invalid')
        issue = item.get('issue')
        where = f'Issue Nr. {int(issue)}' if isinstance(issue, int) and not isinstance(issue, bool) else 'kein Issue angelegt'
        lines.append(f'- {cls}, Episode {episode}, erkannt {_when(item["at"])}, schon wieder erholt ({where})')
        episodes.append(f'{cls}/{episode}')
    if not lines:
        raise GuardError('empty summary')
    digest = hashlib.sha256('\n'.join(sorted(episodes)).encode()).hexdigest()[:12]
    head = f'{_SUMMARY_PREFIX}{digest} -->'
    text = ('Sammelmeldung des Checkups: Während das Melden stummgeschaltet oder widerrufen war, sind diese Vorfälle '
            'aufgetreten und haben sich schon wieder erholt. Dafür gibt es keine einzelnen Meldungen.\n'
            + '\n'.join(lines))
    return head, text


def human_closed_text(commit) -> str:
    where = f' auf Commit {commit}' if isinstance(commit, str) and _COMMIT.match(commit) else ''
    return (f'Der Vorfall ist{where} noch aktiv, das Issue wurde aber von Hand geschlossen. '
            'Steht ein Deploy noch aus? Zu dieser Episode meldet der Checkup nichts mehr.')


def kept_open_status_text(at: str) -> str:
    return (f'- Stand {_when(at)}: erholt, das Issue bleibt wegen der Kommentargrenze offen und wird nach einem '
            'ruhigen Tag geschlossen')


def kept_open_closing_text(since: float) -> str:
    when = datetime.fromtimestamp(float(since), timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return (f'Erholt: Seit {when} gab es zu diesem Vorfall keinen neuen Befund. Das Issue blieb wegen der '
            'Kommentargrenze offen, der Melder schließt es jetzt.')


def limit_status_text(at: str, tag: str) -> str:
    return f'- Stand {_when(at)}: neue Meldung ({tag}) nur hier vermerkt, Kommentargrenze erreicht'


def status_text(entry) -> str:
    count = entry.get('count', 1)
    extra = f' ({int(count)} Läufe zusammengefasst)' if isinstance(count, int) and count > 1 else ''
    return f'- Stand {_when(entry["at"])}: {entry["status"]}{extra}'


# -- diagnosis fields (design B.5) ---------------------------------------------------------------------------------

def check_fields(fields) -> dict:
    """A checked copy of {'fix_kind': FIX_KINDS, 'locations': ['path:line', ...]}; GuardError otherwise. Paths follow
    the location rules (prefix, blocklist, ^[A-Za-z0-9_./-]+$), so the body never gets free text."""
    if not isinstance(fields, dict) or set(fields) != {'fix_kind', 'locations'}:
        raise GuardError('fields invalid')
    if fields['fix_kind'] not in protocol.FIX_KINDS:
        raise GuardError('fields invalid')
    locations = fields['locations']
    if not isinstance(locations, list) or len(locations) > protocol.LOCATIONS_MAX:
        raise GuardError('fields invalid')
    for item in locations:
        match = _FIELD_LOCATION.match(item) if isinstance(item, str) else None
        if match is None or not protocol.path_allowed(match.group(1), None, location=True):
            raise GuardError('fields invalid')
    if len(set(locations)) != len(locations):
        raise GuardError('fields invalid')
    return {'fix_kind': fields['fix_kind'], 'locations': list(locations)}


def fields_section(fields) -> str:
    places = ', '.join(fields['locations']) or 'keine'
    return '\n'.join([FIELDS_BEGIN, f"- Diagnose-Art: {fields['fix_kind']}", f'- Geprüfte Stellen: {places}',
                      FIELDS_END])


def code_label(fix_kind: str, locations) -> bool:
    """B.6: incident:code only for fix_kind code_src with at least one verified location, every one under src/ and
    none in src/tim_incident/ or src/database/."""
    paths = [item['path'] for item in locations]
    return fix_kind == 'code_src' and bool(paths) and all(
        path.startswith('src/') and not path.startswith(('src/tim_incident/', 'src/database/')) for path in paths)


# -- ingest of Qwen results (design B.8): the trust boundary -------------------------------------------------------

AGENT_USER = 'tim-agent'
REPO_ROOT = Path('/opt/tim')
INGEST_MAX = 20                             # results per run; the rest waits for the next run
DIAGNOSIS_TAG_PREFIX = 'diagnosis-'
_REJECT_TEXTS = {
    'unreadable': 'Datei nicht lesbar',
    'symlink': 'symbolischer Link',
    'not_regular': 'keine reguläre Datei',
    'wrong_owner': 'falscher Besitzer',
    'linked': 'mehrfach verlinkte Datei',
    'too_large': 'Datei zu groß',
    'not_json': 'kein gültiges JSON',
    'schema': 'Schema verletzt',
    'bad_name': 'ungültiger Name',
    'write_failed': 'ungültig',
}
_WITHHELD = '[Modelltext zurückgehalten: Die Schlussprüfung hat einen Geheimnisverdacht gefunden.]'


def diagnosis_tag(rid: str) -> str:
    """Comment tag of a request: one diagnosis comment per rid ('diagnosis-20261007t0315z-data-flow-1')."""
    if protocol.parse_rid(rid) is None:
        raise GuardError('invalid rid')
    return DIAGNOSIS_TAG_PREFIX + rid.lower()


def _request_label(rid: str) -> str:
    episode, cls, seq = protocol.parse_rid(rid)
    return f'Auftrag {seq} zur Klasse {cls}, Episode {episode}'


def diagnosis_failed_text(rid: str, reason: str) -> str:
    return (f'Diagnose nicht möglich: {protocol.FAILURE_TEXTS[reason]} ({_request_label(rid)}). '
            'Die Qwen-Diagnose hat keinen Text geliefert.')


def diagnosis_rejected_text(rid: str, code: str) -> str:
    return (f'Diagnose verworfen: Das Ergebnis ({_request_label(rid)}) hat die Prüfung des Checkups nicht bestanden '
            f'({_REJECT_TEXTS.get(code, "ungültig")}). Davon wird nichts angezeigt.')


def diagnosis_missing_text(rid: str, minutes: int) -> str:
    return (f'Diagnose ausgefallen: Zum {_request_label(rid)} kam nach {int(minutes)} min kein Ergebnis. '
            'Sie wird nicht nachgeholt.')


def diagnosis_text(rid: str, result: dict, kept: list[dict], removed: int, literals=()) -> str:
    """The comment for an 'ok' result. Fixed German head with the enum, numbers and verified path:line only; every
    model text (summary, cause, suggestion, check, location reasons, sources) goes through `untrusted_block`
    (redaction with the known secrets, final scan, neutralize, fence). File content is never read into it."""
    unverified = removed + result['unverified_locations']
    places = ', '.join(f"{item['path']}:{item['line']}" for item in kept) or 'keine'
    head = [f'Qwen-Diagnose ({_request_label(rid)}), ungeprüft. Lokales Modell, nur Lesezugriff, nichts wurde '
            'ausgeführt. Der Text im Block stammt vom Modell und ist maschinell redigiert.',
            f"- Diagnose-Art: {result['fix_kind']}",
            f"- Sicherheit laut Modell: {round(result['confidence'] * 100)} %",
            f'- Geprüfte Stellen (Datei und Zeile bestätigt, Inhalt nicht zitiert): {places}',
            f'- Nicht bestätigte Stellen, entfernt: {unverified}',
            f"- Mensch nötig: {'ja' if result['needs_human'] else 'nein'}",
            f"- Modus: {result['mode']}, Werkzeugrunden: {result['rounds']}, abgerufene Seiten: "
            f"{len(result['fetched_urls'])}"]
    parts = [f"Zusammenfassung:\n{result['summary']}"]
    for title, key in (('Ursache', 'root_cause'), ('Vorschlag', 'suggestion'), ('Prüfung', 'verification')):
        if result[key].strip():
            parts.append(f'{title}:\n{result[key]}')
    reasons = [f"{item['path']}:{item['line']}: {item['why']}" for item in kept if item['why'].strip()]
    if reasons:
        parts.append('Begründung der Stellen:\n' + '\n'.join(reasons))
    if result['sources']:
        parts.append('Quellen:\n' + '\n'.join(result['sources']))
    model = '\n\n'.join(parts)
    text = '\n'.join(head) + '\n\n' + untrusted_block(model, literals)
    if final_scan(text) or _holds_literal(text, literals):
        text = '\n'.join(head) + '\n\n' + _WITHHELD
    if final_scan(text) or _holds_literal(text, literals):
        text = f'Qwen-Diagnose ({_request_label(rid)}): {_WITHHELD}'
    return text


def agent_uid(user_lookup=None) -> int | None:
    """uid of tim-agent; None when the user does not exist (ingest is then skipped, fail-closed)."""
    lookup = user_lookup or pwd.getpwnam
    try:
        uid = lookup(AGENT_USER).pw_uid
    except (KeyError, OSError, AttributeError, TypeError, ValueError):
        return None
    return uid if isinstance(uid, int) and not isinstance(uid, bool) and uid >= 0 else None


def _own_file(path: Path, own_uid: int | None) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and (own_uid is None or info.st_uid == own_uid)


def _present(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


@dataclass
class IngestReport:
    ingested: int = 0           # ok results turned into a comment (+ fields)
    failed: int = 0             # status 'failed' results: fixed reason comment
    rejected: int = 0           # results that failed the checks: fixed comment, never their content
    unknown: int = 0            # results without an own request: ignored, never acknowledged
    acked: tuple[str, ...] = ()
    skipped: str | None = None  # fixed reason when nothing was read


def ingest_diagnoses(results_dir, *, requests_dir, policy, now: datetime, spool=None, target=None, literals=(),
                     mode: str | None = None, user_lookup=None, root=REPO_ROOT, own_uid: int | None = None,
                     limit: int = INGEST_MAX) -> IngestReport:
    """Design B.8. For each result without an acknowledgement whose request is ours (requests/<rid>.json, regular,
    owned by `own_uid`): `protocol.read_result` (O_NOFOLLOW, owner tim-agent, <= 32 KB, strict schema, sources within
    fetched_urls on the domain list), `protocol.verify_locations` again under `root`, then spool entries: one comment
    (tag diagnosis-<rid>) and, for an 'ok' result, one 'fields' entry (enum and verified locations, incident:code
    only by rule B.6). The acknowledgement requests/<rid>.ack is written after the entries are queued, so a failure
    repeats the same idempotent entries next run. `spool` None: acknowledge without queueing (reporting off).
    `target(rid)` gives (issue class, active) of the episode; the default is the rid's class, active."""
    uid = agent_uid(user_lookup)
    if uid is None:
        return IngestReport(skipped='agent user unknown')
    results_dir, requests_dir = Path(results_dir), Path(requests_dir)
    report = IngestReport()
    acked = []
    for rid in protocol.list_rids(results_dir):
        if len(acked) >= limit:
            break
        if _present(requests_dir / protocol.ack_name(rid)):
            continue
        if not _own_file(requests_dir / protocol.request_name(rid), own_uid):
            report.unknown += 1
            continue
        episode, cls, _ = protocol.parse_rid(rid)
        issue_class, active = target(rid) if target is not None else (cls, True)
        base = {'v': 1, 'episode': episode, 'class': issue_class, 'host': policy.host, 'at': protocol.iso(now),
                'active': bool(active)}
        if mode in ('dry-run', 'on'):
            base['mode'] = mode
        entries = []
        try:
            result = protocol.read_result(results_dir, rid, expected_uid=uid, fetch_domains=policy.agent.fetch_domains)
        except protocol.ProtocolError as error:
            report.rejected += 1
            entries.append({**base, 'kind': 'comment', 'tag': diagnosis_tag(rid),
                            'text': diagnosis_rejected_text(rid, error.code)})
        else:
            if result['status'] == 'failed':
                report.failed += 1
                entries.append({**base, 'kind': 'comment', 'tag': diagnosis_tag(rid),
                                'text': diagnosis_failed_text(rid, result['reason'])})
            else:
                report.ingested += 1
                kept, removed = protocol.verify_locations(result['locations'], root)
                entries.append({**base, 'kind': 'comment', 'tag': diagnosis_tag(rid),
                                'text': diagnosis_text(rid, result, kept, removed, literals)})
                fields = {'fix_kind': result['fix_kind'],
                          'locations': list(dict.fromkeys(f"{item['path']}:{item['line']}" for item in kept))}
                entries.append({**base, 'kind': 'fields', 'fields': fields,
                                'labels': ['incident:code'] if code_label(result['fix_kind'], kept) else []})
        if spool is not None:
            for item in entries:
                spool.enqueue(item)
        protocol.write_ack(requests_dir, rid, now)
        acked.append(rid)
    report.acked = tuple(acked)
    return report


# -- entries and spool -------------------------------------------------------------------------------------------

def _parse_time(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError('time expected')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('time without zone')
    return parsed.astimezone(timezone.utc)


def _one_line(value, limit: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit and '\n' not in value and '\r' not in value


def validate_entry(entry) -> dict:
    """A checked copy of an outbox entry (contract 3); ValueError with a fixed text otherwise."""
    if not isinstance(entry, dict):
        raise ValueError('entry must be an object')
    data = {key: value for key, value in entry.items() if not str(key).startswith('_')}
    if data.get('v') != 1 or data.get('kind') not in KINDS:
        raise ValueError('entry version or kind invalid')
    if not isinstance(data.get('episode'), str) or not _EPISODE.match(data['episode']):
        raise ValueError('entry episode invalid')
    if data.get('class') not in CLASS_NAMES:
        raise ValueError('entry class invalid')
    if not isinstance(data.get('host'), str) or not _HOSTNAME.match(data['host']):
        raise ValueError('entry host invalid')
    try:
        _parse_time(data.get('at'))
    except (ValueError, TypeError):
        raise ValueError('entry time invalid') from None
    if not isinstance(data.get('active'), bool):
        raise ValueError('entry active flag invalid')
    kind = data['kind']
    if kind == 'open':
        if not _one_line(data.get('title'), MAX_TITLE):
            raise ValueError('entry title invalid')
        body = data.get('body')
        if not isinstance(body, str) or not body.strip() or len(body) > MAX_BODY:
            raise ValueError('entry body invalid')
        if body.rstrip('\n').rsplit('\n', 1)[-1] != incident_marker(data['class'], data['episode'], data['host']):
            raise ValueError('entry body must end with its incident marker')
        labels = data.get('labels')
        if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
            raise ValueError('entry labels invalid')
        if 'adopt_only' in data and not isinstance(data['adopt_only'], bool):
            raise ValueError('entry adopt_only invalid')
    elif kind == 'status_line':
        if not _one_line(data.get('status'), MAX_STATUS):
            raise ValueError('entry status invalid')
    elif kind == 'fields':
        try:
            data['fields'] = check_fields(data.get('fields'))
        except GuardError:
            raise ValueError('entry fields invalid') from None
        labels = data.get('labels')
        if not isinstance(labels, list) or not all(label in FIELD_LABELS for label in labels):
            raise ValueError('entry labels invalid')
    else:
        if not isinstance(data.get('tag'), str) or not _TAG.match(data['tag']):
            raise ValueError('entry tag invalid')
        text = data.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError('entry text invalid')
    if 'mode' in data and data['mode'] not in ('dry-run', 'on'):
        raise ValueError('entry mode invalid')
    commit = data.get('commit')
    if commit is not None and not (isinstance(commit, str) and _COMMIT.match(commit)):
        raise ValueError('entry commit invalid')
    for key in ('count', 'coalesced'):
        if key in data and (not isinstance(data[key], int) or isinstance(data[key], bool) or data[key] < 0):
            raise ValueError(f'entry {key} invalid')
    try:
        size = len(json.dumps(data, sort_keys=True, ensure_ascii=False).encode('utf-8'))
    except (TypeError, ValueError):
        raise ValueError('entry is not JSON') from None
    if size > MAX_ENTRY_BYTES:
        raise ValueError('entry too large')
    return data


def _holds_literal(text: str, literals) -> bool:
    compact = re.sub(r'\s+', '', text)
    return any(variant in text or re.sub(r'\s+', '', variant) in compact
               for secret in literals for variant in literal_variants(secret))


def scrub_entry(entry: dict, literals) -> dict:
    """Literal redaction for the spool (A.5): a known secret never lands on disk. A comment text that holds one is
    replaced whole (its fence could break), the other texts are redacted block by block; the body keeps its marker."""
    if not literals:
        return entry
    if 'text' in entry and _holds_literal(entry['text'], literals):
        entry['text'] = _TEXT_REPLACED
    for key in ('title', 'status'):
        if key in entry and _holds_literal(entry[key], literals):
            entry[key] = ' '.join(redact(entry[key], literals).split())
    if 'body' in entry and _holds_literal(entry['body'], literals):
        head, marker = entry['body'].rstrip('\n').rsplit('\n', 1)
        entry['body'] = f'{redact(head, literals)}\n{marker}'
    return entry


def _write_private(path: Path, data: bytes) -> None:
    """Atomic write with mode 0600 (tmp file, fsync, rename)."""
    tmp = path.with_name(f'.{path.name}.tmp')
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _append_private(path: Path, line: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        os.write(fd, line.encode('utf-8'))
    finally:
        os.close(fd)


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _dumps(data) -> bytes:
    return (json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


class Spool:
    """Outbox `outbox/<seq>-<kind>-<fp12>.json` (mode 0600). Order is the sequence number. Delivered entries move to
    `outbox/done/` and are never deleted; unreadable files move to `outbox/bad/`. Pass `literals`
    (`Reporter.literals`) so that no known secret is ever written here."""

    def __init__(self, directory, *, literals=(), coalesce_after: int = 500, clock=time.time):
        self.directory = _private_dir(Path(directory))
        self._literals = tuple(literals)
        self.done_dir = _private_dir(self.directory / 'done')
        self.bad_dir = self.directory / 'bad'
        self.coalesce_after = int(coalesce_after)
        self._clock = clock

    def _entries(self) -> list[dict]:
        found = []
        for path in sorted(self.directory.glob('*.json')):
            if not _ENTRY_ID.match(path.stem):
                continue
            try:
                info = os.lstat(path)
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ENTRY_BYTES + 4096:
                    raise ValueError('not a spool file')
                data = json.loads(path.read_text(encoding='utf-8'))
                clean = validate_entry(data)
                clean['queued_at'] = float(data.get('queued_at', info.st_mtime))
            except (OSError, ValueError, TypeError):
                _private_dir(self.bad_dir)
                os.replace(path, self.bad_dir / path.name)
                continue
            clean['_id'] = path.stem
            found.append(clean)
        return found

    def pending(self) -> list[dict]:
        return self._entries()

    def _rewrite(self, entry: dict) -> None:
        data = {key: value for key, value in entry.items() if key != '_id'}
        _write_private(self.directory / f'{entry["_id"]}.json', _dumps(data))

    def _next_seq(self, entries) -> int:
        counter = self.directory / '.seq'
        top = max((int(entry['_id'][:12]) for entry in entries), default=0)
        try:
            top = max(top, int(counter.read_text(encoding='ascii').strip()))
        except (OSError, ValueError):
            for path in self.done_dir.glob('*.json'):        # counter lost: never reuse a number of a done entry
                if path.stem[:12].isdigit():
                    top = max(top, int(path.stem[:12]))
        _write_private(counter, f'{top + 1}\n'.encode('ascii'))
        return top + 1

    def enqueue(self, entry) -> str:
        """Store `entry` (validated, known secrets removed) and return its id; a status line right after a status
        line of the same class and episode, and above `coalesce_after` any comment or status line, only grows a counter."""
        clean = scrub_entry(validate_entry(entry), self._literals)
        entries = self._entries()
        same = [item for item in entries if entry_key(item) == entry_key(clean)]
        last = same[-1] if same else None
        if clean['kind'] == 'status_line' and last is not None and last['kind'] == 'status_line':
            last['count'] = last.get('count', 1) + clean.get('count', 1)
            last['status'], last['at'], last['active'] = clean['status'], clean['at'], clean['active']
            self._rewrite(last)
            return last['_id']
        if entries and len(entries) >= self.coalesce_after and clean['kind'] in ('comment', 'status_line'):
            target = last or entries[-1]
            target['coalesced'] = target.get('coalesced', 0) + 1     # above the limit only a counter grows
            self._rewrite(target)
            return target['_id']
        clean.pop('queued_at', None)
        digest = hashlib.sha256(json.dumps(clean, sort_keys=True).encode('utf-8')).hexdigest()[:12]
        name = f'{self._next_seq(entries):012d}-{clean["kind"]}-{digest}'
        clean['queued_at'] = float(self._clock())
        _write_private(self.directory / f'{name}.json', _dumps(clean))
        return name

    def mark_done(self, entry_id: str, note: str = '') -> None:
        if not _ENTRY_ID.match(entry_id or ''):
            raise KeyError('unknown spool entry')
        source = self.directory / f'{entry_id}.json'
        try:
            data = json.loads(source.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise KeyError('unknown spool entry') from None
        data['done'] = {'at': float(self._clock()), 'note': str(note)[:200]}
        target, n = self.done_dir / f'{entry_id}.json', 0
        while target.exists():
            n += 1
            target = self.done_dir / f'{entry_id}.{n}.json'
        _write_private(target, _dumps(data))
        source.unlink()

    def oldest_pending_seconds(self, now: float) -> float | None:
        times = [entry['queued_at'] for entry in self._entries()]
        return max(0.0, float(now) - min(times)) if times else None


# -- delivery ----------------------------------------------------------------------------------------------------

@dataclass
class DeliveryReport:
    reporting: str      # off | dry-run | on | revoked | silenced | forbidden | token_invalid | key_missing |
                        # rate_limited | network_down | authority_missing
    preflight: str      # 'ok' | 'skipped' | fixed failure text
    delivered: int
    pending: int
    oldest_pending_seconds: float | None
    exit_code: int      # 0 or 3 (design A.1)
    notes: tuple[str, ...] = ()
    writes: int = 0


class _Stop(Exception):
    def __init__(self, reporting: str):
        super().__init__(reporting)
        self.reporting = reporting


def _empty_state() -> dict:
    # changed, silent, uncertain, active and kept_open are keyed by entry_key ('CLASS/episode')
    return {'v': 1, 'creates': [], 'comments': {}, 'changed': {}, 'silent': {}, 'status_at': {}, 'pause': None,
            'forbidden_strikes': 0, 'quiet': False, 'uncertain': {}, 'not_sent': {}, 'active': {}, 'kept_open': {}}


class Reporter:
    """Delivers the spool according to design B.4. Build it with `build_reporter`."""

    def __init__(self, settings, policy, *, data_dir, credentials_dir=None, transport=None, runner=None,
                 clock=time.time, monotonic=time.monotonic):
        self.settings, self.policy = settings, policy
        self.mode = settings.reporting
        self.data_dir = Path(data_dir)
        self.incidents_dir = self.data_dir / 'incidents'
        self._key = github_app.key_path(credentials_dir)
        self._transport = incident_transport if transport is None else transport
        self._runner, self._clock, self._monotonic = runner, clock, monotonic
        self._gateway: IncidentGateway | None = None
        self._failure: str | None = None
        self._failure_text: str | None = None
        self._controls: Controls | None = None
        self._registry: TaskRegistry | None = None
        self._literals: tuple[str, ...] = ()
        self._notes: list[str] = []
        self.claimant = f'{policy.host}/tim-checkup'

    def __repr__(self):
        return f'Reporter(mode={self.mode!r})'

    # -- session -----------------------------------------------------------
    @property
    def literals(self) -> tuple[str, ...]:
        """Known secrets for literal redaction (key lines, DB password, installation token). In memory only."""
        return self._literals

    def _load_literals(self) -> None:
        found = list(github_app.key_lines(self._key))
        secret_file = getattr(self.settings, 'database_secret_file', None)
        if secret_file:
            try:
                with open(secret_file, 'rb') as handle:
                    value = handle.read(4097).decode('utf-8', 'replace').strip()
                if value and len(value) <= 4096:
                    found.append(value)
            except OSError:
                pass
        self._literals = tuple(dict.fromkeys(found))

    def close(self) -> None:
        """Close the registry file (the token stays only in this object's memory until it is dropped)."""
        if self._registry is not None:
            self._registry.close()
            self._registry = None

    def registry(self) -> TaskRegistry:
        if self._registry is None:
            _private_dir(self.incidents_dir)
            self._registry = TaskRegistry(str(self.incidents_dir / 'registry.sqlite'), clock=self._clock)
        return self._registry

    def _session(self) -> IncidentGateway | None:
        if self._gateway is not None or self._failure is not None:
            return self._gateway
        self._load_literals()
        settings = self.settings
        try:
            token = github_app.mint_installation_token(
                settings.app_id, settings.installation_id, self._key, runner=self._runner, transport=self._transport,
                now=int(self._clock()), repository_name=self.policy.repository.split('/', 1)[1])
        except github_app.AppTokenError as error:
            self._failure = error.kind
            return None
        self._literals = self._literals + (token,)
        self._gateway = IncidentGateway(
            self.policy.repository, token, reporter_login=settings.reporter_login, owner_login=settings.owner_login,
            authority_issue=settings.authority_issue, watch_issue=settings.watch_issue, transport=self._transport,
            write_budget=self.policy.rate_limits.writes_per_run)
        del token
        return self._gateway

    def _classify(self, error) -> str:
        if isinstance(error, RepositoryNotVisible):
            return github_app.TOKEN_INVALID     # the installation does not cover the repository: exit 3
        if isinstance(error, NetworkDown):
            return github_app.NETWORK_DOWN
        if isinstance(error, HTTPStatusError):
            return {401: github_app.TOKEN_INVALID, 403: github_app.FORBIDDEN,
                    429: github_app.RATE_LIMITED}.get(error.status, github_app.NETWORK_DOWN)
        return github_app.NETWORK_DOWN          # GitHub answered nothing usable: treated like an outage

    def read_controls(self) -> Controls:
        """State and labels of the authority issue (one GET). Never raises."""
        if self.mode == 'off' or not self.settings.complete:
            self._controls = NOT_CONFIGURED
            return NOT_CONFIGURED
        try:
            gateway = self._session()
            if gateway is None:
                controls = Controls('unknown', frozenset())
            else:
                controls = gateway.read_controls(self.registry().registry_id)
        except Exception as error:              # never raises; the failure kind decides the report
            self._failure = self._classify(error)
            if isinstance(error, RepositoryNotVisible):
                self._failure_text = 'repository not visible'
            controls = Controls('unknown', frozenset())
        self._controls = controls
        return controls

    def open_incidents(self) -> list[dict] | None:
        """Open incident issues of the reporter, for adopting after a lost state; None when GitHub cannot be read."""
        if self.mode == 'off' or not self.settings.complete:
            return None
        try:
            gateway = self._session()
            return None if gateway is None else gateway.open_incidents()
        except Exception:
            return None

    # -- report helpers ----------------------------------------------------
    def _report(self, spool, reporting: str, preflight: str, delivered: int = 0, state=None) -> DeliveryReport:
        now = self._clock()
        pending = spool.pending()
        oldest = spool.oldest_pending_seconds(now)
        exit_code = 0
        if reporting in (github_app.KEY_MISSING, github_app.TOKEN_INVALID):
            exit_code = 3
        elif reporting == github_app.FORBIDDEN and state is not None and state.get('forbidden_strikes', 0) >= 2:
            exit_code = 3
        elif reporting not in ('off', 'dry-run', 'revoked', 'silenced') and oldest is not None \
                and oldest > self.policy.limits.spool_alarm_minutes * 60:
            exit_code = 3
        writes = self._gateway.writes if self._gateway is not None else 0
        return DeliveryReport(reporting, preflight, delivered, len(pending), oldest, exit_code, tuple(self._notes),
                              writes)

    def _load_state(self) -> dict:
        state = _empty_state()
        try:
            data = json.loads((self.incidents_dir / 'delivery.json').read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('v') == 1:
                state.update({key: data[key] for key in state if key in data})
        except (OSError, ValueError):
            pass
        return state

    def _save_state(self, state) -> None:
        now = self._clock()
        state['creates'] = [t for t in state['creates'] if now - t < 86400]
        comments = {}
        for number, times in state['comments'].items():
            recent = [t for t in times if now - t < 86400]
            if recent:
                comments[number] = recent
        state['comments'] = comments
        for key in ('changed', 'silent', 'uncertain', 'active', 'kept_open'):
            state[key] = {ep: value for ep, value in state[key].items() if now - value.get('at', now) < STATE_KEEP_SECONDS}
        _private_dir(self.incidents_dir)
        _write_private(self.incidents_dir / 'delivery.json', _dumps(state))

    def _clean_text(self, text: str) -> str:
        """Comment text as sent. The checkup already redacted and fenced the untrusted parts; running the regex chain
        again could rewrite a closing fence, so only the known secrets and `final_scan` are checked here, and a hit
        replaces the whole text by a fixed notice."""
        text = text.replace('\r\n', '\n').replace('\r', '\n').replace('<!--', '<\u200b!--')
        if _holds_literal(text, self._literals) or final_scan(text):
            return _TEXT_REPLACED
        return text

    # -- deliver -----------------------------------------------------------
    def deliver(self, spool: Spool, *, deadline: float) -> DeliveryReport:
        """Deliver pending entries in order until `deadline` (a `time.monotonic()` value)."""
        self._notes = []
        if self.mode == 'off':
            return self._report(spool, 'off', PREFLIGHT_SKIPPED)
        controls = self._controls if self._controls is not None else self.read_controls()
        if self.mode == 'dry-run':
            return self._dry_run(spool, controls)
        state = self._load_state()
        if self._failure is not None:
            if self._failure in (github_app.FORBIDDEN, github_app.RATE_LIMITED):
                self._strike(self._failure, state)
                self._save_state(state)
            return self._report(spool, self._failure, self._failure_text or _FAILURE_TEXT[self._failure], state=state)
        gateway = self._gateway
        if gateway is None:
            return self._report(spool, 'authority_missing', 'not configured')
        if controls.authority == 'closed':
            state['quiet'] = True
            self._save_state(state)
            return self._report(spool, 'revoked', 'authority closed')
        if not controls.open:
            return self._report(spool, 'authority_missing', gateway.authority_problem)
        if controls.silenced:
            state['quiet'] = True
            self._save_state(state)
            return self._report(spool, 'silenced', PREFLIGHT_OK)
        now = self._clock()
        pause = state.get('pause')
        if pause and now < pause.get('until', 0):
            kind = pause.get('kind', github_app.FORBIDDEN)
            return self._report(spool, kind, _FAILURE_TEXT.get(kind, PREFLIGHT_OK), state=state)
        state['pause'] = None
        reporting, delivered = 'on', 0
        try:
            if state.get('quiet'):
                self._summarize(spool, state)
            delivered = self._deliver_entries(spool, state, deadline)
            self._follow_up(spool, state, deadline)
        except _Stop as stop:
            reporting = stop.reporting
        except (NetworkDown, HTTPStatusError) as error:       # raised by the summary
            reporting = self._stop_for(error, state).reporting
        except WriteBudgetExceeded:
            self._notes.append('write budget of this run used up')
        except (GuardError, GitHubError) as error:            # summary refused or failed: deliver nothing this run
            self._notes.append(f'summary not posted: {error}')
        finally:
            if gateway.writes_ok:
                state['forbidden_strikes'] = 0
            self._save_state(state)
        preflight = _FAILURE_TEXT.get(reporting, PREFLIGHT_OK)
        return self._report(spool, reporting, preflight, delivered, state)

    def _strike(self, kind, state) -> None:
        """403: pause writes, and count it (twice in a row without a successful write is `forbidden`, exit 3).
        429: pause writes. A pause that is still running is not extended."""
        now, limits = self._clock(), self.policy.rate_limits
        pause = state.get('pause')
        if pause and now < pause.get('until', 0):
            return
        if kind == github_app.FORBIDDEN:
            state['forbidden_strikes'] = state.get('forbidden_strikes', 0) + 1
            state['pause'] = {'kind': kind, 'until': now + limits.pause_after_forbidden_minutes * 60}
        elif kind == github_app.RATE_LIMITED:
            state['pause'] = {'kind': kind, 'until': now + limits.pause_after_rate_limit_minutes * 60}

    def _stop_for(self, error, state):
        kind = self._classify(error)
        self._strike(kind, state)
        return _Stop(kind)

    def _deliver_entries(self, spool, state, deadline) -> int:
        gateway, budget = self._gateway, self.policy.rate_limits.writes_per_run
        waiting, delivered = set(), 0
        for entry in spool.pending():
            key = entry_key(entry)
            if key in waiting:
                continue                        # order within an episode: nothing overtakes a waiting entry
            if self._monotonic() >= deadline:
                self._notes.append('deadline reached')
                break
            if gateway.writes >= budget:
                self._notes.append('write budget of this run used up')
                break
            try:
                verdict, note = self._deliver_entry(entry, state, deadline)
            except CreateRefused as error:
                verdict, note = 'done', f'refused: {error}'
            except CreateRejected as error:
                if error.status in (401, 403, 429):
                    raise self._stop_for(HTTPStatusError(error.status, str(error)), state) from None
                verdict, note = 'wait', str(error)
            except CreateNotSent:
                self._remember_not_sent(entry, state)
                raise _Stop(github_app.NETWORK_DOWN) from None
            except (NetworkDown, HTTPStatusError) as error:
                raise self._stop_for(error, state) from None
            except GuardError as error:
                verdict, note = 'done', f'refused: {error}'
            except WriteBudgetExceeded:
                self._notes.append('write budget of this run used up')
                break
            except GitHubError as error:
                verdict, note = 'wait', f'github error: {error}'
            if verdict == 'done':
                spool.mark_done(entry['_id'], note)
                delivered += 1
            elif verdict == 'stop':
                self._notes.append(note)
                break
            else:
                waiting.add(key)
                self._notes.append(f'{key}: {note}')
        return delivered

    def _follow_up(self, spool, state, deadline) -> None:
        """Per run, for issues no entry touched: the note for an issue a person closed while the incident is still
        active (B.4), and the late close of an issue kept open at the comment limit once it stayed quiet a day."""
        gateway, budget = self._gateway, self.policy.rate_limits.writes_per_run
        busy = {entry_key(entry) for entry in spool.pending()}
        for key, info in list(state['active'].items()):
            if key in busy or key in state['silent'] or self._monotonic() >= deadline or gateway.writes >= budget:
                continue
            issue = gateway.issue_state(info['issue'])
            if issue is None:
                state['active'].pop(key, None)
            elif issue['state'] == 'closed' and not (issue['closed_by_reporter']
                                                     and issue['state_reason'] == 'completed'):
                try:
                    self._human_closed(info['issue'], key, info.get('commit'), state)
                except GuardError as error:
                    state['active'].pop(key, None)
                    self._notes.append(f'{key}: human-closed note refused: {error}')
        now = self._clock()
        for key, info in list(state['kept_open'].items()):
            if key in busy or now - info['at'] < self.policy.hysteresis.status_line_hours * 3600:
                continue
            if self._monotonic() >= deadline or gateway.writes + 2 > budget:
                break
            episode = key.split('/', 1)[1]
            issue = gateway.issue_state(info['issue'])
            state['kept_open'].pop(key, None)
            if issue is not None and issue['state'] == 'open':
                try:
                    gateway.comment_once(info['issue'], f"{info['tag']}-late", kept_open_closing_text(info['at']),
                                         episode=episode)
                    gateway.close_incident(info['issue'], episode=episode)
                except GuardError as error:
                    self._notes.append(f'{key}: late close refused: {error}')

    def _remember_not_sent(self, entry, state) -> None:
        request = task_request(entry['class'], entry['episode'], entry['host'])
        mapping = self.registry().get(request.fingerprint)
        if mapping is not None and mapping.state is MappingState.CLAIMED and mapping.create_intent:
            state['not_sent'][request.fingerprint] = mapping.claim_token

    def _issue_for(self, request) -> int | None:
        mapping = self.registry().get(request.fingerprint)
        if mapping is None or mapping.state is not MappingState.MAPPED or mapping.github_issue_number is None:
            return None
        if normalize_repository(mapping.github_repository or '') != normalize_repository(self.policy.repository):
            return None
        return mapping.github_issue_number

    def _deliver_entry(self, entry, state, deadline) -> tuple[str, str]:
        if entry['host'] != self.policy.host:
            return 'done', 'refused: host is not this server'
        episode, kind, key = entry['episode'], entry['kind'], entry_key(entry)
        if self.mode == 'on' and entry.get('mode') == 'dry-run':
            return 'done', 'dry-run entry: not sent'
        if kind == 'open':
            verdict, note = self._open(entry, state, deadline)
            number = self._issue_for(task_request(entry['class'], episode, entry['host']))
            if verdict == 'done' and number is not None and key not in state['silent']:
                state['active'][key] = {'issue': number, 'commit': entry.get('commit'), 'at': self._clock()}
            return verdict, note
        if key in state['silent']:
            return 'done', 'silent: closed by a person'
        number = self._issue_for(task_request(entry['class'], episode, entry['host']))
        if number is None:
            return 'done', 'no issue for this episode'
        gateway = self._gateway
        issue = gateway.issue_state(number)
        if issue is None:
            state['active'].pop(key, None)
            return 'done', 'issue does not exist'
        if entry['active']:
            state['active'][key] = {'issue': number, 'commit': entry.get('commit'), 'at': self._clock()}
            state['kept_open'].pop(key, None)
        else:
            state['active'].pop(key, None)
        closed = issue['state'] == 'closed'
        by_person = closed and not (issue['closed_by_reporter'] and issue['state_reason'] == 'completed')
        if by_person:
            if entry['active']:
                return self._human_closed(number, key, entry.get('commit'), state)
            return 'done', 'closed by a person'
        if kind == 'status_line':
            return self._status(number, issue, entry, state)
        if kind == 'fields':
            return self._fields(number, issue, entry)
        if kind == 'comment':
            return self._post_comment(number, entry, state)
        if kind == 'resolve':
            if closed:
                return 'done', 'already closed'
            if not self._comment_allowed(number, entry, state):
                # B.7: at the limit a close would be one more notification, and a flapping cause would reopen it
                # soon; the issue stays open with a status line and closes after a quiet day (_follow_up)
                gateway.set_status_line(number, kept_open_status_text(entry['at']), episode=episode)
                state['kept_open'][key] = {'issue': number, 'tag': entry['tag'], 'at': self._clock()}
                return 'done', 'comment limit: resolved, issue kept open'
            self._post_comment(number, entry, state)
            gateway.close_incident(number, episode=episode)
            return 'done', 'resolved and closed'
        # reopen
        if closed and not gateway.reopen_incident(number, episode=episode):
            return 'done', 'not reopened'
        self._post_comment(number, entry, state)
        return 'done', 'reopened' if closed else 'already open'

    def _comment_allowed(self, number, entry, state) -> bool:
        now, limits = self._clock(), self.policy.rate_limits
        times = [t for t in state['comments'].get(str(number), []) if now - t < 86400]
        if len(times) >= limits.comments_per_incident_per_day:
            return False
        changed = state['changed'].get(entry_key(entry), {}).get('count', 0)
        return not (entry['tag'].startswith('changed') and changed >= limits.changed_per_episode)

    def _post_comment(self, number, entry, state) -> tuple[str, str]:
        gateway, episode, key = self._gateway, entry['episode'], entry_key(entry)
        if not self._comment_allowed(number, entry, state):
            gateway.set_status_line(number, limit_status_text(entry['at'], entry['tag']), episode=episode)
            return 'done', 'comment limit: status line instead'
        if gateway.comment_once(number, entry['tag'], self._clean_text(entry['text']), episode=episode):
            now = self._clock()
            state['comments'].setdefault(str(number), []).append(now)
            if entry['tag'].startswith('changed'):
                old = state['changed'].get(key, {}).get('count', 0)
                state['changed'][key] = {'count': old + 1, 'at': now}
            return 'done', 'comment posted'
        return 'done', 'comment already posted'

    def _status(self, number, issue, entry, state) -> tuple[str, str]:
        if issue['frozen']:
            return 'done', 'body frozen'
        now, last = self._clock(), state['status_at'].get(str(number))
        if last is not None and now - last < self.policy.hysteresis.status_line_hours * 3600:
            return 'done', 'status line too soon'
        line = redact(status_text(entry), self._literals)
        self._gateway.set_status_line(number, line, episode=entry['episode'])
        state['status_at'][str(number)] = now
        return 'done', 'status line set'

    def _fields(self, number, issue, entry) -> tuple[str, str]:
        """FIELDS section and the incident:code label of a verified diagnosis; nothing once the body is frozen (E6)."""
        if issue['frozen']:
            return 'done', 'body frozen'
        self._gateway.set_fields(number, entry['fields'], episode=entry['episode'])
        labels = [label for label in entry.get('labels') or () if label in FIELD_LABELS and label_allowed(label)]
        if labels:
            self._gateway.add_labels(number, labels, episode=entry['episode'])
        return 'done', 'fields set'

    def _human_closed(self, number, key, commit, state) -> tuple[str, str]:
        self._gateway.comment_once(number, 'human-closed', human_closed_text(commit), episode=key.split('/', 1)[1])
        state['silent'][key] = {'issue': number, 'at': self._clock()}
        state['active'].pop(key, None)
        state['kept_open'].pop(key, None)
        return 'done', 'closed by a person while active: note posted, episode silent'

    def _open_request(self, entry) -> tuple[TaskRequest, list[str]]:
        head, marker = entry['body'].rstrip('\n').rsplit('\n', 1)
        body = f'{redact(head, self._literals)}\n{marker}'
        title = ' '.join(redact(entry['title'], self._literals).split())
        request = task_request(entry['class'], entry['episode'], entry['host'], title, body)
        labels = [label for label in entry['labels'] if label_allowed(label)]
        if len(labels) != len(entry['labels']):
            self._notes.append(f'{entry["class"]}/{entry["episode"]}: labels outside the allowlist dropped')
        return request, labels

    def _open(self, entry, state, deadline) -> tuple[str, str]:
        gateway, registry, episode, key = self._gateway, self.registry(), entry['episode'], entry_key(entry)
        request, labels = self._open_request(entry)
        number = self._issue_for(request)
        if number is not None:
            gateway.add_labels(number, labels, episode=episode)
            return 'done', 'issue exists'
        adopt_only = entry.get('adopt_only') is True
        self._release_not_sent(request, state)
        self._confirm_not_created(request, key)
        if not adopt_only:
            now, limits = self._clock(), self.policy.rate_limits
            if sum(1 for t in state['creates'] if now - t < 3600) >= limits.new_issues_per_hour \
                    or sum(1 for t in state['creates'] if now - t < 86400) >= limits.new_issues_per_day:
                return 'wait', 'new issue limit reached'
            if deadline - self._monotonic() < self.policy.limits.create_min_remaining_seconds:
                return 'stop', 'too little time left for a create'
            if gateway.writes + CREATE_WRITES > self.policy.rate_limits.writes_per_run:
                return 'stop', 'write budget too small for a create'
        result = ensure_task(request, registry, _AdoptOnly(gateway) if adopt_only else gateway,
                             claimant=self.claimant,
                             trusted_authors=[self.settings.reporter_login, self.settings.owner_login])
        if result.outcome is not EnsureOutcome.BLOCKED and result.outcome is not EnsureOutcome.PENDING \
                and result.issue_number is not None:
            if result.created:
                state['creates'].append(self._clock())
            state['uncertain'].pop(key, None)
            gateway.add_labels(result.issue_number, labels, episode=episode)
            return 'done', result.outcome.value.lower()
        if result.outcome is EnsureOutcome.PENDING:
            return 'wait', 'claim held'
        if result.detail == 'CREATE_NOT_AUTHORIZED':
            return ('done', 'adopt only: no issue found') if adopt_only else ('wait', 'create not authorized')
        if result.detail == 'CREATE_UNCERTAIN':
            since = state['uncertain'].setdefault(key, {'at': self._clock()})['at']
            if self._clock() - since > CREATE_UNCERTAIN_NOTE_SECONDS:
                path = self._confirm_path(key)
                self._notes.append(f"confirm-not-created: sudo sh -c 'install -o tim -g tim -m 0600 /dev/null {path}"
                                   " && systemctl start tim-checkup.service'")
            return 'wait', 'create uncertain'
        return 'wait', f'blocked: {result.detail}'

    def _release_not_sent(self, request, state) -> None:
        """A create that our transport proved unsent, but that ensure_task could not verify then (network gone):
        verify now and release the claim, so it does not turn into CREATE_UNCERTAIN."""
        token = state['not_sent'].pop(request.fingerprint, None)
        if token is None:
            return
        registry = self.registry()
        mapping = registry.get(request.fingerprint)
        if mapping is None or mapping.state is not MappingState.CLAIMED or not mapping.create_intent \
                or mapping.claim_token != token:
            return
        if not self._gateway.find_issues(request.fingerprint, request.key):
            registry.release(request.fingerprint, token, create_not_sent=True)

    def _confirm_path(self, key: str) -> Path:
        cls, episode = key.split('/', 1)
        return self.incidents_dir / f'confirm-not-created.{cls}.{episode}'

    def _confirm_not_created(self, request, key) -> None:
        """B.4: the owner's file `confirm-not-created.<CLASS>.<episode>` clears an uncertain create after the fixed
        checks (no issue with the task marker in the full listing, at least 1 h since the create started)."""
        path = self._confirm_path(key)
        try:
            if not stat.S_ISREG(os.lstat(path).st_mode):
                return
        except OSError:
            return
        registry = self.registry()
        mapping = registry.get(request.fingerprint)
        if mapping is None or not mapping.create_intent or mapping.state not in (MappingState.BLOCKED, MappingState.RELEASED):
            return
        if self._gateway.find_issues(request.fingerprint, request.key):
            self._notes.append(f'{key}: confirm-not-created refused, an issue with the marker exists')
            return
        if registry.confirm_not_created(request.fingerprint, 'confirm-not-created file of the owner',
                                        quiet_seconds=CONFIRM_QUIET_SECONDS):
            os.replace(path, path.with_name(f'{path.name}.used'))
            self._notes.append(f'{key}: confirm-not-created applied')
        else:
            self._notes.append(f'{key}: confirm-not-created refused, create attempt too recent or claim held')

    def _summarize(self, spool, state) -> None:
        """After silence or revocation: one summary comment for episodes that resolved meanwhile; their entries do not
        become single issues. An episode that already has an issue still gets its resolve entry (comment, close)."""
        groups: dict[str, list[dict]] = {}
        for entry in spool.pending():
            if entry.get('mode') != 'dry-run':         # left over from a dry-run: not sent at all (_deliver_entry)
                groups.setdefault(entry_key(entry), []).append(entry)
        resolved = {key: entries for key, entries in groups.items()
                    if entries[-1]['kind'] == 'resolve' or not entries[-1]['active']}
        if resolved:
            items, issues = [], {}
            for key, entries in resolved.items():
                first = entries[0]
                issues[key] = self._issue_for(task_request(first['class'], first['episode'], first['host']))
                items.append({'class': first['class'], 'episode': first['episode'], 'at': first['at'],
                              'issue': issues[key]})
            self._gateway.post_summary(items)
            for key, entries in resolved.items():
                keep = entries[-1] if issues[key] is not None and entries[-1]['kind'] == 'resolve' else None
                for entry in entries:
                    if entry is not keep:
                        spool.mark_done(entry['_id'], 'summarized')
        state['quiet'] = False

    # -- dry run -----------------------------------------------------------
    def _preflight(self) -> str:
        if self._failure is not None:
            return self._failure_text or _FAILURE_TEXT[self._failure]
        gateway = self._gateway
        if gateway is None:
            return 'not configured'
        try:
            if not gateway.repository_visible():
                return 'repository not visible'
            if gateway.authority_problem != PREFLIGHT_OK:
                return gateway.authority_problem
            missing = gateway.missing_labels(sorted(LABEL_ALLOWLIST))
        except Exception as error:
            return _FAILURE_TEXT[self._classify(error)]
        return f'labels missing: {", ".join(missing)}' if missing else PREFLIGHT_OK

    def _dry_run(self, spool, controls) -> DeliveryReport:
        """Only GETs. Every would-be write goes to data/incidents/dryrun.jsonl; the entry moves to done. Entries
        queued while reporting was 'on' stay pending for the next 'on' run (their episode is already announced)."""
        preflight = self._preflight()
        if not self._literals:
            self._load_literals()
        _private_dir(self.incidents_dir)
        log, delivered = self.incidents_dir / 'dryrun.jsonl', 0
        run_at = datetime.fromtimestamp(self._clock(), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        held = 0
        for entry in spool.pending():
            if entry.get('mode') == 'on':
                held += 1
                continue
            record = {'run_at': run_at, 'id': entry['_id'], 'kind': entry['kind'], 'class': entry['class'],
                      'episode': entry['episode'], 'at': entry['at'], 'authority': controls.authority}
            if entry['kind'] == 'open':
                request, labels = self._open_request(entry)
                record.update(would='create_issue' if not entry.get('adopt_only') else 'adopt_issue',
                              title=request.title, labels=labels, body=request.body)
            elif entry['kind'] == 'status_line':
                record.update(would='set_status_line', status=redact(status_text(entry), self._literals))
            elif entry['kind'] == 'fields':
                record.update(would='set_fields', fields=entry['fields'], labels=entry.get('labels') or [])
            else:
                record.update(would={'comment': 'comment', 'resolve': 'comment_and_close',
                                     'reopen': 'reopen_and_comment'}[entry['kind']],
                              tag=entry['tag'], text=self._clean_text(entry['text']))
            _append_private(log, json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
            spool.mark_done(entry['_id'], 'dry-run')
            delivered += 1
        if held:
            self._notes.append(f"{held} entries from reporting 'on' kept for the next 'on' run")
        return self._report(spool, 'dry-run', preflight, delivered)


def build_reporter(settings, policy, *, data_dir: Path, credentials_dir: Path | None, transport=None, runner=None,
                   clock=time.time, monotonic=time.monotonic) -> Reporter:
    """The reporter for one checkup run. No network here; the token is minted on the first `read_controls`.
    `runner(argv, *, input: bytes, timeout: float)` runs openssl and returns an object with `returncode` and
    `stdout` (bytes); the default uses subprocess without a shell."""
    return Reporter(settings, policy, data_dir=data_dir, credentials_dir=credentials_dir, transport=transport,
                    runner=runner, clock=clock, monotonic=monotonic)
