"""Update-first synchronisation: existing task -> update, otherwise create exactly once."""
from dataclasses import dataclass
from enum import Enum
from typing import Collection, Protocol

_UNBLOCKABLE_BY_HINT = ('AMBIGUOUS_DUPLICATES', 'DUPLICATE_AFTER_CREATE', 'HINT_NOT_FOUND', 'HINT_INVALID')
MIN_LEASE_FACTOR = 4      # lease must be at least this many times the gateway's worst-case create time
CREATE_FRESHNESS_SECONDS = 80.0   # a create rests on a lookup and an authority answer at most this old (#68): 4 x the default
                                  # create bound of 20 s, measured by the clock that moved further (monotonic or wall)
HOLDER_HOST_CHARS = 16            # of the host name in the create-claim text (GitHub: 100 characters for a label description)

import socket
import time

from .identity import TaskRequest
from .create_authority import CreateNotAuthorized
from .legacy import LEGACY_AUTHORITIES
from .repository_names import normalize_repository
from .registry import Mapping, MappingState, TaskRegistry


@dataclass(frozen=True)
class IssueRef:
    number: int
    state: str          # 'open' | 'closed'
    title: str = ''
    author: str = ''
    is_pull_request: bool | None = None    # None = gateway did not say: the guard BLOCKS, it neither adopts nor creates


class UnknownIssueKind(Exception):
    """A marker match whose issue-vs-PR status the gateway did not report."""

    def __init__(self, numbers):
        super().__init__(f'unknown issue kind for {sorted(numbers)}')
        self.numbers = sorted(numbers)


class CreateNotSent(Exception):
    """Raised by a gateway when create_issue failed before any request left the process.
    Only then may the claim be released at once; every other failure is treated as uncertain."""


class IssueGateway(Protocol):
    """The only GitHub surface the guard may use. It has no close operation, and
    `mark_duplicate`/`update_issue` must only comment or label, never change state.

    Contract for implementers:
    - `find_issues` lists issues carrying the fingerprint marker (not the lagging search index). The REST listing lags too:
      the gateway reads the numbers around its highest entry one by one so an issue created a moment ago is not missed.
    - `update_issue` also writes the marker into the issue body, which back-fills issues that
      predate the marker (e.g. #11 and #22-#65).
    - `create_issue` embeds the marker in the body.
    - `authorize_create` is asked before every create (#68 path A, see `create_authority.py`); a gateway without it never creates.
    - `claim_create` takes the repository-wide create claim of the task, something the repository hands out at most once
      per task until `release_create_claim` (the REST gateway: a label). It returns None when the claim is now ours, else
      a text naming the holder. A gateway without it never creates either.
    """
    repository: str
    max_create_seconds: float   # REQUIRED: hard upper bound (enforced via `timeout`) of one create_issue call incl. retries

    def find_issues(self, fingerprint: str, canonical_key: str) -> list[IssueRef]: ...
    def get_issue(self, number: int) -> IssueRef | None: ...
    def carries_marker(self, number: int, fingerprint: str) -> bool: ...   # the issue exists and still has the task marker
    def authorize_create(self, registry_id: str, trusted_authors) -> None: ...   # raise CreateNotAuthorized unless the repository designates this registry
    def claim_create(self, fingerprint: str, holder: str) -> str | None: ...    # None: the create claim is ours; else who holds it
    def release_create_claim(self, fingerprint: str) -> None: ...
    def create_issue(self, request: TaskRequest, fingerprint: str, *, timeout: float) -> IssueRef: ...   # must enforce `timeout`
    def update_issue(self, number: int, request: TaskRequest, reason: str) -> None: ...
    def reopen_issue(self, number: int, request: TaskRequest, reason: str) -> None: ...
    def is_documented_duplicate(self, number: int, authoritative: int) -> bool: ...
    def mark_duplicate(self, number: int, authoritative: int) -> None: ...


class ReopenPolicy(str, Enum):
    NEVER = 'NEVER'          # closed authoritative issue stays closed, only an audit comment is added
    EXPLICIT = 'EXPLICIT'    # reopen only when the caller passes retry=True


