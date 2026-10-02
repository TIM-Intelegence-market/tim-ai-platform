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

## Umsetzung (Builder 1.0.0, 2026-10-01)

`src/research/case_builder.py::assess(case, as_of, gaps, candles)` liefert je
Case: `schema_version` (2), `case_version` (Builder-Version), `case_hash`
(sha256 über Case-ID, Symbol, Timeframe, Evidenz mit Input-Hashes,
Regelversionen; unabhängig von `as_of`), Fenster Start/Ende UTC,
`outcome_due_at` (Fensterende + 12 Bars), `maturity` (PENDING/MATURE),
`observation_count/types`, `data_quality_status` (OK/GAP_EXPOSED/DEFECT),
`gap_exposure` (Gap-IDs), `review_status` (NOT_READY/PENDING/REVIEWED/BLOCKED),
`lineage` (Observation-IDs, Input-Hashes, Regelversionen), `derived_status`.

Statusableitung (CONFIRMED nie automatisch):

| Bedingung | Status |
|---|---|
| CONFIRMED, REJECTED, CLOSED, QUARANTINED, INVALIDATED | bleibt (Review oder terminal) |
| Evidenz defekt (Input-Hash fehlt, unbekannter Typ, nach `as_of`) | QUARANTINED |
| weniger als 2 Observations | OPEN |
| sonst fehlt etwas | COLLECTING_EVIDENCE |
| alles erfüllt | READY_FOR_REVIEW + `Manual Review pending` |

Missing-Evidence-Gründe: `zu wenige Observations`, `Rule Version fehlt`,
`structure_confirmation`, `level_reaction_context`, `continuation_context`,
`Outcome horizon not closed`, `Outcome-Daten unvollständig` (Lücke in den
Candles des Horizonts), `Gap überlappt Case`, `Data Quality unter Schwelle`,
`Manual Review pending`. Nicht automatisch prüfbar und daher nicht
behauptet: Replay und Control/Negative Evidence.

Outcome: beschreibend (`PRICE_INCREASED`/`PRICE_DECREASED`/`PRICE_SIDEWAYS`,
Band ±0,1 %) vom Close am Fensterende bis zum Close am Horizontende, nur wenn
jeder Bar des Horizonts vorhanden ist, kein Gap überlappt und die Evidenz
nicht defekt ist. Keine Empfehlung, kein Signal.

Jede vom Builder ausgelöste Statusänderung steht in `review_history` mit
`by: case_builder`, Builder-Version, Grund und `as_of`.
`ResearchCaseEngine.confirm` akzeptiert jetzt READY_FOR_REVIEW-Cases, deren
einziger offener Punkt `Manual Review pending` ist, und leert danach die Liste.
