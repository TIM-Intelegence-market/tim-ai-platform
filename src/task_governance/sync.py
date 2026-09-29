"""Update-first synchronisation: existing task -> update, otherwise create exactly once."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .identity import TaskRequest
from .registry import Mapping, MappingState, TaskRegistry


@dataclass(frozen=True)
class IssueRef:
    number: int
    state: str          # 'open' | 'closed'
    title: str = ''


class IssueGateway(Protocol):
    """The only GitHub surface the guard may use. There is deliberately no close method."""
    repository: str

    def find_issues(self, fingerprint: str, canonical_key: str) -> list[IssueRef]: ...
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
    RECOVERED = 'RECOVERED'            # GitHub match adopted without local mapping, nothing created
    REOPENED = 'REOPENED'
    PENDING = 'PENDING'                # another live worker holds the claim, nothing created
    BLOCKED = 'BLOCKED'                # ambiguous/violated uniqueness, escalated, nothing created


@dataclass(frozen=True)
class EnsureResult:
    outcome: EnsureOutcome
    mapping: Mapping
    created: bool
    issue_number: int | None
    detail: str = ''


def ensure_task(request: TaskRequest, registry: TaskRegistry, gateway: IssueGateway, *, claimant: str,
                policy: ReopenPolicy = ReopenPolicy.NEVER, retry: bool = False,
                authoritative_hint: int | None = None, lease_seconds: float = 300.0) -> EnsureResult:
    """Resolve one logical task to exactly one authoritative GitHub issue.

    `authoritative_hint` is the explicit roadmap-designated issue (e.g. #11 for
    the M09-P0 audit). Without it, several GitHub matches are ambiguous and the
    task is BLOCKED rather than guessed.
    """
    fp, key = request.fingerprint, request.key

    existing = registry.get(fp)
    if existing and existing.state is MappingState.MAPPED:
        return _sync(existing, request, registry, gateway, policy, retry)
    if existing and existing.state is MappingState.BLOCKED:
        return EnsureResult(EnsureOutcome.BLOCKED, existing, False, existing.github_issue_number, existing.block_reason)

    won, mapping = registry.claim(fp, key, claimant, lease_seconds)
    if mapping.state is MappingState.MAPPED:     # someone finished between our read and claim
        return _sync(mapping, request, registry, gateway, policy, retry)
    if mapping.state is MappingState.BLOCKED:
        return EnsureResult(EnsureOutcome.BLOCKED, mapping, False, mapping.github_issue_number, mapping.block_reason)
    if not won:
        return EnsureResult(EnsureOutcome.PENDING, mapping, False, None, f'claim held by {mapping.claimant}')

    # We hold the claim. Uniqueness check BEFORE creation: GitHub is authoritative too.
    matches = gateway.find_issues(fp, key)
    if len(matches) == 1:
        return _adopt(registry, gateway, fp, matches[0], (), request, EnsureOutcome.RECOVERED)
    if len(matches) > 1:
        numbers = sorted(m.number for m in matches)
        if authoritative_hint in numbers:
            chosen = next(m for m in matches if m.number == authoritative_hint)
            dups = [n for n in numbers if n != chosen.number]
            _document_duplicates(gateway, chosen.number, dups)
            return _adopt(registry, gateway, fp, chosen, dups, request, EnsureOutcome.RECOVERED)
        blocked = registry.block(fp, 'AMBIGUOUS_DUPLICATES', f'matches={numbers}, no authoritative hint')
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, False, None, blocked.block_reason)

    issue = gateway.create_issue(request, fp)
    # Uniqueness check AFTER creation: a concurrent creator outside our claim shows up here.
    after = gateway.find_issues(fp, key)
    if len({m.number for m in after} | {issue.number}) > 1:
        numbers = sorted({m.number for m in after} | {issue.number})
        blocked = registry.block(fp, 'DUPLICATE_AFTER_CREATE', f'matches={numbers}')
        return EnsureResult(EnsureOutcome.BLOCKED, blocked, True, issue.number, blocked.block_reason)
    mapped = registry.map_issue(fp, gateway.repository, issue.number)
    return EnsureResult(EnsureOutcome.CREATED, mapped, True, issue.number)


def _adopt(registry, gateway, fp, issue, duplicates, request, outcome) -> EnsureResult:
    mapped = registry.map_issue(fp, gateway.repository, issue.number, duplicates)
    gateway.update_issue(issue.number, request, 'mapping recovered from GitHub')
    return EnsureResult(outcome, mapped, False, issue.number)


def _document_duplicates(gateway, authoritative: int, duplicates) -> None:
    for number in duplicates:
        if not gateway.is_documented_duplicate(number, authoritative):
            gateway.mark_duplicate(number, authoritative)


def _sync(mapping: Mapping, request, registry, gateway, policy, retry) -> EnsureResult:
    number = mapping.github_issue_number
    current = next((m for m in gateway.find_issues(mapping.fingerprint, mapping.canonical_key) if m.number == number), None)
    if current is not None and current.state == 'closed':
        if policy is ReopenPolicy.EXPLICIT and retry:
            gateway.reopen_issue(number, request, 'explicit retry')
            return EnsureResult(EnsureOutcome.REOPENED, mapping, False, number)
        gateway.update_issue(number, request, 'task requested again; issue is closed and policy forbids reopening')
        return EnsureResult(EnsureOutcome.UPDATED, mapping, False, number, 'closed, not reopened')
    gateway.update_issue(number, request, 'task requested again; existing issue updated')
    return EnsureResult(EnsureOutcome.UPDATED, mapping, False, number)