class EnsureOutcome(str, Enum):
    CREATED = 'CREATED'
    UPDATED = 'UPDATED'                # existing mapped issue synced, nothing created
    RECOVERED = 'RECOVERED'            # existing GitHub issue adopted without local mapping, nothing created
    REOPENED = 'REOPENED'
    PENDING = 'PENDING'                # another live worker holds the claim, nothing created
    BLOCKED = 'BLOCKED'                # ambiguous/violated uniqueness, escalated


@dataclass(frozen=True)
class EnsureResult:
    outcome: EnsureOutcome
    mapping: Mapping
    created: bool
    issue_number: int | None
    detail: str = ''


def ensure_task(request: TaskRequest, registry: TaskRegistry, gateway: IssueGateway, *, claimant: str,
                policy: ReopenPolicy = ReopenPolicy.NEVER, retry: bool = False,
                trusted_authors: Collection[str] | None, authoritative_hint: int | None = None,
                legacy_issues: Collection[int] = (), lease_seconds: float = 300.0) -> EnsureResult:
    """Resolve one logical task to exactly one authoritative GitHub issue.

    `authoritative_hint` is the explicit roadmap-designated issue (e.g. #11 for the M09-P0
    audit); it is adopted even if it predates the fingerprint marker. `legacy_issues` are
    known historical duplicates without a marker and require a hint. `trusted_authors` is a
    required decision: pass the set of accounts allowed to own task issues so a stranger cannot
    hijack or block a task by copying the marker, or pass None to trust every author. The hint
    is an operator decision, but it must still be a confirmed issue (not a PR) by a trusted author.
    Matches whose issue-vs-PR status the gateway did not report BLOCK (`UNKNOWN_ISSUE_KIND`,
    re-validated on every run); they are neither adopted nor bypassed by creating.
    The first claim pins the hint and `legacy_issues` in the registry row (same transaction), and
    every later run of an unfinished task uses the pinned hint even if the caller omits it; a
    different explicit hint BLOCKS as HINT_CONFLICT until an operator calls `registry.replace_hint`.
    An explicit hint that does not resolve to an existing issue BLOCKS the task; it never
    falls through to creation. Without a hint, several matches are ambiguous and BLOCK too.

    Scope: the claim lives in `registry`, so every worker that may create this task must
    share one registry. Across registries only the GitHub-side checks protect.
    """
    fp, key = request.fingerprint, request.key
    existing = registry.get(fp)
    if existing is not None and existing.state is not MappingState.MAPPED and existing.hint_issue is not None \
            and authoritative_hint is None:
        # An earlier run pinned a hint and may already have acted on it: a run that forgot to pass it
        # must not carry on without it (that could create a second issue next to the legacy one).
        authoritative_hint = existing.hint_issue
        legacy_issues = tuple(existing.hint_legacy) + tuple(legacy_issues)
    known = LEGACY_AUTHORITIES.get(key)
    if known is not None and _norm_repo(known.repository) != _norm_repo(gateway.repository):
        known = None                                  # numbers of another repository mean nothing here
    if known is not None and authoritative_hint in (None, known.authoritative):
        authoritative_hint = known.authoritative
        legacy_issues = tuple(known.duplicates) + tuple(legacy_issues)
    if legacy_issues and authoritative_hint is None:
        raise ValueError('legacy_issues need an authoritative_hint')
    worst_create = getattr(gateway, 'max_create_seconds', None)
    if not isinstance(worst_create, (int, float)) or worst_create <= 0:
        raise ValueError('gateway must declare max_create_seconds > 0 and enforce it as the create timeout')
    if lease_seconds < MIN_LEASE_FACTOR * worst_create:
        raise ValueError(f'lease_seconds={lease_seconds} is shorter than {MIN_LEASE_FACTOR}x the gateway create time '
                         f'({worst_create}s): a slow create could outlive its claim')

    if existing and existing.state is MappingState.BLOCKED:
        if existing.github_issue_number is None and existing.github_repository \
                and _norm_repo(existing.github_repository) != _norm_repo(gateway.repository):
            # A create was attempted in another repository: its issue numbers mean something else here. Touch nothing.
            registry.record_incident(fp, 'REPOSITORY_MISMATCH',
                                     f'create attempted in {existing.github_repository}, called for {gateway.repository}')
            return EnsureResult(EnsureOutcome.BLOCKED, existing, False, None, 'REPOSITORY_MISMATCH')
        if existing.github_issue_number is None and (
                existing.block_reason in ('UNKNOWN_ISSUE_KIND', 'CREATE_UNCERTAIN')   # look again; the create record stays
                or (existing.block_reason == 'HINT_UNKNOWN_KIND'       # only the same hint may re-validate it,
                    and authoritative_hint in existing.block_candidates)):   # else a hint-less run would create anew
            if not registry.unblock(fp, f'{existing.block_reason}: re-validating',
                                    expect=(existing.block_reason, existing.block_candidates)):
                return _changed_meanwhile(registry, fp)
            existing = None
        elif existing.github_issue_number is None and existing.block_reason == 'POST_CREATE_CHECK_FAILED' \
                and existing.block_candidates and existing.github_repository is None:
            # Written by a release that did not record the repository: the candidate number may belong to another one.
            registry.record_incident(fp, 'REPOSITORY_UNKNOWN', f'created #{existing.block_candidates[0]} in an unknown '
                                     f'repository, called for {gateway.repository}; operator: unblock with hint=<issue>')
            return EnsureResult(EnsureOutcome.BLOCKED, existing, False, None, 'REPOSITORY_UNKNOWN')
        elif existing.github_issue_number is None and existing.block_reason == 'POST_CREATE_CHECK_FAILED' \
                and existing.block_candidates:
            # Our own create succeeded but the duplicate check did not. Nothing changes in the row until a re-check has
            # succeeded, so a second failure loses no context. Then the created issue alone is adopted by number.
            verdict = _recheck_created_issue(registry, gateway, request, existing, trusted_authors)
            if isinstance(verdict, EnsureResult):
                return verdict
            if not registry.unblock(fp, f'POST_CREATE_CHECK_FAILED: #{verdict} is the only marker issue', hint=verdict,
                                    expect=('POST_CREATE_CHECK_FAILED', existing.block_candidates)):
                return _changed_meanwhile(registry, fp)
            authoritative_hint = verdict
            existing = None
        elif existing.github_issue_number is None and _hint_resolves_block(existing, authoritative_hint):
            if not registry.unblock(fp, f'authoritative hint #{authoritative_hint} supplied', hint=authoritative_hint,
                                    legacy=legacy_issues, expect=(existing.block_reason, existing.block_candidates)):
                return _changed_meanwhile(registry, fp)
            existing = None
        else:
            return EnsureResult(EnsureOutcome.BLOCKED, existing, False, existing.github_issue_number, existing.block_reason)
    if existing and existing.state is MappingState.MAPPED:
        if authoritative_hint not in (None, existing.github_issue_number):
            registry.record_incident(fp, 'HINT_IGNORED_MAPPED',
                                     f'task is mapped to #{existing.github_issue_number}, hint #{authoritative_hint} ignored')
        return _sync(registry, existing, request, gateway, policy, retry)

    won, mapping = registry.claim(fp, key, claimant, lease_seconds, hint=authoritative_hint, legacy=legacy_issues)
    if mapping.state is MappingState.MAPPED:     # someone finished between our read and claim
        return _sync(registry, mapping, request, gateway, policy, retry)
    if mapping.state is MappingState.BLOCKED:
        return EnsureResult(EnsureOutcome.BLOCKED, mapping, False, mapping.github_issue_number, mapping.block_reason)
    if not won:
        return EnsureResult(EnsureOutcome.PENDING, mapping, False, None, f'claim held by {mapping.claimant}')
    token = mapping.claim_token
    if mapping.create_intent and mapping.github_repository \
            and _norm_repo(mapping.github_repository) != _norm_repo(gateway.repository):
        # The create that may have happened went to another repository: adopting or creating here could split the task.
        registry.release(fp, token)                  # the create record stays
        registry.record_incident(fp, 'REPOSITORY_MISMATCH',
                                 f'create attempted in {mapping.github_repository}, called for {gateway.repository}')
        return EnsureResult(EnsureOutcome.BLOCKED, registry.get(fp), False, None, 'REPOSITORY_MISMATCH')
    if mapping.hint_issue is not None and authoritative_hint in (None, mapping.hint_issue):
        # The row we won is the truth, not what we read before the claim: another run may have pinned a hint
        # (or more legacy numbers) in between, e.g. it claimed, failed and released just before we took over.
        authoritative_hint = mapping.hint_issue
        legacy_issues = tuple(mapping.hint_legacy) + tuple(legacy_issues)
    if authoritative_hint is not None and mapping.hint_issue != authoritative_hint:
        blocked = registry.block(fp, 'HINT_CONFLICT', f'pinned hint #{mapping.hint_issue}, this run passed #{authoritative_hint}',
                                 token=token, candidates=[mapping.hint_issue, authoritative_hint])
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)

    try:
        matches = _matches(gateway, fp, key, trusted_authors)
        hinted = gateway.get_issue(authoritative_hint) if authoritative_hint is not None else None
    except UnknownIssueKind as exc:
        return _blocked_unknown(registry, fp, token, exc, created=False)
    except Exception:
        registry.release(fp, token)              # nothing was created yet: safe to give the claim up
        raise

    if authoritative_hint is not None and hinted is None:
        blocked = registry.block(fp, 'HINT_NOT_FOUND', f'hint={authoritative_hint} does not exist', token=token,
                                 candidates=[authoritative_hint])
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)
    if hinted is not None and hinted.is_pull_request is None:
        blocked = registry.block(fp, 'HINT_UNKNOWN_KIND', f'hint={hinted.number}: gateway did not say issue or PR',
                                 token=token, candidates=[hinted.number])
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)
    if hinted is not None and (hinted.is_pull_request or not _trusted(hinted, trusted_authors)):
        why = 'is a pull request' if hinted.is_pull_request else f'is authored by untrusted {hinted.author!r}'
        blocked = registry.block(fp, 'HINT_INVALID', f'hint={hinted.number} {why}', token=token,
                                 candidates=[hinted.number])
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)
    candidates = {m.number: m for m in matches}
    if hinted is not None:
        candidates[hinted.number] = hinted
        dups = sorted((set(candidates) | set(legacy_issues)) - {hinted.number})
        return _adopt(registry, gateway, fp, token, hinted, dups, request)
    if len(candidates) == 1:
        return _adopt(registry, gateway, fp, token, next(iter(candidates.values())), [], request)
    if len(candidates) > 1:
        numbers = sorted(candidates)
        blocked = registry.block(fp, 'AMBIGUOUS_DUPLICATES', f'matches={numbers}, no authoritative hint', token=token,
                                 candidates=numbers)
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)

    if mapping.create_intent:
        # An earlier claim of this task may already have created the issue (it crashed or outlived its lease before it
        # could record the result) and the listing may not show it yet: never create blindly after that. The block is
        # re-validated on every run and adopts the issue once it is visible; otherwise an operator checks GitHub and
        # calls registry.confirm_not_created.
        blocked = registry.block(fp, 'CREATE_UNCERTAIN', 'an earlier create may have reached GitHub; no marker issue visible',
                                 token=token)
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, 'CREATE_UNCERTAIN')
    # Nothing exists. Only the registry that the repository designates may create (#68, decision gate path A); the check
    # comes before the create intent is recorded, so a refusal leaves nothing behind that could block a later creator.
    try:
        _authorize_create(gateway, registry, trusted_authors)
    except CreateNotAuthorized as exc:
        return _create_refused(registry, fp, token, exc)
    except Exception:
        registry.release(fp, token)              # authority unreadable: nothing was created, try again on the next run
        raise
    # Re-assert the claim and record the create intent right before the irreversible create.
    if not registry.begin_create(fp, token, gateway.repository):
        return EnsureResult(EnsureOutcome.PENDING, registry.get(fp), False, None, 'claim lost before create')
    # The repository-wide create claim (#68): the row above fences only this registry file, and no check of the designation
    # can cover the moment of the request (a process may stand still between the two). The claim is something the
    # repository hands out once per task (a label); every create happens under it and it is dropped only after the created
    # issue is recorded, so a second creator either does not get it or, holding it, sees the issue in the lookup below.
    try:
        held = _claim_create(gateway, registry, fp, token)
    except CreateNotAuthorized as exc:
        return _create_refused(registry, fp, token, exc, not_sent=True)
    except Exception:
        registry.release(fp, token, create_not_sent=True)      # nothing was sent to the issues endpoint
        raise
    if held is not None:
        registry.release(fp, token, create_not_sent=True)
        _incident_once(registry, fp, 'GLOBAL_CLAIM_HELD', held)
        return EnsureResult(EnsureOutcome.PENDING, registry.get(fp), False, None, 'GLOBAL_CLAIM_HELD')
    looked = _now()                              # the create rests on this lookup and on the authority answer after it
    try:
        matches = _matches(gateway, fp, key, trusted_authors)
    except UnknownIssueKind as exc:
        _release_create_claim(gateway, registry, fp)
        return _blocked_unknown(registry, fp, token, exc, created=False)
    except Exception:
        _release_create_claim(gateway, registry, fp)
        registry.release(fp, token, create_not_sent=True)
        raise
    if matches:                                  # created under an earlier claim and visible now that we hold it
        try:
            if len(matches) == 1:
                return _adopt(registry, gateway, fp, token, matches[0], [], request)
            numbers = sorted(m.number for m in matches)
            blocked = registry.block(fp, 'AMBIGUOUS_DUPLICATES', f'matches={numbers}, no authoritative hint', token=token,
                                     candidates=numbers)
            return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)
        finally:
            _release_create_claim(gateway, registry, fp)
    # The designation is asked again right before the request, and lookup and answer must be fresh: a creator whose
    # designation was withdrawn after its first check, or that stood still longer than the bound, does not create.
    try:
        _authorize_create(gateway, registry, trusted_authors)
        age = _age(looked)
        if age > CREATE_FRESHNESS_SECONDS:
            raise CreateNotAuthorized(f'the lookup and the authority answer are {age:.0f}s old, '
                                      f'the create bound is {CREATE_FRESHNESS_SECONDS:g}s')
    except CreateNotAuthorized as exc:
        _release_create_claim(gateway, registry, fp)
        return _create_refused(registry, fp, token, exc, not_sent=True)
    except Exception:
        _release_create_claim(gateway, registry, fp)
        registry.release(fp, token, create_not_sent=True)
        raise
    started = time.monotonic()
    try:
        issue = gateway.create_issue(request, fp, timeout=worst_create)
    except CreateNotSent as exc:
        # Trust but verify: a gateway that raised this wrongly must not enable an instant second create.
        try:
            visible = _matches(gateway, fp, key, trusted_authors)
        except UnknownIssueKind as unknown:
            return _blocked_unknown(registry, fp, token, unknown, created=False)   # intent and claim stay (re-validated)
        except Exception:
            raise exc                                # cannot verify: keep the claim (and the create claim) until its lease expires
        if visible:
            result = _reconcile_after_failed_create(registry, gateway, fp, key, token, trusted_authors, exc)
            _release_create_claim(gateway, registry, fp)
            return result
        registry.release(fp, token, create_not_sent=True)
        _release_create_claim(gateway, registry, fp)
        raise
    except Exception as exc:
        # Raises while the outcome stays uncertain: then the claim and the create claim stay, nobody creates behind them.
        result = _reconcile_after_failed_create(registry, gateway, fp, key, token, trusted_authors, exc)
        _release_create_claim(gateway, registry, fp)
        return result
    result = _record_create(registry, gateway, fp, key, token, trusted_authors, issue, time.monotonic() - started, worst_create)
    _release_create_claim(gateway, registry, fp)
    return result


