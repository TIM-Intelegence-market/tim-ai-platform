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
    is an operator decision, but it must still be a confirmed issue (not a PR) by a trusted author.
    Matches whose issue-vs-PR status the gateway did not report BLOCK (`UNKNOWN_ISSUE_KIND`,
    re-validated on every run); they are neither adopted nor bypassed by creating.
    An explicit hint that does not resolve to an existing issue BLOCKS the task; it never
    falls through to creation. Without a hint, several matches are ambiguous and BLOCK too.

    Scope: the claim lives in `registry`, so every worker that may create this task must
    share one registry. Across registries only the GitHub-side checks protect.
    """
    fp, key = request.fingerprint, request.key
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

    existing = registry.get(fp)
    if existing and existing.state is MappingState.BLOCKED:
        if existing.github_issue_number is None and (
                existing.block_reason == 'UNKNOWN_ISSUE_KIND'          # the marker exists, so no hint is needed
                or (existing.block_reason == 'HINT_UNKNOWN_KIND'       # only the same hint may re-validate it,
                    and authoritative_hint in existing.block_candidates)):   # else a hint-less run would create anew
            registry.unblock(fp, f'{existing.block_reason}: re-validating')
            existing = None
        elif existing.github_issue_number is None and _hint_resolves_block(existing, authoritative_hint):
            registry.unblock(fp, f'authoritative hint #{authoritative_hint} supplied')
            existing = None
        else:
            return EnsureResult(EnsureOutcome.BLOCKED, existing, False, existing.github_issue_number, existing.block_reason)
    if existing and existing.state is MappingState.MAPPED:
        return _sync(registry, existing, request, gateway, policy, retry)

    won, mapping = registry.claim(fp, key, claimant, lease_seconds)
    if mapping.state is MappingState.MAPPED:     # someone finished between our read and claim
        return _sync(registry, mapping, request, gateway, policy, retry)
    if mapping.state is MappingState.BLOCKED:
        return EnsureResult(EnsureOutcome.BLOCKED, mapping, False, mapping.github_issue_number, mapping.block_reason)
    if not won:
        return EnsureResult(EnsureOutcome.PENDING, mapping, False, None, f'claim held by {mapping.claimant}')
    token = mapping.claim_token

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

    # Nothing exists. Re-assert the claim right before the irreversible create.
    if not registry.renew(fp, token):
        return EnsureResult(EnsureOutcome.PENDING, registry.get(fp), False, None, 'claim lost before create')
    started = time.monotonic()
    try:
        issue = gateway.create_issue(request, fp, timeout=worst_create)
    except CreateNotSent as exc:
        # Trust but verify: a gateway that raised this wrongly must not enable an instant second create.
        try:
            visible = _matches(gateway, fp, key, trusted_authors)
        except UnknownIssueKind as unknown:
            return _blocked_unknown(registry, fp, token, unknown, created=False)
        except Exception:
            raise exc                                # cannot verify: keep the claim until its lease expires
        if visible:
            return _reconcile_after_failed_create(registry, gateway, fp, key, token, trusted_authors, exc)
        registry.release(fp, token)
        raise
    except Exception as exc:
        return _reconcile_after_failed_create(registry, gateway, fp, key, token, trusted_authors, exc)
    elapsed = time.monotonic() - started
    if elapsed > worst_create:
        registry.record_incident(fp, 'SLOW_CREATE', f'create took {elapsed:.1f}s, declared bound {worst_create}s')
    try:
        after = {m.number for m in _matches(gateway, fp, key, trusted_authors)} | {issue.number}
    except UnknownIssueKind as unknown:
        return _blocked_unknown(registry, fp, token, unknown, created=True, issue_number=issue.number)
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


def _norm_repo(repo) -> str:
    text = str(repo).strip().lower().rstrip('/')
    for prefix in ('https://github.com/', 'http://github.com/', 'github.com/', 'git@github.com:'):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.removesuffix('.git').rstrip('/')


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
