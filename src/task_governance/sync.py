"""Update-first synchronisation: existing task -> update, otherwise create exactly once."""
from dataclasses import dataclass
from enum import Enum
from typing import Collection, Protocol

_UNBLOCKABLE_BY_HINT = ('AMBIGUOUS_DUPLICATES', 'DUPLICATE_AFTER_CREATE', 'HINT_NOT_FOUND', 'HINT_INVALID')
MIN_LEASE_FACTOR = 4      # lease must be at least this many times the gateway's worst-case create time

import time

from .identity import TaskRequest
from .legacy import LEGACY_AUTHORITIES
from .registry import Mapping, MappingState, TaskRegistry


@dataclass(frozen=True)
class IssueRef:
    number: int
    state: str          # 'open' | 'closed'
    title: str = ''
    author: str = ''
    is_pull_request: bool = False


class IssueGateway(Protocol):
    """The only GitHub surface the guard may use. It has no close operation, and
    `mark_duplicate`/`update_issue` must only comment or label, never change state.

    Contract for implementers:
    - `find_issues` lists issues carrying the fingerprint marker (not the lagging search index).
    - `update_issue` also writes the marker into the issue body, which back-fills issues that
      predate the marker (e.g. #11 and #22-#65).
    - `create_issue` embeds the marker in the body.
    """
    repository: str
    max_create_seconds: float   # REQUIRED: hard upper bound (enforced via `timeout`) of one create_issue call incl. retries

    def find_issues(self, fingerprint: str, canonical_key: str) -> list[IssueRef]: ...
    def get_issue(self, number: int) -> IssueRef | None: ...
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
    itself is an operator decision and is not author-filtered.
    An explicit hint that does not resolve to an existing issue BLOCKS the task; it never
    falls through to creation. Without a hint, several matches are ambiguous and BLOCK too.

    Scope: the claim lives in `registry`, so every worker that may create this task must
    share one registry. Across registries only the GitHub-side checks protect.
    """
    fp, key = request.fingerprint, request.key
    known = LEGACY_AUTHORITIES.get(key)
    if authoritative_hint is None and known is not None:
        authoritative_hint, legacy_issues = known.authoritative, tuple(known.duplicates) + tuple(legacy_issues)
    if legacy_issues and authoritative_hint is None:
        raise ValueError('legacy_issues need an authoritative_hint')
    worst_create = getattr(gateway, 'max_create_seconds', None)
    if not isinstance(worst_create, (int, float)) or worst_create <= 0:
        raise ValueError('gateway must declare max_create_seconds > 0 and enforce it as the create timeout')
    if lease_seconds < MIN_LEASE_FACTOR * worst_create:
        raise ValueError(f'lease_seconds={lease_seconds} is shorter than {MIN_LEASE_FACTOR}x the gateway create time '
                         f'({worst_create}s): a slow create could outlive its claim')

    existing = registry.get(fp)
    if existing and existing.state is MappingState.BLOCKED:
        if existing.github_issue_number is None and _hint_resolves_block(registry, fp, existing, authoritative_hint):
            registry.unblock(fp, f'authoritative hint #{authoritative_hint} supplied')
            existing = None
        else:
            return EnsureResult(EnsureOutcome.BLOCKED, existing, False, existing.github_issue_number, existing.block_reason)
    if existing and existing.state is MappingState.MAPPED:
        return _sync(existing, request, gateway, policy, retry)

    won, mapping = registry.claim(fp, key, claimant, lease_seconds)
    if mapping.state is MappingState.MAPPED:     # someone finished between our read and claim
        return _sync(mapping, request, gateway, policy, retry)
    if mapping.state is MappingState.BLOCKED:
        return EnsureResult(EnsureOutcome.BLOCKED, mapping, False, mapping.github_issue_number, mapping.block_reason)
    if not won:
        return EnsureResult(EnsureOutcome.PENDING, mapping, False, None, f'claim held by {mapping.claimant}')
    token = mapping.claim_token

    try:
        matches = _matches(gateway, fp, key, trusted_authors)
        hinted = gateway.get_issue(authoritative_hint) if authoritative_hint is not None else None
    except Exception:
        registry.release(fp, token)              # nothing was created yet: safe to give the claim up
        raise

    if authoritative_hint is not None and hinted is None:
        blocked = registry.block(fp, 'HINT_NOT_FOUND', f'hint={authoritative_hint} does not exist', token=token)
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)
    if hinted is not None and (hinted.is_pull_request or (trusted_authors is not None and hinted.author not in trusted_authors)):
        why = 'is a pull request' if hinted.is_pull_request else f'is authored by untrusted {hinted.author!r}'
        blocked = registry.block(fp, 'HINT_INVALID', f'hint={hinted.number} {why}', token=token)
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
        blocked = registry.block(fp, 'AMBIGUOUS_DUPLICATES', f'matches={numbers}, no authoritative hint', token=token)
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)

    # Nothing exists. Re-assert the claim right before the irreversible create.
    if not registry.renew(fp, token):
        return EnsureResult(EnsureOutcome.PENDING, registry.get(fp), False, None, 'claim lost before create')
    started = time.monotonic()
    issue = gateway.create_issue(request, fp, timeout=worst_create)
    elapsed = time.monotonic() - started
    if elapsed > worst_create:
        registry.record_incident(fp, 'SLOW_CREATE', f'create took {elapsed:.1f}s, declared bound {worst_create}s')
    after = {m.number for m in _matches(gateway, fp, key, trusted_authors)} | {issue.number}
    if len(after) > 1:
        blocked = registry.block(fp, 'DUPLICATE_AFTER_CREATE', f'matches={sorted(after)}', token=token)
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


def _hint_resolves_block(registry, fp, existing, hint) -> bool:
    """A hint lifts a block only if it actually addresses it, so an always-passed hint cannot silently
    wave away every incident: it must be one of the recorded candidates, or differ from a failed hint."""
    if hint is None or existing.block_reason not in _UNBLOCKABLE_BY_HINT:
        return False
    incident = registry.last_incident(fp, (existing.block_reason,))
    detail = incident['detail'] if incident else ''
    if existing.block_reason in ('HINT_NOT_FOUND', 'HINT_INVALID'):
        return f'hint={hint} ' not in detail + ' '
    return f'{hint}' in detail.replace('[', ' ').replace(']', ' ').replace(',', ' ').split()


def _matches(gateway, fp, key, trusted_authors) -> list[IssueRef]:
    found = gateway.find_issues(fp, key)
    if trusted_authors is None:
        return found
    return [m for m in found if m.author in trusted_authors]


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


def _sync(mapping: Mapping, request, gateway, policy, retry) -> EnsureResult:
    number = mapping.github_issue_number
    current = gateway.get_issue(number)
    if current is not None and current.state == 'closed':
        if policy is ReopenPolicy.EXPLICIT and retry:
            gateway.reopen_issue(number, request, 'explicit retry')
            return EnsureResult(EnsureOutcome.REOPENED, mapping, False, number)
        gateway.update_issue(number, request, 'task requested again; issue is closed and policy forbids reopening')
        return EnsureResult(EnsureOutcome.UPDATED, mapping, False, number, 'closed, not reopened')
    gateway.update_issue(number, request, 'task requested again; existing issue updated')
    return EnsureResult(EnsureOutcome.UPDATED, mapping, False, number)
