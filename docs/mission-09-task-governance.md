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
   - `authoritative_hint` given but the issue does not exist (`HINT_NOT_FOUND`), is a pull request, or has an untrusted author (`HINT_INVALID`): `BLOCKED`, nothing written into that issue, never a fallthrough to create
   - no hint, or the listed hint, and the task is listed in `legacy.py` for this repository (today: M09-P0 audit → #11, duplicates #22–#65 in `uezeyiraydin-cell/tim-ai-platform`): the listed authority and duplicates are used automatically. The table is bound to a repository, so other repositories are never touched
   - one marker match: adopt it (`RECOVERED`), no create
   - several matches without hint: `BLOCKED` plus a governance incident; a later call with a hint unblocks it only if the hint addresses the block: it must be one of the structured `block_candidates` stored on the task row (`AMBIGUOUS_DUPLICATES`, `DUPLICATE_AFTER_CREATE`) or differ from the rejected hint (`HINT_NOT_FOUND`, `HINT_INVALID`). An always-passed hint therefore cannot wave away unrelated incidents
   - none: renew the lease (fails if the claim was taken over, then nothing is created) and create exactly once
5. If `create_issue` raises (for example a timeout after GitHub created the issue), record `CREATE_UNCERTAIN` and search by marker before anything else: one match is adopted, several block, none or unreachable keeps the claim held until the lease expires and re-raises. Otherwise: uniqueness check after creating. A second match blocks the task and records an incident. Nothing is ever closed automatically.
6. Adopt path order: mark duplicates and write the marker first (all idempotent, comment/label only), persist the mapping last, so a crash midway repeats the remaining steps on the next run.
7. Persist the mapping with the fencing token (issue number, repository, duplicate list). If the claim was lost meanwhile, the result is `BLOCKED` (`CLAIM_LOST_AFTER_CREATE`), never reported as cleanly created. The stale worker only records an incident and adds its issue to the winner's duplicate list; it cannot overwrite the winner's state (fenced writes).

A `MAPPED` task is never downgraded to `BLOCKED`, not even by an unfenced operator call; such a call only records an incident.

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
- Fencing tokens are monotonic per task: rows are never deleted, releasing or unblocking sets `RELEASED`, so a stale worker's old token can never match a later claim.
- The gateway must declare `max_create_seconds` and enforce it as the `timeout` of `create_issue`; a create that exceeds it is recorded as a `SLOW_CREATE` incident. `lease_seconds` must be at least 4 times that value (`ValueError` otherwise). A create that still outlives its lease produces a detected duplicate (incident plus the stale worker's issue in the winner's duplicate list), not a prevented one. GitHub offers no idempotency key, so prevention is impossible there.
- Issues that predate the marker are only found through `authoritative_hint` or the built-in `legacy.py` table. A legacy task that is not listed there and is called without a hint creates a new issue. New legacy cases must be added to the table.

## Wiring a real GitHub gateway

Pull requests are never treated as task issues (`find_issues` results with `is_pull_request` are dropped). A gateway raises `CreateNotSent` only when `create_issue` failed before any request left the process; that releases the claim immediately. Any other exception is treated as uncertain (see step 5). A registry file from an earlier release is migrated on open (`PRAGMA user_version`, missing columns added).

Implement `IssueGateway` (`find_issues`, `create_issue`, `update_issue`, `reopen_issue`, `is_documented_duplicate`, `mark_duplicate`). `create_issue` and `update_issue` must embed `fingerprint_marker(fp)` in the body (the update back-fills issues that predate it). `mark_duplicate` and `update_issue` may only comment or label. `find_issues` should list issues and match the marker; GitHub's search index lags, and a lagging search would hide a just-created issue from the post-create check.

## Integration with #12

The task engine (PR #119) must store `canonical_task_key`, `task_fingerprint`, `github_issue_number`, `github_repository` and `sync_state` and call `ensure_task` before any autonomous issue creation. That step is intentionally not done here, so this change does not touch PR #119's files. #68 stays open until it is done.
