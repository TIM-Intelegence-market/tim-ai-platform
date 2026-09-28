# TIM Constitution Band 2 — adoption record

Status: ADOPTED ON GOVERNANCE BRANCH

## Problem and goal

Band 1 defines TIM's mission and constitutional values but does not fully
specify repository, branching, commit, schema, review, documentation, merge,
release and multi-agent rules. Band 2 supplies those rules without changing
platform behavior.

## Decision

`TIM_ENGINEERING_GOVERNANCE.md` is the canonical Band 2 document. Repository
precedence is Band 1, then Band 2, then Master Prompts, then implementation.

## Alternatives

- Embed Band 2 into Band 1: rejected because the two authoritative bands have
  distinct purposes and precedence.
- Duplicate the rules in all platform prompts: rejected because copies drift.

## Risks

- Existing accepted platforms may not yet possess every newly required
  documentation artifact. This is visible governance debt and does not
  authorize silent retroactive platform changes.
- Merge and release actions remain separately gated.

## Acceptance scope

This adoption is documentation-only. It changes no platform code, schema,
historical data, test behavior, secret, release tag or scientific result.

## Verification

Verified on branch `codex/tim-constitution`:

- Band-2 file and relative Master-Index link: PASS.
- `git diff --check`: PASS.
- Doctor: PASS, exit code 0.
- Validate: PASS, exit code 0.
- Full TIM suite: 271 passed, 0 failed, 0 skipped, 0 XFAIL/XPASS,
  3 known warnings, exit code 0, duration 40.467 seconds.
- Evidence: `artifacts/test_reports/governance_band2_full_suite.*`.
- Protected scope: documentation-only.

Final adoption status on this branch: **PASS**.
