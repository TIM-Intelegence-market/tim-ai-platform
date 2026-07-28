# TIM Research Insights Engine 1.0

The Research Insights Engine is a retrospective, read-only component outside
the frozen TIM Core 1.0. It consumes copied persisted orderflow observations,
validations, research cases, the Core manifest, and persisted quality status.
It has no database write method and produces no observations or outcomes.

## Safety and eligibility

The engine never labels results eligible unless all of these are true:

- at least 1,000 fully validated cases;
- at least 100 complete cases per included observation type;
- one consistent Core/metrics/rule/validation version group;
- replay status `PASS`;
- no known data gap or integrity error;
- data coverage is documented.

Until then, output is labelled `NOT_YET_ELIGIBLE` and either
`EXPLORATORY_ONLY` or `INSUFFICIENT_SAMPLE`. TEST_ONLY records and cases are
excluded with stable reasons.

## Determinism

- UTC timestamps and explicit chronological/identifier sorting;
- Decimal arithmetic with half-even rounding to eight decimal places;
- population standard deviation;
- linearly interpolated percentiles using index `(n - 1) × p`;
- SHA-256 over canonical input plus analysis configuration;
- SHA-256 over the complete output payload before `output_hash` is added;
- deterministic JSON, CSV, and Markdown serialization.

Fixed sessions are descriptive labels only:

- ASIA: 00:00–08:00 UTC
- EUROPE: 08:00–16:00 UTC
- USA: 16:00–24:00 UTC

## Interface

- Dashboard: `/insights`
- JSON API: `/api/insights`
- Exports: `/exports/insights.json`, `.csv`, `.md`

The page contains no mutation controls and makes no forecast, probability,
ranking, causal claim, or trading recommendation.

## Known operational limitations

The current running dataset is not eligible: fewer than 1,000 complete cases,
an open persisted `DATA_GAP`, and no completed coverage record. Results must be
treated as exploratory only. Dashboard state is populated from the persisted
runtime read model; if its configured recent-data limit is reached, the engine
must remain ineligible until a complete read-only persisted export is supplied.
