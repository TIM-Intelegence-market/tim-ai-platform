# Research Case API (Phase 5)

Read-only, OBSERVE-only, keine implizite CONFIRMED-Restriktion.

- `GET /api/research-cases` — Collection mit Filtern `status` (inkl.
  `all`/leer = alle), `timeframe`, `observation_type`, `rule_version`,
  `instrument`, `limit` (1–200, Default 50), `cursor` (case_id).
  Antwort: `{cases, stats, pagination, provenance}`.
- `GET /api/research-cases/stats` — `{stats, provenance}` mit `total`,
  `by_status`, `confirmed`, `pending_outcome`, `missing_evidence`-Counts.
- `GET /api/research-cases/{case_id}` — Detail oder 404
  `{"error": "case not found"}`.
- Legacy `GET /api/cases/{id}` bleibt bestehen.

Implementierung: `_research_cases_collection()` in
`src/dashboard/app_base.py` (reine Funktion, unit-getestet).
Provenance: `PUBLIC_MARKET_DATA_DETERMINISTIC`.
