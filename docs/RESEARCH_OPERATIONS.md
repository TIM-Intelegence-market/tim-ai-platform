# TIM Research Operations

Research Operations is an external OBSERVE-only layer for the frozen TIM Core
1.0. It contains three deterministic components and does not import into or
alter Core runtime logic.

## Research Audit Engine

`ResearchAuditEngine` recursively inspects persisted research artifacts,
validates JSON/JSONL structure, timestamps, provenance, report sidecars,
artifact hashes, declared output/report/snapshot hashes, and version metadata.
It exposes no file-write method. Findings identify missing documentation but do
not modify source artifacts.

## Research Quality Engine

`ResearchQualityEngine` checks operational and research event records for:

- valid schemas and timezone-aware timestamps;
- future timestamps and forward-only sequence order;
- documented `DATA_GAP` events;
- OBSERVE-only mode;
- current provenance and audit integrity.

It never repairs, interpolates, or reconstructs missing records.

## Monthly Research Snapshot

`MonthlyResearchSnapshot` combines read-only database counts, closed 1-minute
candle coverage, replay status, Research Insights status, and Quality findings.
An active UTC month is emitted as `IN_PROGRESS`; the canonical final month file
is only produced after that month ends.

Coverage uses persisted closed `BTCUSDT` 1-minute candle timestamps:

`observed distinct minutes / expected minutes from first through last candle`.

No absent interval is filled. Snapshot hashes cover the complete canonical
payload before `snapshot_hash` is appended.

## Running the review

```bash
.venv/bin/python scripts/research_infrastructure_review.py
```

Outputs:

- `data/research/audit/latest.json`
- `data/research/quality/latest.json`
- `data/research/snapshots/YYYY-MM.in_progress.json` and `.md` during a month
- `data/research/snapshots/YYYY-MM.json` and `.md` after month end

The script performs database `SELECT` operations only. Its file writes are
limited to the external research-report directories listed above.

## Current limitations

The July 2026 snapshot is provisional. Current persisted evidence reports an
unresolved data gap, incomplete Acceptance provenance, and legacy Module A
cache entries without schema/generator/artifact-hash metadata. These are
reported, not automatically corrected.
