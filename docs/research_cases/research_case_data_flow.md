# Research Case Datenpfad (Phase 1)

Binance Raw (public WS, keine Auth) → `CandleAggregator` (1m/5m/15m/1h,
`candle_input_hash`) → Feature/Observation (`ObservationEngine`,
Verified-only, Lookahead-Schutz, `rule_id`/`rule_version` bos/bronxc
1.0.0, Provenance `PUBLIC_MARKET_DATA_DETERMINISTIC`) → Research Trigger
(idempotent, `data/research/trigger_state.json`) → Case Builder
(`ResearchCaseEngine`, `case_id = case_+sha256(symbol:timeframe:window)[:16]`,
30-Min-Fenster) → Persistence (`repository.save_observation_with_case`,
`upsert_research_case`, `research_cases`-Tabelle) → API (NEU:
`GET /api/research-cases`, `/{case_id}`, `/stats`) → UI (`/cases`,
Default ALL ACTIVE).

Orderflow-Zweig: `OrderflowResearchCaseEngine` (`ofcase_+sha256[:20]`),
`save_orderflow_observation_with_case`, Validierung
(`pending_orderflow_observations` → `save_orderflow_validation`).

Liveness: `main.py` Observation-Schleife (ingest→persist→trigger→
Dashboard-State) + `restore_persisted_state` (Replay ab ältester
persistierter Candle, idempotent) + Orderflow-Fenster.

Garantien: deterministisch (kein UUID/Zeit in IDs), idempotent
(Upserts nach case_id), Provenienz lückenlos, Raw unverändert
(nur abgeleitete Cases).
