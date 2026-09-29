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
   - `authoritative_hint` given and that issue exists: adopt it even if it predates the marker (#11 and #22–#65 do); `legacy_issues` and other marker matches are recorded as duplicates
   - one marker match: adopt it (`RECOVERED`), no create
   - several matches without hint: `BLOCKED` plus a governance incident; a later call with a valid hint unblocks it
   - none: renew the lease (fails if the claim was taken over, then nothing is created) and create exactly once
5. Uniqueness check after creating. A second match blocks the task and records an incident. Nothing is ever closed automatically.
6. Persist the mapping with the fencing token (issue number, repository, duplicate list). If the claim was lost meanwhile, the task is `BLOCKED` (`CLAIM_LOST_AFTER_CREATE`), never reported as cleanly created.

A failure before anything was created (for example GitHub unreachable) releases the claim.

## Policies

| Situation | Behaviour |
|---|---|
| Retry, restart, usage-limit resume | Same issue, updated |
| Closed authoritative issue | Never replaced. Reopened only with `ReopenPolicy.EXPLICIT` and `retry=True`, otherwise an audit comment |
| Historical duplicates | Kept as audit evidence, marked "duplicate of" once if not yet documented, never closed or deleted |
| Creator crashed after creating the issue | Same claimant resumes at once, others after `lease_seconds`; the marker search finds the issue and adopts it |
| Local registry lost | Mapping recovered from the GitHub marker |

The gateway interface has no close operation on purpose. `trusted_authors` restricts which marker matches count, so someone who copies the marker into another issue cannot hijack or block a task.

## Limits

- The create-once guarantee holds for all workers that share one registry file. Workers with separate registries (for example cloud sessions and a Mac LaunchAgent) are protected only by the GitHub-side checks, which are not atomic. Run task creation from one place or share the registry.
- The lease must be much longer than one `create_issue` call. Between the final lease renewal and the create there is a short window that only the after-create check covers.

## Wiring a real GitHub gateway

Implement `IssueGateway` (`find_issues`, `create_issue`, `update_issue`, `reopen_issue`, `is_documented_duplicate`, `mark_duplicate`). `create_issue` and `update_issue` must embed `fingerprint_marker(fp)` in the body (the update back-fills issues that predate it). `mark_duplicate` and `update_issue` may only comment or label. `find_issues` should list issues and match the marker; GitHub's search index lags, and a lagging search would hide a just-created issue from the post-create check.

## Integration with #12

The task engine (PR #119) must store `canonical_task_key`, `task_fingerprint`, `github_issue_number`, `github_repository` and `sync_state` and call `ensure_task` before any autonomous issue creation. That step is intentionally not done here, so this change does not touch PR #119's files. #68 stays open until it is done.
