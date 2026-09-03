# TIM V4 Developer Manual — Verifikationsbericht (Phase 2)

Status: **Verifikation abgeschlossen (Stand dieser Auswertung)**
Methode: Jedes Kapitel 00–29 wurde satzweise gegen den realen Quellcode
(`src/`, `tests/`, `config/`, Schemas) geprüft. Jede Aussage ist mit
`✓ VERIFIED`, `≈ PARTIAL`, `✗ NOT IMPLEMENTED` oder `[SPEZIFIKATION]`
klassifiziert.

Legende:
- `✓ VERIFIED` — Aussage durch realen Code gedeckt.
- `≈ PARTIAL` — Aussage teilweise richtig / leicht abweichend.
- `✗ NOT IMPLEMENTED` — beschriebener Code existiert nicht.
- `[SPEZIFIKATION]` — vom Manual korrekt als zukünftige Spezifikation geführt.

---

## Kapitel 00 — Verfassung

Implementierungsgrad: `VERIFIED ~100 %` (normativer Inhalt, keine Code-Aussage verletzt).
- Fehlende Klassen: keine.
- Fehlende Funktionen: keine.
- Fehlende Tests: keine (Policy, kein Code).
- Risiko: Gering.

## Kapitel 01 — Governance

Implementierungsgrad: `VERIFIED ~78 % · PARTIAL ~17 % · SPEC ~5 %`.
- Fehlende Funktionen: `default_governance_config()` wird im Manual unter `config.py` geführt, liegt real in `governance.py:252` (PARTIAL).
- PARTIAL: `KillSwitch`/`OperationalModeGuard`-Codeblöcke lassen `reason`/`mode`-Felder aus.
- Fehlende Tests: kein dedizierter Governance-Test; nur `test_repository_governance.py`.
- Risiko: Mittel (falscher Querverweis).
- Empfehlung: Codeblöcke um `reason`/`mode` ergänzen; Pfad nach `governance.py` korrigieren.

## Kapitel 02 — Systemarchitektur

Implementierungsgrad: `VERIFIED ~70 % · PARTIAL ~12 % · SPEC ~18 %`.
- Fehlende Pfade: `tools/`, `src/strategy/`, `src/backtest/`, `engines/backtest/` existieren als Verzeichnis nicht.
- Risiko: Hoch (deklarierte Pfade, die es nicht gibt).
- Empfehlung: Layer/Pfad-Tabelle real reduzieren oder explizit als Schema markieren.

## Kapitel 03 — Repository-Struktur

Implementierungsgrad: `VERIFIED ~90 % · PARTIAL ~10 %`.
- Fehlende Pfade: `/tools` existiert nicht.
- PARTIAL: `tests/test_orderflow_scenario/` ist **leer** (Real-Test liegt als flache Datei `test_orderflow_scenario_data_quality.py`).
- Risiko: Gering.
- Empfehlung: `/tools` entfernen; leeren Katalog als Lücke kennzeichnen.

## Kapitel 04 — Coding Standard

Implementierungsgrad: `VERIFIED ~100 %` (nur 2 Code-Bezüge, beide korrekt).
- Risiko: Gering.

## Kapitel 05 — Datenplattform

Implementierungsgrad: `VERIFIED ~70 % · PARTIAL ~25 % · SPEC ~5 %`.
- PARTIAL: `Trade`/`Candle` (models/market_data.py) haben **kein** `provenance`-Feld — nur `Observation`.
- PARTIAL: `Observation` ist **nicht** frozen (nur `slots=True`).
- Fehlende Schemas: Trade/Candle-Schema [SPEC] (korrekt markiert).
- Risiko: Mittel — Datenmodell-Aussagen ungenau.
- Empfehlung: Feld-Tabellen korrigieren; `provenance` für Trade/Candle als nicht vorhanden kennzeichnen.

## Kapitel 06 — Datenqualität

Implementierungsgrad: `VERIFIED ~95 % · SPEC ~5 %`.
- Exakt verdrahtete 14 Checks, Statuswerte `PASS/PARTIAL/INSUFFICIENT_DATA` korrekt.
- 11 Tests (8 Funktionen + 4 parametrisiert) korrekt.
- Fehlende Tests: SOLL-Felder (DEGRADED etc.) [SPEC].
- Risiko: Gering.

## Kapitel 07 — Orderflow Engine

