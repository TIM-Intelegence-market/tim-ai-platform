# Research Case Materialisierung (Phase 4)

Skript: `scripts/materialize_research_cases.py` (nur Test-DB 5433/tim_test,
0600-Secret, `TIM_ENV=test`, Safety-Guard).

Ablauf: Dry-Run (Memory, Preview-JSON, keine DB) → Apply (schema.sql
evolvieren, Candles+Observations+Cases transaktional, Manifest) →
Validate (Re-Read, Counts/Hashes) → 2. Apply (0 Changes = Idempotenz).

Echter Codepfad: Fixture-Candles → `ObservationEngine.evaluate`
(deterministische IDs, Provenance) → `ResearchCaseEngine.ingest` →
`save_observation_with_case` (Hash-validiert, transaktional, Upsert).

Befund 2026-09-20: 3 Fenster → 3 Observations (BOS_BULLISH, REJECTION,
FAILED_CONTINUATION) → 3 Cases, Manifest-Hash stabil über Re-Runs.
Lektion: Engine evaluiert kumulativ (Live-Verhalten); Fixture-Preise als
Float (DB-Roundtrip); Timestamps historisch (Validator).

Manifest: `artifacts/research_cases/materialization_manifest.json`
Preview: `artifacts/research_cases/preview.json`
Validation: `artifacts/research_cases/validation.json`
