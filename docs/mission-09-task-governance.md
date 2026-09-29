# Mission 09 task governance (#68)

Guard that makes mission-task creation idempotent, update-first and duplicate-safe.
Code: `src/task_governance/`. Tests: `tests/task_governance/`.

## Identity

`canonical_task_key = MISSION|PHASE|TASK_TYPE|TARGET|schema_version`, for example
`M09|P0|BASELINE_ARCHITECTURE_AUDIT|TIM|v1`. The fingerprint is `sha256(key)`.
Titles and bodies are display text and never part of the identity. Empty parts or
parts containing `|` are rejected, not normalised.

## Flow (`ensure_task`)

1. Mapping for the fingerprint is MAPPED: update the issue (or apply the reopen policy). Nothing is created.
2. Mapping is BLOCKED: stay blocked, nothing is created.
3. Otherwise claim creation. The claim is a row in SQLite (`PRIMARY KEY fingerprint`, `UNIQUE canonical_key`), so threads and processes cannot both win it. Every claim carries a fencing token. A worker that loses returns `PENDING`. A claim is taken over only after its lease expired, never because the claimant name matches.
4. Uniqueness check before creating: search GitHub for the fingerprint marker (`<!-- TIM_TASK_FINGERPRINT:<sha> -->`).
   - `authoritative_hint` given and that issue exists: adopt it even if it predates the marker (#11 and #22–#65 do); `legacy_issues` (which require a hint) and other marker matches are recorded as duplicates
   - `authoritative_hint` given but the issue does not exist: `BLOCKED` (`HINT_NOT_FOUND`), never a fallthrough to create
   - one marker match: adopt it (`RECOVERED`), no create
   - several matches without hint: `BLOCKED` plus a governance incident; a later call with a valid hint unblocks it (also for `DUPLICATE_AFTER_CREATE` and `HINT_NOT_FOUND`)
   - none: renew the lease (fails if the claim was taken over, then nothing is created) and create exactly once
5. Uniqueness check after creating. A second match blocks the task and records an incident. Nothing is ever closed automatically.
6. Adopt path order: mark duplicates and write the marker first (all idempotent, comment/label only), persist the mapping last, so a crash midway repeats the remaining steps on the next run.
7. Persist the mapping with the fencing token (issue number, repository, duplicate list). If the claim was lost meanwhile, the result is `BLOCKED` (`CLAIM_LOST_AFTER_CREATE`), never reported as cleanly created. The stale worker only records an incident and adds its issue to the winner's duplicate list; it cannot overwrite the winner's state (fenced writes).

A failure before anything was created (for example GitHub unreachable) releases the claim.

## Policies

| Situation | Behaviour |
|---|---|
| Retry, restart, usage-limit resume | Same issue, updated |
| Closed authoritative issue | Never replaced. Reopened only with `ReopenPolicy.EXPLICIT` and `retry=True`, otherwise an audit comment |
| Historical duplicates | Kept as audit evidence, marked "duplicate of" once if not yet documented, never closed or deleted |
| Creator crashed after creating the issue | Nobody takes over before `lease_seconds` expired (a claimant name is not an identity); then the marker search finds the issue and adopts it |
| Local registry lost | Mapping recovered from the GitHub marker |

The gateway interface has no close operation on purpose. `trusted_authors` is a required argument: pass the accounts allowed to own task issues, so someone who copies the marker into another issue cannot hijack or block a task (`None` trusts everyone and is a conscious choice). The hint is an operator decision and is not author-filtered.

## Limits

- The create-once guarantee holds for all workers that share one registry file. Workers with separate registries (for example cloud sessions and a Mac LaunchAgent) are protected only by the GitHub-side checks, which are not atomic. Run task creation from one place or share the registry.
- `lease_seconds` must be at least 4 times the gateway's `max_create_seconds` (enforced, `ValueError` otherwise). A create that still outlives its lease produces a detected duplicate (incident plus duplicate list), not a prevented one. GitHub offers no idempotency key, so prevention is impossible there.
- Issues that predate the marker are only found through `authoritative_hint`. The first run for such a task must pass the hint, or a new issue is created. The Task Engine wiring must supply it (for M09-P0: #11).

## Wiring a real GitHub gateway

Implement `IssueGateway` (`find_issues`, `create_issue`, `update_issue`, `reopen_issue`, `is_documented_duplicate`, `mark_duplicate`). `create_issue` and `update_issue` must embed `fingerprint_marker(fp)` in the body (the update back-fills issues that predate it). `mark_duplicate` and `update_issue` may only comment or label. `find_issues` should list issues and match the marker; GitHub's search index lags, and a lagging search would hide a just-created issue from the post-create check.

## Integration with #12

The task engine (PR #119) must store `canonical_task_key`, `task_fingerprint`, `github_issue_number`, `github_repository` and `sync_state` and call `ensure_task` before any autonomous issue creation. That step is intentionally not done here, so this change does not touch PR #119's files. #68 stays open until it is done.