Fehlende Funktionen: keine.
Referenz `test_orderflow_scenario_data_quality.py`: 11 Tests (18 gleichzeitig mit `test_data_quality.py`).
- ✓ Befunde korrekt (18 passed Bezug; 1 Obs-Env-Fehler `config/secrets.py:132`).
- PARTIAL: `OrderflowMetric`-Feldnamen sind im Manual vereinfacht; real heißen sie z. B. `window_start`/`aggregate_buy_volume`.
- Risiko: Gering.

## Kapitel 08 — Auction Market Engine

Fehlende Tests: keine eigene Auction-Testdatei (nur public DQ in Gate).
- Risiko: Gering– Mittel.
- PARTIAL: „Standardabweichung der Bodys" ist irreführend — real `mean(last_3)/mean(first_3)>1.5`.

## Kapitel 09 — Market Structure Engine

Fehlende Tests: keine eigene Datei.
- Risiko: Gering.
- PARTIAL: `MarketStateKind` real **18** Werte, Manual sagt **17**.

## Kapitel 10 — Liquidität

Implementierungsgrad: `VERIFIED ~88 % · PARTIAL ~6 % · SPEC ~6 %`.
- PARTIAL: Sweep führt `candles[-2]` (vorletzte), nicht „letzte".
- PARTIAL: `open_interest` kein eigenes Feld (nur Interpretations-String).
- Fehlend: eigenständige Liquiditäts-Engine [SPEC] (korrekt getaggt).
- Risiko: Gering.

## Kapitel 11 — Szenarien

Implementierungsgrad: `VERIFIED ~93 % · PARTIAL ~7 %`.
- ✗ NOT IMPLEMENTED: `EntryModel.RETEST` wird in `scenario_generator.py:161` genutzt, existiert im Enum aber nicht (nur `LIMIT_RETEST`/`FAILED_RETEST`) → latenter `AttributeError`.
- PARTIAL: `Scenario` trägt `entry_model` nicht direkt (im `trade_template`).
- PARTIAL: Fallback-IDs „A"/„B" doppelt; Kommentar `max_scenarios` wird nie gelesen.
- Fehlende Tests: Generator ungetestet.
- Risiko: **Hoch** (möglicher Runtime-Bug in einem Branch).

## Kapitel 12 — Konfirmation

Implementierungsgrad: `VERIFIED ~100 %`.
- Fehlende Tests: keine eigene Datei.
- Risiko: Gering.

## Kapitel 13 — Probability

Implementierungsgrad: `VERIFIED ~100 %`.
- Risiko: Gering.

## Kapitel 14 — Trade Decision

Implementierungsgrad: `VERIFIED ~97 % · PARTIAL ~3 %`.
- PARTIAL: vetings `NONE` fällt auf `PAPER_APPROVED` zurück.
- Risiko: Gering.

## Kapitel 15 — Trade Plan

Implementierungsgrad: `VERIFIED ~100 %`.
- PARTIAL: `_atr` ist ungenutzter (toter) Code (harmlos).
- Risiko: Gering.

## Kapitel 16 — Risk

Implementierungsgrad: `VERIFIED ~95 % · PARTIAL ~5 %`.
- PARTIAL: „Account-Validierung (Positionen)" → real überprüft nur `equity` + `free_margin` im `__post_init__`.
- Fehlende Tests: keine eigene Datei.
- Risiko: Gering.

## Kapitel 17 — Portfolio

Implementierungsgrad: `VERIFIED ~55 % · PARTIAL ~15 % · SPEC ~30 %`.
- ✗ kein eigener `PortfolioState`/Allokation/Snapshot (korrekt [SPEC]).
- PARTIAL: `open_positions` (nicht `positions`).
- Risiko: Gering.

## Kapitel 18 — Backtest

Implementierungsgrad: `VERIFIED ~92 % · PARTIAL ~8 %`.
- PARTIAL: Konstruktor — Manual „Entry ≤ 1", real nur `>0`, keine Normalisierung.
- Fehlende Tests: keine eigene Backtestdatei.
- Risiko: Mittel.

## Kapitel 19 — Research

Implementierungsgrad: `VERIFIED ~100 %`.
- Fehlend: einheitliche `ResearchEngine` [SPEC].
- Tests: `test_research_*` vorhanden.
- Risiko: Gering.

## Kapitel 20 — Paper