def _record_create(registry, gateway, fp, key, token, trusted_authors, issue, elapsed, worst_create) -> EnsureResult:
    """The issue exists: check for duplicates and map it. Every verdict here records the created number."""
    if elapsed > worst_create:
        registry.record_incident(fp, 'SLOW_CREATE', f'create took {elapsed:.1f}s, declared bound {worst_create}s')
    try:
        after = {m.number for m in _matches(gateway, fp, key, trusted_authors)} | {issue.number}
    except UnknownIssueKind as unknown:
        return _blocked_unknown(registry, fp, token, unknown, created=True, issue_number=issue.number)
    except Exception as exc:    # the issue exists but a duplicate cannot be ruled out: block with it as the candidate, never map blindly
        registry.record_incident(fp, 'POST_CREATE_CHECK_FAILED',
                                 f'created #{issue.number}; the duplicate check failed ({type(exc).__name__}: {exc})')
        blocked = registry.block(fp, 'POST_CREATE_CHECK_FAILED', f'created #{issue.number}, duplicates not checked', token=token,
                                 candidates=[issue.number])
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, True, issue.number, 'POST_CREATE_CHECK_FAILED')
    if len(after) > 1:
        blocked = registry.block(fp, 'DUPLICATE_AFTER_CREATE', f'matches={sorted(after)}', token=token,
                                 candidates=sorted(after))
        if blocked.state is MappingState.MAPPED:      # a newer owner already mapped: keep its state, record ours
            blocked = registry.add_duplicates(fp, after - {blocked.github_issue_number})
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, True, issue.number, 'DUPLICATE_AFTER_CREATE')
    mapped = registry.map_issue(fp, token, gateway.repository, issue.number)
    if mapped is None:
        # Claim lost while creating: our issue is a duplicate of whatever the new owner does.
        # Record it without overwriting the owner's state, and tell the caller honestly.
        current = registry.block(fp, 'CLAIM_LOST_AFTER_CREATE', f'created #{issue.number} after the claim was taken over',
                                 token=token)
        if current.state is MappingState.MAPPED:
            current = registry.add_duplicates(fp, [issue.number])
        return EnsureResult(EnsureOutcome.BLOCKED, current, True, issue.number, 'CLAIM_LOST_AFTER_CREATE')
    return EnsureResult(EnsureOutcome.CREATED, mapped, True, issue.number)


