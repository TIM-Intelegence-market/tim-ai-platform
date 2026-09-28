# TIM — ARCHITECTURE_REVIEW.md

Phase: Phase-2-Architekturprüfung (statisch, gegen den realen Nutzer- und
Importbaum). Schwerpunkt: `src/orderflow_scenario`, `src/orderflow`,
`src/research_ops`, `src/paper`, Schemas, `tests`.

---

## Zusammenfassung

- **Import-Integrität:** alle Module der Kern-Pakete importieren fehlerfrei
  (keine zirkulären Abhängigkeiten, keine broken imports).
- **Schemas:** keine Duplikate im Szenario-Paket; einzige Quelle ist
  `analysis_output_v1.json`.
- **Doppelte Logik:** `src/paper/automation.py` vs. `execution/paper.py` —
  zwei parallele Paper-Implementierungen.
- **Tote Klassen/Module:** Klassen in `governance.py` (KillSwitch,
  GovernanceLimits, OperationalModeGuard, OrderflowScenarioGovernance,
  default_governance_config) und das gesamte Modul `backtest.py` werden
  nirgends importiert oder instanziiert.
- **Ungenutzte Tests:** `tests/test_orderflow_scenario/` ist leer.

---

## 1. Import-Integrität

Durchlauf: alle Module in `orderflow_scenario` und `orderflow` importierbar.
- **Ergebnis:** fehlerfrei (keine zirkulären Abhängigkeiten, keine broken imports).
- Bemerkung: Einstieg `cli.py` ist nirgends als Konsolen-Einstieg verankert
  (kein pyproject-Eintrag, kein Skript in `scripts/`); nur via
  `python -m orderflow_scenario.cli` erreichbar (partiell unverankert).

## 2. Ungenutzte Klassen / tote Dateien

| Modul | Klassen/Funktionen | Verwendung |
|---|---|---|
| `governance.py` | `KillSwitch`, `GovernanceLimits`, `OperationalModeGuard`, `OrderflowScenarioGovernance`, `default_governance_config` | **0 Importe** außerhalb der Datei — wird nicht angewendet |
| `backtest.py` | `ReplayBar`, `ScenarioVerdict`, `CalibrationResult`, `ForwardOnlyReplay`, `compute_calibration` | **0 Importe** in src/tests — ungenutzt |
| `engines/trade_plan.py` | `_atr` | toter Code (wird von `build` nie aufgerufen) |

## 3. Doppelte Logik

- **Paper-Gebühren/Slippage:** `execution/paper.py` (fee_bps=6, slippage_bps=2,
  Decimal/10000) und `src/paper/automation.py` (fee_bps=6.0, slippage_bps=2.0,
  *2/10000) — zwei separaten Paper-Implementierungen mit konsistenten Fees, aber
  getrennten Typen → Redundanz, Drift-Risiko.

## 4. Doppelte/inkonsistente Schemas

- `analysis_output_v1.json` ist das einzige Schema im Szenario-Paket. ✓
- Andere Schemas (`data_quality_report_v1.json`, `tim_v2/…`) liegen in anderen
  Zweigen — kein Konflikt. ✓
- Schema-Enum `mode` entspricht `domain.Mode` — konsistent. ✓
- Schema `data_quality.status` (PASS/PARTIAL/INSUFFICIENT_DATA) entspricht
  `domain.DataQualityReport` — konsistent. ✓

## 5. Inkonsistente Enums/Typen

| Befund | Detail |
|---|---|
| `EntryModel.RETEST` fehlt | `scenario_generator.py:161` referenziert ihn; Enum enthält nur `LIMIT_RETEST`/`FAILED_RETEST` → latenter `AttributeError` (→ V5-01) |
| `MarketStateKind`-Anzahl | 18 real (Manual "17") (→ V5-07) |
| `MarketState`-Alias | `pipeline.py` re-aliased `.domain` — konsistent |
| `provenance` | nur `Observation`, nicht Trade/Candle (→ V5-04) |

## 6. Ungenutzte Tests

- `tests/test_orderflow_scenario/` ist **leer** → Szenario-Engines ungetestet.
- `tests/test_paper_automation.py` testet `src/paper/automation.py` (nicht das
  Journal) — nicht "ungenutzt", aber Lose-Kopplung zu Kapitel 20.

## 7. Nicht referenzierte Module

- `governance.py`, `backtest.py` (siehe §2): kein einziger Import im Code.

## 8. Fehlerhafte Imports

- **Keine** gefunden (alle Module importierbar).

## 9. Technische Schulden

- Zwei Paper-Engines (Duplikation) → Konsolidierung.
- Toter Governance-Code ohne Anbindung (Schutzschicht wird nicht genutzt;
  die Pipeline nutzt nur Bool-Flags `kill_switch_enabled`).
- Systemarchitektur-Doku nennt Pfade ohne Quellexistenz
  (`tools/`, `src/strategy/`, `src/backtest/`).

---

## Empfohlene Maßnahmen

1. **Hoch:** `EntryModel.RETEST` → `LIMIT_RETEST` (Risikofehler).
2. **Hoch:** API-Referenz an reale Namen anpassen (Kapitel 28).
3. **Mittel:** Paper-Duplikation zusammenführen.
4. **Mittel:** `governance.py` in die Pipeline integrieren (Schutzschicht statt
   nur Flags) oder als [SPEC] kennzeichnen.
5. **Mittel:** `backtest.py` ins Replay-/Backtest-Flow integrieren oder als
   eigenständige Teil-Doku führen.
6. **Mittel:** Systemarchitektur-Pfade an reale Struktur angleichen.
7. **Gering:** `_atr` entfernen oder binden; `max_scenarios`-Kommentar korrigieren.

---

## Begleitdokumente
`VERIFICATION_REPORT.md` · `IMPLEMENTATION_GAP.md` · `ROADMAP_V5.md`