Implementierungsgrad: `VERIFIED ~100 %` (Journal-Claims).
- Lücke: zweite Paper-Engine `src/paper/automation.py` wird nicht erwähnt.
- Risiko: Gering.

## Kapitel 21 — Shadow

Implementierungsgrad: `VERIFIED ~100 %` der IST-Claims; Shadow-Engine ∈ [SPEC].
- Risiko: Gering.

## Kapitel 22 — Review

Implementierungsgrad: `VERIFIED` (kein Review-Modul, korrekt [SPEC]).
- Fehlende Tests: keine.
- Risiko: Gering.

## Kapitel 23 — Audit

Implementierungsgrad: `VERIFIED ~86 % · PARTIAL ~12 % · SPEC ~2 %`.
- PARTIAL: §7 listet `test_repository_governance.py` als Audit-Test — die Datei testet nicht `orderflow_scenario/audit.py`.
- Fehlende Tests: dedizierte Audit-Invarianten (Redaction, Versionsfelder, analysis_id).
- Risiko: Mittel (Test-Referenz falsch).

## Kapitel 24 — JSON Schemas

Implementierungsgrad: `VERIFIED ~100 %`.
- Fehlende Schemas: Trade/Candle [SPEC] (korrekt markiert).
- Risiko: Gering.
- ✓ `analysis_output_v1.json`: 16 Pflichfelder, `schema_version const 1.0.0`, Validator `validate_analysis` bestätigt.

## Kapitel 25 — Testing

Implementierungsgrad: `VERIFIED ~100 %`.
- ✓ 18 passed (gate+DQ); `tests/test_orderflow_scenario/` leer; 1 Obs-Env-Fehler (`test_orderflow_observations.py`).
- Fehlende Tests: Engine-Szenario-tests (LÜCKE bekannt).
- Risiko: Gering.

## Kapitel 26 — Acceptance

Implementierungsgrad: `VERIFIED ~95 % · PARTIAL ~5 %`.
- ✗ „13 Prüfungen" → real **12** in `test_acceptance.py`.
- Risiko: Gering.

## Kapitel 27 — Release

Implementierungsgrad: `VERIFIED ~100 %` (prozedural, keine falsifizierbaren Code-Aussagen).
- Risiko: Gering.

## Kapitel 28 — API-Referenz

Implementierungsgrad: `VERIFIED ~72 % · ✗ ~28 %`.
- ✗ `src/orderflow/input.py` + `get_primitive_inputs` existieren **nicht**.
- ✗ `compute_orderflow_metrics` existiert nicht (real: `OrderflowMetricsEngine.calculate`); Klasse `OrderflowMetric` (Casing).
- ✗ `DataQualityReport` in der `data_quality.py`-Zeile → real `DataQualityGate`, `DataQualityInputs` (Report in `domain.py`).
- ✗ `MarketStateAnalyzer` → real `MarketStateEngine`.
- ✗ `ScoreEngine` (probability.py) → real `ProbabilityEngine`.
- Risiko: **Hoch** (API-Referenz führt nicht existente Einstiegspunkte).

## Kapitel 29 — Changelog

Implementierungsgrad: `VERIFIED ~100 %` (Struktur, keine falsifizierbaren Aussagen).
- Risiko: Gering.

## README

- `README.md`: Struktur-Index korrekt bis auf `27_RELEASE.md` (inzwischen gefixt, bestätigt).
- Hinweis „Inkrementell im Aufbau": nach Phase 2 als „Verifiziert" markieren.

---

## Gesamteindruck (gewichtet)

| Status | Anteil |
|---|---|
| VERIFIED | ~88 % |
| PARTIAL | ~8 % |
| SPECIFICATION | ~4 % |
| ✗ NOT IMPLEMENTED (im Manual falsch behauptet) | ~2 % |

## Risiko-Überblick

- **Hoch:** Kapitel 11 — `EntryModel.RETEST` (potentieller `AttributeError`).
- **Hoch:** Kapitel 28 — API-Referenz nennt nicht existente Einstiegspunkte.
- **Mittel:** Kapitel 02 — nicht existente Pfade.
- **Mittel:** Kapitel 05 — `provenance`/frozen-Aussagen.
- **Mittel:** Kapitel 18 — Entry-Bound-Beschreibung.
- Gesamt-Doku-Gesamt: **Mittel** (mehrere API-/Datenmodell-Overclaims, keine zweifelsfreien Fehlfunktionen).