def _create_refused(registry, fp, token, exc, *, not_sent=False) -> EnsureResult:
    """The designation (or its freshness) refused the create: give the claim up, say it once."""
    registry.release(fp, token, create_not_sent=not_sent)
    _incident_once(registry, fp, 'CREATE_NOT_AUTHORIZED', str(exc))
    return EnsureResult(EnsureOutcome.BLOCKED, registry.get(fp), False, None, 'CREATE_NOT_AUTHORIZED')


def _incident_once(registry, fp, reason, detail) -> None:
    """Record the incident unless it repeats the last one: a scheduler that retries says it once."""
    last = registry.incidents(fp)[-1:]
    if not last or (last[0]['reason'], last[0]['detail']) != (reason, detail):
        registry.record_incident(fp, reason, detail)


def _now():
    return time.monotonic(), time.time()


def _age(since) -> float:
    """Seconds since `since` by whichever clock moved further: a paused process (monotonic) or a corrected wall clock
    cannot hide time on both of them at once."""
    mono, wall = _now()
    return max(mono - since[0], wall - since[1])


def _hostname() -> str:
    try:
        return (socket.gethostname() or 'unknown').split()[0]
    except OSError:
        return 'unknown'


def _claim_holder(registry, token) -> str:
    """Who holds the create claim (no secret in it): registry id, claim token, host, time. Fits 100 characters."""
    text = f'registry={registry.registry_id} token={token} host={_hostname()[:HOLDER_HOST_CHARS]}'
    stamp = time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())
    return text if len(f'{text} at={stamp}') > 100 else f'{text} at={stamp}'


