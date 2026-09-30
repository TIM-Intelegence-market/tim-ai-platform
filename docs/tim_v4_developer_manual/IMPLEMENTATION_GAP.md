# TIM — IMPLEMENTATION_GAP Register

Quelle: Verifikation der 30 Manual-Kapitel gegen den realen Quellcode (Phase 2).
Jeder Eintrag benennt eine real gefundene Lücke/Überanspruch mit Priorität.
`[SPEC]` = im Manual korrekt als zukünftige Spezifikation ausgewiesen (kein Fehler).

---

## HIGH

### H-1 `EntryModel.RETEST` ist nicht definiert, wird aber verwendet
- Kapitel: 11 — Szenario-Engine.
- Quelle: `scenario_generator.py:161` nutzt `EntryModel.RETEST`; Enum `domain.py:138-148` kennt nur `LIMIT_RETEST`/`FAILED_RETEST`.
- Folgen: latenter `AttributeError` in einem Szenario-Branch.
- Lösung: Zuweisung auf `EntryModel.LIMIT_RETEST` korrigieren; Test für den Branch ergänzen.
- Abhängigkeit: Domain/Enum (klein).
- Status: erledigt (PR #121).

### H-02 API-Referenz nennt nicht existente Einstiegspunkte
- Kapitel: 28.
- Quelle: `get_primitive_inputs` (src/orderflow/input.py fehlt gänzlich), `compute_orderflow_metrics`, `DataQualityReport` in data_quality.py, `MarketStateAnalyzer`, `ScoreEngine`.
- Ursachen: teilweise historische Namen; eigentliche Code-Namen ergänzen oder anpassen.
- Folgen: Dok-Nutzer greifen auf API-Punkte zu, die nicht existieren.
- Lösung: API-Referenz an reale Namen anpassen (`OrderflowMetricsEngine.calculate`, `OrderflowMetric`, `DataQualityGate`, `MarketStateEngine`, `ProbabilityEngine`) und `input.py`-Abschnitt entfernen oder als [SPEC] kennzeichnen.

### H-03 Lineage/Pfad-Overclaims in der Systemarchitektur
- Kapitel: 02 — Systemarchitektur.
- Quelle: `tools/`, `src/strategy/`, `src/backtest/`, `src/orderflow_scenario/engines/backtest/` existieren nicht.
- Folgen: falsche Paket-Umfang sicherstellt.
- Lösung: Layer-Tabelle auf reale Struktur reduzieren bzw. Pfade als [SPEC] markieren.

---

## MEDIUM

### M-01 Test-Referenz im Audit-Kapitel falsch
- Kapitel: 23.
- Quelle: `test_repository_governance.py` testet DB/Repository/Observation, nicht `orderflow_scenario/audit.py`.
- Lösung: Audit-Test-Referenz auf die tatsächlich vorhandene Abdeckung korrigieren; dedizierte Audit-Invarianten-Tests ergänzen.

### M-02 `provenance` auf Trade/Candle dokumentiert, existiert nicht
- Kapitel: 05.
- Quelle: models/market_data.py (Trade 15-21, Candle 31-42) — kein Feld `provenance`; nur `Observation` hat es.
- Lösung: Datenmodell-Tabelle korrigieren; ggf. Feld nachrüsten, wenn Lineage verlangt ist.

### M-03 `Observation` ist nicht frozen
- Kapitel: 05.
- Quelle: `Observation` (market_data.py:73) `@dataclass(slots=True)`, nicht frozen.
- Lösung: entweder im Manual als „nicht frozen" dokumentieren oder frozen setzen (nur wenn keine Mutation nötig).

### M-04 Backtest-Konstruktor-Beschreibung
- Kapitel: 18.
- Quelle: Manual „Entry-Fraktion ≤ 1", real nur `>0`-Check ohne Normalisierung (`backtest.py:71-73`).
- Lösung: Beschreibung auf reale Guard-Bedingung korrigieren.

### M-05 Governance-Codeblöcke/Standort
- Kapitel: 01.
- Quelle: `default_governance_config()` liegt in `governance.py:252`, nicht `config.py`; Codeblöcke `KillSwitch`/`OperationalModeGuard` lassen `reason`/`mode` aus.
- Lösung: Manual-Pfad korrigieren, Codeblöcke vollständig nachbilden.

### M-06 `MarketStateKind` Wert anzahl
- Kapitel: 09.
- Quelle: real 18 Werte, Manual „17".
- Lösung: Ziffer korrigieren.

### M-07 Liquidität: Sweep-Verschiebung & open_interest
- Kapitel: 10.
- Quelle: `_is_sweep` stützt `candles[-2]`; `open_interest` nur als Interpretations-String.
- Lösung: Formulierung präzisieren.

---

## LOW

### L-01 `_atr` ist toter Code
- Kapitel: 15 — trade_plan.py:59 wird nie von `build` aufgerufen.
- Lösung: entfernen oder verwenden.

### L-02 `max_scenarios`-Kommentar inkorrekt
- Kapitel: 11. Generator liest keinen `max_scenarios`.
- Lösung: Kommentar streichen oder Logik ergänzen.

### L-03 Doppelte Fallback-Szenario-IDs
- Kapitel: 11. Fallback-IDs „A"/„B" werden wiederverwendet.
- Lösung: eindeutige IDs.

### L-04 Acceptance-Testanzahl
- Kapitel: 26 — real 12 Tests, Manual sagt „13".
- Lösung: Zahl auf 12 korrigieren.

### L-05 „17/13"-Restzahlen, README „Inkrementell im Aufbau"
- Kapitel: README/09/26. Nach Phasenabschluss Status als „Verifiziert" setzen.

### L-06 Zweite Paper-Engine unerwähnt
- Kapitel: 20 — `src/paper/automation.py` (mit `test_paper_automation.py`) fehlt im Kapitel.
- Lösung: Sektion ergänzen oder in API verweisen.

---

## Bezug
Implementierungsgrad je Kapitel: siehe `VERIFICATION_REPORT.md`.

## [SPEC-Liste (korrekt markiert, kein Fehler)]
- eigene Liquiditäts-Engine, PortfolioState/Allokation, Shadow-Engine, Review-Engine.
- einheitliche Research-Engine.
- Trade/Candle-Schemas.

_Eindeutig bestimmte Fehler (mit Codestelle) sind vermerkt; Rest realisiert nur im Quellcode._