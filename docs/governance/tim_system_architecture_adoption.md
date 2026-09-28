# TIM Constitution Band 3 — adoption record

Status: ADOPTED ON GOVERNANCE BRANCH

## Problem and goal

Bands 1 and 2 define mission, values and engineering governance but do not
provide one canonical layered system architecture with platform
responsibilities, forward data flow, contract rules, event/record models and
trust boundaries.

## Decision

`TIM_SYSTEM_ARCHITECTURE.md` is the canonical Band 3 document. The authoritative
precedence is Band 1, Band 2, Band 3, Master Prompts, implementation.

## Alternatives

- Keep architecture distributed across platform documents: rejected because
  precedence and system-wide boundaries would remain ambiguous.
- Rewrite existing platform code immediately: rejected because accepted
  platforms may only change through scoped, reviewed migration work.

## Compatibility and debt

Band 3 is prospective architecture governance. Existing accepted records that
do not yet implement the complete canonical Event or Record model are visible
compatibility debt. This adoption does not authorize retroactive code changes,
schema breakage or migration.

## Acceptance scope

Documentation only. No platform implementation, schema, historical data,
scientific result, test behavior, secret, release tag or runtime artifact is
changed.

## Verification

Verified on branch `codex/tim-constitution`:

- Band-3 file and relative Master-Index link: PASS.
- `git diff --check`: PASS.
- Doctor: PASS, exit code 0.
- Validate: PASS, exit code 0.
- Full TIM suite: 271 passed, 0 failed, 0 skipped, 0 XFAIL/XPASS,
  3 known warnings, exit code 0, duration 67.160 seconds.
- Evidence: `artifacts/test_reports/architecture_band3_full_suite.*`.
- Protected scope: documentation-only.

Final adoption status on this branch: **PASS**.