def _claim_fields(text) -> dict:
    return dict(part.split('=', 1) for part in (text or '').split() if '=' in part)


def _claim_create(gateway, registry, fp, token):
    """Take the repository-wide create claim (#68). None when it is ours, otherwise the text naming who holds it.

    A claim of this registry on this host under a lower (older) token is replaced: this run won the local claim of a row
    without a create intent, which only `release(create_not_sent=True)` (the run that held it ended without a request) or
    an operator's `confirm_not_created` leaves behind; so that holder is gone and only its release was lost. Any other
    holder keeps it (another registry, another host, a token that is not lower: a registry file restored from a backup),
    and a claim whose holder died is removed by an operator who knows that holder stopped (see the docs)."""
    claim = getattr(gateway, 'claim_create', None)
    if claim is None or getattr(gateway, 'release_create_claim', None) is None:
        raise CreateNotAuthorized('the gateway has no claim_create, so it cannot take the repository-wide create claim')
    holder = _claim_holder(registry, token)
    held = claim(fp, holder)
    if held is None or held == holder:
        return None
    fields = _claim_fields(held)
    if fields.get('registry') != registry.registry_id or fields.get('host') != _claim_fields(holder)['host'] \
            or not fields.get('token', '').isdigit() or int(fields['token']) >= int(token):
        return held
    gateway.release_create_claim(fp)
    registry.record_incident(fp, 'STALE_CLAIM_REPLACED', held)
    held = claim(fp, holder)
    return None if held in (None, holder) else held


