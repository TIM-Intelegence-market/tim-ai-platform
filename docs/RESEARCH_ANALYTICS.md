# TIM Research Analytics V1

`/analytics` is a read-only statistical view over observations, research cases,
and operational events already persisted by TIM. The engine creates no market
rules, observations, predictions, rankings, probabilities, or confidence scores.

## Definitions

- Average duration: span between the first and last persisted observation in an associated case.
- Average lifetime: persisted `updated_at - opened_at` of associated cases.
- Average timeframes: mean number of distinct persisted timeframes per associated case.
- Stored evidence score: the existing observation `confidence` field, used only as a cluster dimension and never recalculated.
- Rates: exact status counts divided by associated persisted case count.

All grouping keys and output rows are sorted. The dataset hash is SHA-256 over
canonical JSON input, so identical persisted inputs produce identical analytics
and identical exports.

## Read-only endpoints

- `/api/analytics`
- `/exports/analytics.csv`
- `/exports/analytics.json`
- `/exports/analytics.md`

The runtime retains up to the same 1,000 observations and 1,000 research cases
loaded from persistence for analytics. The normal dashboard tables still expose
only the latest 50 items.
