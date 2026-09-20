# Research Case Domänenmodell (Phase 2)

## Felder

`case_id` (deterministisch, s. Phase 1), `schema_version`,
`case_version`, Markt/Instrument (`symbol`, `timeframe`),
Start/Ende UTC (`opened_at`, `updated_at`), `status`, Observation
IDs/Count/Types, `rule_versions`, Evidence + Missing Evidence,
Outcome/Maturity, Data Quality, Gap Exposure, Replay, Review,
Source-/Case-Hash + Lineage (`input_hash`, Provenance).

## Status-Lifecycle

`OPEN → COLLECTING_EVIDENCE → READY_FOR_REVIEW → CONFIRMED`
Seitenäste: `→ REJECTED`, `→ QUARANTINED` (defekte Observations),
terminal: `CLOSED` (Outcome gesetzt). Übergänge nur vorwärts
(kein Retrograd), jeder Übergang mit Begründung + Timestamp.

`CONFIRMED` nur bei ALLEN Kriterien: volle Evidenz (kein Missing),
Outcome-Horizont geschlossen, kein Gap-Overlap, Rule-Version vorhanden,
Replay abgeschlossen, Control/Negative Evidence vorhanden, Data Quality
≥ Schwelle, Manual Review erfolgt.

## Missing-Evidence-Gründe (geschlossenes Vokabular)

`Outcome horizon not closed`, `Gap überlappt Case`, `zu wenige
Observations`, `Rule Version fehlt`, `Replay nicht abgeschlossen`,
`Control/Negative Evidence fehlt`, `Data Quality unter Schwelle`,
`Manual Review pending`.

## Regeln

Kein Random-UUID/Zeit in IDs. Keine implizite CONFIRMED-Restriktion in
API/UI. Stats echt über alle Status. QUARANTINED statt Löschen.