def _release_create_claim(gateway, registry, fp) -> None:
    """Drop the create claim once the outcome of the create is recorded; a failure is an incident, never a blocker."""
    try:
        gateway.release_create_claim(fp)
    except Exception as exc:
        registry.record_incident(fp, 'CLAIM_RELEASE_FAILED', f'{type(exc).__name__}: {exc}')


def _authorize_create(gateway, registry, trusted_authors) -> None:
    """Raise `CreateNotAuthorized` unless the repository designates this registry as the one that may create.

    A gateway without `authorize_create` cannot prove it: that refuses, so a gateway written without the rule never creates."""
    authorize = getattr(gateway, 'authorize_create', None)
    if authorize is None:
        raise CreateNotAuthorized('the gateway has no authorize_create, so it cannot prove that this registry may create')
    authorize(registry.registry_id, trusted_authors)


def _recheck_created_issue(registry, gateway, request, row, trusted_authors):
    """Re-check a task that was blocked as POST_CREATE_CHECK_FAILED: the issue number to adopt, or a BLOCKED result.

    The row is only changed to say something new (`EXPECTED_ISSUE_INVALID`, `DUPLICATE_AFTER_CREATE`); a failing re-check
    leaves it untouched, and nothing here ever creates an issue."""
    fp, key, cand = request.fingerprint, request.key, row.block_candidates[0]

    def blocked(reason, detail, numbers):
        mapping = registry.block(fp, reason, detail, candidates=numbers, expect=('POST_CREATE_CHECK_FAILED', row.block_candidates))
        if (mapping.block_reason, mapping.block_candidates) != (reason, tuple(sorted(set(numbers)))):
            return _changed_meanwhile(registry, fp)      # another worker's newer verdict stands
        return EnsureResult(EnsureOutcome.BLOCKED, mapping, False, cand, reason)
    try:
        expected = gateway.get_issue(cand)
        matches = _matches(gateway, fp, key, trusted_authors)
        marked = getattr(gateway, 'carries_marker', None)
        marked = True if expected is None else (marked is not None and marked(cand, fp))     # no way to check: fail closed
    except Exception as exc:
        return EnsureResult(EnsureOutcome.BLOCKED, row, False, cand,
                            f'POST_CREATE_CHECK_FAILED: the re-check failed again ({type(exc).__name__}), nothing was changed')
    if expected is None:
        return blocked('EXPECTED_ISSUE_INVALID', f'created #{cand} does not exist any more', [cand])
    if expected.is_pull_request is not False or not _trusted(expected, trusted_authors):
        return blocked('EXPECTED_ISSUE_INVALID', f'created #{cand} is a pull request, of unknown kind or by an untrusted author', [cand])
    if not marked:
        return blocked('EXPECTED_ISSUE_INVALID', f'created #{cand} no longer carries the task marker', [cand])
    others = {m.number for m in matches} - {cand}
    if others:
        numbers = sorted(others | {cand})
        return blocked('DUPLICATE_AFTER_CREATE', f'matches={numbers} (found when re-checking created #{cand})', numbers)
    return cand


