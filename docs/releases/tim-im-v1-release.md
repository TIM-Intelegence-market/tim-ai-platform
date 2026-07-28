# TIM Intelligence Manager V1 — Technical Release

Release: `tim-im-v1.0.0`
Status: `PASS`
Release date: 2026-07-28
Scope: local TIM Intelligence Manager V1

## Release decision

TIM Intelligence Manager V1 is technically accepted and functionally frozen.
The release establishes TIM-IM as the read-only knowledge, provenance and
management layer for future TIM work.

The release does not add trading behavior, change scientific models, rewrite
historical data or modify existing Research, Evaluation or Orderflow results.

## Acceptance evidence

| Evidence | Result |
|---|---|
| Mandatory scenarios | 20/20 passed, 0 XFAIL |
| TIM-IM tests | 58 passed |
| Full TIM regression | 237 passed |
| Warnings | 145 pytest-asyncio deprecation warnings |
| Doctor | PASS |
| Validate | PASS |
| Snapshot schema | 1.1; historical 1.0 snapshot remains valid |
| Local MCP | read-only boundary validated |
| Protected paths | TIM-IM writes denied; no TIM-IM protected write observed |

## Frozen acceptance references

- Content manifest:
  `22b258c5fd8eac5e4d3cff0ef648b96c1ce00665c6b11e58a7f5e2b491a10c1b`
- Snapshot ID: `43312fa2-a863-5f56-9765-0d7a224239be`
- Snapshot file SHA-256:
  `73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d`
- Snapshot schema: `1.1`
- Final acceptance:
  `docs/tim_manager/final_acceptance_review.md`
- Acceptance matrix:
  `docs/tim_manager/acceptance_test_matrix.md`

These references describe the accepted TIM-IM state immediately before
repository initialization. Repository history beginning with the initial
commit provides the authoritative version reference from this release onward.

## Repository authority

- Repository root: `/Users/tim/Documents/TIM/tim`
- Initial commit:
  `f1b267e650ace8fb4d50e01496ac50b593887e3f`
- Release branch: `main`
- Release ref: `refs/tags/tim-im-v1.0.0`
- Remote: not configured

Resolve the exact release commit with:

```text
git rev-list -n 1 tim-im-v1.0.0
```

## Freeze rule

TIM-IM V1 may receive release-engineering, documentation, security or
compatibility corrections only. Any behavior change requires a new version,
an explicit acceptance delta and a complete regression run.

TIM V2 work must be implemented outside the frozen V1 behavior contract.
