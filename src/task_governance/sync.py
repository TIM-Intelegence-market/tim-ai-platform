"""Update-first synchronisation: existing task -> update, otherwise create exactly once."""
from dataclasses import dataclass
from enum import Enum
from typing import Collection, Protocol

from .identity import TaskRequest
from .registry import Mapping, MappingState, TaskRegistry


@dataclass(frozen=True)
class IssueRef:
    number: int
    state: str          # 'open' | 'closed'
    title: str = ''
    author: str = ''


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

    def find_issues(self, fingerprint: str, canonical_key: str) -> list[IssueRef]: ...
    def get_issue(self, number: int) -> IssueRef | None: ...
    def create_issue(self, request: TaskRequest, fingerprint: str) -> IssueRef: ...
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
                authoritative_hint: int | None = None, legacy_issues: Collection[int] = (),
                trusted_authors: Collection[str] | None = None, lease_seconds: float = 300.0) -> EnsureResult:
    """Resolve one logical task to exactly one authoritative GitHub issue.

    `authoritative_hint` is the explicit roadmap-designated issue (e.g. #11 for the M09-P0
    audit); it is adopted even if it predates the fingerprint marker. `legacy_issues` are
    known historical duplicates without a marker. `trusted_authors` restricts which marker
    matches count, so a stranger cannot hijack or block a task by copying the marker.
    Without a valid hint, several matches are ambiguous and the task is BLOCKED.

    Scope: the claim lives in `registry`, so every worker that may create this task must
    share one registry. Across registries only the GitHub-side checks protect.
    """
    fp, key = request.fingerprint, request.key

    existing = registry.get(fp)
    if existing and existing.state is MappingState.BLOCKED:
        if existing.github_issue_number is None and existing.block_reason == 'AMBIGUOUS_DUPLICATES' \
                and authoritative_hint is not None:
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

    candidates = {m.number: m for m in matches}
    if hinted is not None:
        candidates[hinted.number] = hinted
    if hinted is not None or len(candidates) == 1:
        chosen = hinted or next(iter(candidates.values()))
        dups = sorted((set(candidates) | set(legacy_issues)) - {chosen.number}) if hinted else []
        return _adopt(registry, gateway, fp, token, chosen, dups, request)
    if len(candidates) > 1:
        numbers = sorted(candidates)
        blocked = registry.block(fp, 'AMBIGUOUS_DUPLICATES', f'matches={numbers}, no authoritative hint')
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)

    # Nothing exists. Re-assert the claim right before the irreversible create.
    if not registry.renew(fp, token):
        return EnsureResult(EnsureOutcome.PENDING, registry.get(fp), False, None, 'claim lost before create')
    issue = gateway.create_issue(request, fp)
    after = {m.number for m in _matches(gateway, fp, key, trusted_authors)} | {issue.number}
    if len(after) > 1:
        blocked = registry.block(fp, 'DUPLICATE_AFTER_CREATE', f'matches={sorted(after)}')
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, True, issue.number, blocked.block_reason)
    mapped = registry.map_issue(fp, token, gateway.repository, issue.number)
    if mapped is None:
        blocked = registry.block(fp, 'CLAIM_LOST_AFTER_CREATE', f'created #{issue.number} after the claim was taken over')
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, True, issue.number, blocked.block_reason)
    return EnsureResult(EnsureOutcome.CREATED, mapped, True, issue.number)


def _matches(gateway, fp, key, trusted_authors) -> list[IssueRef]:
    found = gateway.find_issues(fp, key)
    if trusted_authors is None:
        return found
    return [m for m in found if m.author in trusted_authors]


def _adopt(registry, gateway, fp, token, issue, duplicates, request) -> EnsureResult:
    mapped = registry.map_issue(fp, token, gateway.repository, issue.number, duplicates)
    if mapped is None:
        return EnsureResult(EnsureOutcome.PENDING, registry.get(fp), False, None, 'claim lost while adopting')
    for number in duplicates:
        if not gateway.is_documented_duplicate(number, issue.number):
            gateway.mark_duplicate(number, issue.number)
    gateway.update_issue(issue.number, request, 'mapping recovered; marker written')
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