def _changed_meanwhile(registry, fp) -> EnsureResult:
    """Another worker changed the blocked task between our read and our release: its newer verdict stands."""
    current = registry.get(fp)
    if current.state is MappingState.BLOCKED:
        return EnsureResult(EnsureOutcome.BLOCKED, current, False, current.github_issue_number, current.block_reason)
    return EnsureResult(EnsureOutcome.PENDING, current, False, current.github_issue_number, 'task changed meanwhile, run again')


def _reconcile_after_failed_create(registry, gateway, fp, key, token, trusted_authors, exc) -> EnsureResult:
    """The create call failed, but GitHub may have created the issue anyway. Look before anyone retries."""
    registry.record_incident(fp, 'CREATE_UNCERTAIN', f'{type(exc).__name__}: {exc}')
    try:
        found = _matches(gateway, fp, key, trusted_authors)
    except UnknownIssueKind as unknown:
        return _blocked_unknown(registry, fp, token, unknown, created=True)
    except Exception:
        raise exc                                    # cannot look: keep the claim, never release after a create attempt
    if len(found) == 1:
        mapped = registry.map_issue(fp, token, gateway.repository, found[0].number)
        if mapped is not None:
            return EnsureResult(EnsureOutcome.CREATED, mapped, True, found[0].number, 'adopted after failed create call')
        current = registry.block(fp, 'CLAIM_LOST_AFTER_CREATE', f'created #{found[0].number} after the claim was taken over',
                                 token=token)
        if current.state is MappingState.MAPPED and current.github_issue_number != found[0].number:
            current = registry.add_duplicates(fp, [found[0].number])
        return EnsureResult(EnsureOutcome.BLOCKED, current, True, found[0].number, 'CLAIM_LOST_AFTER_CREATE')
    if len(found) > 1:
        numbers = sorted(m.number for m in found)
        blocked = registry.block(fp, 'DUPLICATE_AFTER_CREATE', f'matches={numbers}', token=token, candidates=numbers)
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, True, None, 'DUPLICATE_AFTER_CREATE')
    raise exc                                        # nothing visible yet: claim stays held until its lease expires


