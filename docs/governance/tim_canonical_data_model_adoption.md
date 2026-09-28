# TIM Constitution Band 4 — adoption record

Status: ADOPTED ON GOVERNANCE BRANCH

## Problem and goal

Band 3 defines a common Record model at architecture level but does not fully
specify canonical identity, serialization, hashing, versioning, provenance,
events, snapshots, validation and compatibility.

## Decision

`TIM_CANONICAL_DATA_MODEL.md` is the canonical Band 4 document. It applies
after Bands 1–3 and before every Master Prompt and implementation.

## Alternatives

- Let each platform define its own base record and serialization: rejected
  because hashes and interoperability would diverge.
- Immediately rewrite accepted platform records: rejected because it would
  violate scoped change control and compatibility rules.

## Compatibility debt

Existing accepted platform objects may not yet expose every Band-4 field or use
one common serializer. These deviations are explicit migration debt. This
adoption neither conceals them nor authorizes retroactive code/schema changes.

## Acceptance scope

Documentation only. No platform code, schema, historical data, scientific
result, test behavior, secret, release tag or runtime state is changed.

## Verification

Verified on branch `codex/tim-constitution`:

- Band-4 file and relative Master-Index link: PASS.
- `git diff --check`: PASS.
- Doctor: PASS, exit code 0.
- Validate: PASS, exit code 0.
- Full TIM suite: 271 passed, 0 failed, 0 skipped, 0 XFAIL/XPASS,
  3 known warnings, exit code 0, duration 35.978 seconds.
- Evidence: `artifacts/test_reports/canonical_band4_full_suite.*`.
- Protected scope: documentation-only.

Final adoption status on this branch: **PASS**.
