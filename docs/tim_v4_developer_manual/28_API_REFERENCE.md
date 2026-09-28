# TIM V4 Developer Manual — Kapitel 28

# API-Referenz (öffentliche Flächen)

Version: **0.1.0**
Status: **Konsistent für IST (aus Kapiteln 05–24)**
Verbindlichkeit: **Ja**

Dieses Kapitel fasst die öffentlich nutzbaren Schnittstellen der Module
zusammen. Detaillierte Signaturen stehen in den zugehörigen Kapiteln; hier
nur die konsolidierte Übersicht (Einstieg, nicht Ersatz).

## 1. Domain & Query

- `src/orderflow/metrics.py`: `OrderflowMetricsEngine.calculate`,
  `OrderflowMetric`, `OrderflowMetricsService` (async, `AggTradeReader`).
- `src/orderflow/observations.py`: `OrderflowObservation`,
  `OrderflowObservationEngine` (Kapitel 05/07).
- `src/orderflow_scenario/domain.py`: Domain-Typen/Statuswerte
  (`Mode`, `ScenarioType`, `MarketState`, …).

> Hinweis: `src/orderflow/input.py` existiert im IST **nicht**; es gibt dort
> keine Funktion `get_primitive_inputs` (siehe ARCHITECTURE_REVIEW, V5-02).

## 2. Engines (orderflow_scenario/engines)

| Modul | Einstieg |
|---|---|
| `data_quality.py` | `DataQualityGate` (+ `DataQualityInputs`); `DataQualityReport` liegt in `domain.py` |
| `market_state.py` | `MarketStateEngine`, `AuctionStateEngine` |
| `orderflow_interpretation.py` | `OrderflowInterpretationEngine` |
| `scenario_generator.py` | `ScenarioGenerator` |
| `confirmation.py` | `ConfirmationEngine` |
| `probability.py` | `ProbabilityEngine` |
| `decision.py` | `DecisionEngine` |
| `trade_plan.py` | `TradePlanBuilder` |
| `risk.py` | `RiskEngine` |

## 3. Governance & Steuerung

- `src/orderflow_scenario/governance.py`: `KillSwitch`,
  `GovernanceLimits`, `OperationalModeGuard`.
- `src/orderflow_scenario/audit.py`: `AuditBuilder`, `analysis_id_for`.

## 4. Daten/Adapters

- `src/orderflow_scenario/adapters/`: `base`, `generic`, `mmt_structured`,
  `mmt_screenshot` (Kapitel 05).

## 5. Ausführungs-/Verifikation

- `execution/paper.py`: `PaperExecutionJournal`.
- `backtest.py`: `ForwardOnlyReplay`, `ScenarioVerdict`.

## 6. Research

- `src/research/`, `src/research_ops/`: `audit.py`, `quality.py`
  (ResearchAuditEngine etc., Kapitel 19).

## 7. Schema / Validierung

- `schemas/analysis_output_v1.json`, `schema_validation.py`.
  (`validate_analysis`, `load_reference_schema`).
  — Kapitel 24.

## 8. Aufrufkonventionen

- Deterministische IDs; deterministische Signatur/Digest (wo anwendbar).
- Diese Liste ist ein **Index**; Signaturdetails je Kapitel.

## 9. Offene Lücken

| Bereich | IST | SOLL |
|---|---|---|
| vollständige API-Dok | kapitelweise | zentrale API-Doku (OpenAPI-artig) [SPEZIFIKATION] |
| Schema für Trade/Candle | fehlt | neue Schemas (Kapitel 24) |

## 10. Roadmap [SPEZIFIKATION]

- Maschinenlesbare API-Beschreibung (OpenAPI).
- Konsolidierung der Einstiegspunkte (Facade) für alle Engines.

---

## Code Coverage (Phase 2)

```
VERIFIED .......... 72 %
NOT IMPLEMENTED ... 28 %
```

Befunde und Korrekturen: entfernt/nicht vorhanden — `get_primitive_inputs`
(`src/orderflow/input.py`), `compute_orderflow_metrics`, `OrderFlowMetric`
(real: `OrderflowMetric`), `DataQualityReport` in `data_quality.py`,
`MarketStateAnalyzer` (real: `MarketStateEngine`), `ScoreEngine` (real:
`ProbabilityEngine`). Alle anderen Einstiegspunkte verifiziert (Datei+Klasse).

---

*Ende Kapitel 28.*