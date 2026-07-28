# TIM Research Dashboard V2

## Scope

Version 2.0.0 modernizes only the read-only research interface. It does not
change market rules, observation generation, persistence semantics, research
logic, AI configuration, or execution governance. TIM remains in `OBSERVE`
mode and exposes no order or trading controls.

## Pages

- `/` — Research Overview with acceptance, quality, stream, validator,
  runtime, case, candle, observation, and version cards.
- `/observations` — read-only observation explorer with deterministic
  evidence score, provenance, rule version, status, and full details.
- `/cases` — research case explorer with lifecycle filters, missing evidence,
  duration, outcome, and evidence timeline.
- `/health` — component health for database, stream, validator, dashboard,
  replay, acceptance, data quality, research integrity, and governance.
- `/timeline` — persisted operational events. Trading and order events are
  explicitly excluded.
- `/research` — existing local research workflow in a dedicated workspace.

All visible counts identify whether they are persisted totals or the latest
visible window. Missing values render as an em dash; the UI does not infer or
invent them.

## Data contracts

The existing `/api/state` contract remains compatible and now also includes:

- `dashboard_version`
- `case_counts`
- `timeline`

Read-only detail endpoints:

- `/api/observations/<observation_id>`
- `/api/cases/<case_id>`

## Validation

- Full suite: 109 tests passed.
- Dashboard suite: 16 tests passed, including route, detail, filtering,
  health, timeline, restart equivalence, and latency checks.
- Python compilation passed.
- After controlled restart, exactly one TIM runtime and one validator were
  active.
- All UI routes returned HTTP 200.

## Performance

Persisted pre-change dashboard health sample: 2.27 ms for the root request.
Post-change warm root samples ranged from 1.90 ms to 2.81 ms. Warm
`/api/state` samples ranged from 4.83 ms to 11.13 ms. Cold navigation across
all richer pages ranged from 12.8 ms to 87.3 ms. All routes remained below the
existing 500 ms threshold, and the automated route regression requires every
page to stay below 500 ms.

The operational event timeline is cached by the persisted event-file version,
so 5-second dashboard polling does not repeatedly parse an unchanged log. The
market-data and validation loops are unaffected.

## Known limitations

- News remains inactive until an authorized source connector exists.
- Acceptance remains red while the persisted historical `DATA_GAP` finding is
  open.
- Observation and case pages show the latest persisted in-memory window;
  they do not fabricate database totals or reconstruct missing records.