def _hint_resolves_block(existing, hint) -> bool:
    """A hint lifts a block only if it addresses it, so an always-passed hint cannot silently wave away
    every incident: it must be one of the recorded candidates, or differ from a rejected hint."""
    if hint is None or existing.block_reason not in _UNBLOCKABLE_BY_HINT:
        return False
    if existing.block_reason in ('HINT_NOT_FOUND', 'HINT_INVALID'):
        return hint not in existing.block_candidates
    return hint in existing.block_candidates


def _matches(gateway, fp, key, trusted_authors) -> list[IssueRef]:
    # Pull requests come out of the issues API too; a PR that carries the marker is never a task issue.
    seen = [m for m in gateway.find_issues(fp, key) if _trusted(m, trusted_authors)]
    unknown = [m.number for m in seen if m.is_pull_request is None]
    if unknown:
        raise UnknownIssueKind(unknown)              # never adopt, never create around it: block and look again next run
    return [m for m in seen if m.is_pull_request is False]


def _blocked_unknown(registry, fp, token, exc, *, created, issue_number=None) -> EnsureResult:
    blocked = registry.block(fp, 'UNKNOWN_ISSUE_KIND', str(exc), token=token, candidates=exc.numbers)
    return EnsureResult(EnsureOutcome.BLOCKED, blocked, created, issue_number, 'UNKNOWN_ISSUE_KIND')


def _trusted(issue, trusted_authors) -> bool:
    return trusted_authors is None or issue.author.strip().lower() in {a.strip().lower() for a in trusted_authors}


_norm_repo = normalize_repository


def _adopt(registry, gateway, fp, token, issue, duplicates, request) -> EnsureResult:
    # Side effects first (all idempotent, comment/label only), mapping last: if we die midway the
    # claim is still open and the next run repeats the remaining steps instead of skipping them.
    for number in duplicates:
        if not gateway.is_documented_duplicate(number, issue.number):
            gateway.mark_duplicate(number, issue.number)
    gateway.update_issue(issue.number, request, 'mapping recovered; marker written')
    mapped = registry.map_issue(fp, token, gateway.repository, issue.number, duplicates)
    if mapped is None:
        return EnsureResult(EnsureOutcome.PENDING, registry.get(fp), False, None, 'claim lost while adopting')
    return EnsureResult(EnsureOutcome.RECOVERED, mapped, False, issue.number)


def _sync(registry, mapping: Mapping, request, gateway, policy, retry) -> EnsureResult:
    number = mapping.github_issue_number
    if _norm_repo(mapping.github_repository or '') != _norm_repo(gateway.repository):
        # Same registry, different repository: issue numbers mean something else there. Touch nothing.
        registry.record_incident(mapping.fingerprint, 'REPOSITORY_MISMATCH',
                                 f'mapped in {mapping.github_repository}, called for {gateway.repository}')
        return EnsureResult(EnsureOutcome.BLOCKED, mapping, False, number, 'REPOSITORY_MISMATCH')
    current = gateway.get_issue(number)
    if current is not None and current.state == 'closed':
        if policy is ReopenPolicy.EXPLICIT and retry:
            gateway.reopen_issue(number, request, 'explicit retry')
            return EnsureResult(EnsureOutcome.REOPENED, mapping, False, number)
        gateway.update_issue(number, request, 'task requested again; issue is closed and policy forbids reopening')
        return EnsureResult(EnsureOutcome.UPDATED, mapping, False, number, 'closed, not reopened')
    gateway.update_issue(number, request, 'task requested again; existing issue updated')
    return EnsureResult(EnsureOutcome.UPDATED, mapping, False, number)
