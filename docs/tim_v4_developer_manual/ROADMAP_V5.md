# TIM — ROADMAP V5

Diese Roadmap basiert **ausschließlich** auf den während der Phase-2-Verifikation
gefundenen Lücken (siehe `IMPLEMENTATION_GAP.md`, `VERIFICATION_REPORT.md`).
Kein Eintrag ist abstrakte Idee; jeder hat Problem, Ursache, Auswirkung,
Lösung, Aufwand, Abhängigkeit und Priorität.

Legende Priorität: 1 = sofort, 2 = geplant, 3 = optional.

---

## V5-01 Fix `EntryModel.RETEST`

- **Problem:** `scenario_generator.py:161` referenziert `EntryModel.RETEST`, das im Enum nicht existiert.
- **Ursache:** Enum-Migration (`LIMIT_RETEST` etc.) nicht überall nachgezogen.
- **Auswirkung:** latenter `AttributeError` in einem Breakout-Branch zur Laufzeit.
- **Lösung (empf.):** Zuweisung auf `LIMIT_RETEST` setzen; Branch-Unittest ergänzen.
- **Aufwand:** klein (≤ 0,5 Tag).
- **Abhängigkeit:** `domain.py`.
- **Priorität:** 1.
- **Status:** erledigt (PR #121, `LIMIT_RETEST`; Test in `tests/test_orderflow_engine_edge_cases.py`).

## V5-02 API-Referenz korrigieren

- **Problem:** Kapitel 28 nennt nicht existente Namen (`get_primitive_inputs`, `compute_orderflow_metrics`, `DataQualityReport` in `data_quality.py`, `MarketStateAnalyzer`, `ScoreEngine`).
- **Ursache:** veraltete/nicht verifizierte Namen übernommen.
- **Auswirkung:** falsche Einstiegspunkte für Entwickler.
- **Lösung (empf.):** Kapitel 28 an reale Namen angleichen (`OrderflowMetricsEngine.calculate`, `OrderflowMetric`, `DataQualityGate`, `MarketStateEngine`, `ProbabilityEngine`).
- **Aufwand:** klein.
- **Abhängigkeit:** keine.
- **Priorität:** 1.

## V5-03 Systemarchitektur-Pfade bereinigen

- **Problem:** `tools/`, `src/strategy/`, `src/backtest/`, `engines/backtest/` dokumentiert, existieren nicht.
- **Ursache:** Layer-Pfad plakativ.
- **Auswirkung:** falsche Paket-Umfang-Modelle.
- **Lösung:** Pfade auf echte Struktur reduzieren bzw. als [SPEC] markieren.
- **Aufwand:** klein.
- **Abhängigkeit:** keine.
- **Priorität:** 1.

## V5-04 Datenmodell-`provenance` klären

- **Problem:** Manual nennt `provenance` für `Trade`/`Candle`, existiert nur auf `Observation`.
- **Ursache:** Lineage-Anspruch und Ist-Feld vorgemischt.
- **Auswirkung:** falsche Feld-Überblicke.
- **Lösung:** Manual korrigieren; Feld für Trade/Candle nachrüsten (wenn Lineage verlangt).
- **Aufwand:** klein (Doku) bis mittel (Feld).
- **Abhängigkeit:** Schema/Datenbank.
- **Priorität:** 2.

## V5-05 Account-Validierung & Backtest-Bound dokumentieren

- **Problem:** Risk-„Positionen"-Validierung und Backtest-Entry-Bound unpräzise.
- **Ursache:** Formulierungsfehler.
- **Auswirkung:** reduzierte Dokugenauigkeit.
- **Lösung:** Text korrigieren (`open_positions` wird nicht im `__post_init__` validiert; Backtest prüft nur `>0`).
- **Aufwand:** klein.
- **Abhängigkeit:** keine.
- **Priorität:** 2.

## V5-06 Governance-Codeblöcke & Standort aktualisieren

- **Problem:** `default_governance_config()` in `governance.py`, nicht `config.py`; Codeblöcke ohne `reason`/`mode`.
- **Ursache:** unvollständige Codeblöcke im Manual.
- **Auswirkung:** falscher Querverweis, inkonsistente Blöcke.
- **Lösung:** Pfad/Blöcke korrigieren.
- **Aufwand:** klein.
- **Priorität:** 2.

## V5-07 `MarketStateKind`-Zahl & Liquiditäts-Formulierungen

- **Problem:** 17 vs 18 Werte; Sweep-Verschiebung (`candles[-2]`), OI.
- **Lösung:** Ziffern/Text korrigieren.
- **Priorität:** 3.

## V5-08 Audit-Test-Referenz & Dedizierte Audit-/Backtest-/Engine-Tests

- **Problem:** `test_repository_governance.py` deckt Audit nicht ab (→ M-01); keine eigenen Tests für backtest, engines, audit-invariants.
- **Ursache:** Testreferenz ohne Code-Verifikation übernommen.
- **Lösung:** richtige Referenz; neue Tests.
- **Aufwand:** mittel.
- **Priorität:** 2.

## V5-09 Kleinanpassungen (toter Code, IDs, Counts)

- **Problem:** `_atr` toter Code; doppelte Szen-ID; `max_scenarios` ungenutzt; 12 statt 13 Tests.
- **Lösung:** je ein kleiner Fix.
- **Aufwand:** klein.
- **Priorität:** 3.

---

### Empfohlene Reihenfolge
V5-01 → V5-02 → V5-03 (Fehler dringend), danach V5-04…08 (Doku/Rundung), zuletzt V5-09.

### Kein Ideen-Roadmap
Alle obigen Einträge leiten sich direkt aus codierten Fundstellen ab; keine
fiktiven Features ohne Referenz.