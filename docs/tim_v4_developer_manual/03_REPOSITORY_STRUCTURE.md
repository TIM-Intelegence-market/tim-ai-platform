# TIM V4 Developer Manual — Kapitel 03

# Repository-Struktur

Version: **0.1.0**
Status: **Konsistent (reflektiert den tatsächlichen Git-Stand)**
Verbindlichkeit: **Ja**

Dieses Kapitel dokumentiert die autoritative Ordnung des TIM-Repositorys:
Top-Level-Verzeichnisse, ihre Verantwortung und die Pfadregeln für neue
Module. Es ist die Referenz für die Entwicklung und die Basis für alle
Fachkapitel.

## 1. Ziel

Eine eindeutige, ehrliche Karte des Repositorys liefern, damit jede Änderung
an der richtigen Stelle erfolgt und Verantwortungen nicht vermischt werden.

## 2. Top-Level-Ordnung

| Pfad | Verantwortung | Status |
|---|---|---|
| `/` (Root) | Konstitution, Master Prompts, Bände als Markdown | Autoritativ |
| `/src` | Produktionscode (Python-Pakete) | Autoritativ |
| `/tests` | Testcode einschließlich V2-Suite | Autoritativ |
| `/docs` | Dokumentation (inkl. Governance, Fachdokumente) | Autoritativ |
| `/scripts` | Hilfsskripte und Betriebs-Commands | Operator |
| `/schemas` | Schemas (vertragsstützend) | Autoritativ |
| `/artifacts` | generierte Artefakte (Berichte, Reports) | Generiert |
| `/.venv*` | virtuelle Umgebungen | Nicht versioniert |

> Hinweis (Phase 2): `/tools` existiert im IST **nicht**; entfernt.

Konstitution im Root: `TIM_CONSTITUTION.md`, `TIM_ENGINEERING_GOVERNANCE.md`,
`TIM_SYSTEM_ARCHITECTURE.md` sowie weitere Bände und Master-Prompt-Dateien.

## 3. Kernverzeichnisse unter `src/`

| Verzeichnis | Kernverantwortung |
|---|---|
| `src/data_ingestion/` | Datenbeschaffung (WebSockets, Binance, Durable Ingestion) |
| `src/database/` | Persistenz, Schema, PostgreSQL |
| `src/orderflow/` | Orderflow-Metriken und -Beobachtung |
| `src/orderflow_scenario/` | Orderflow-Szenario- und Trade-Decision-Pipeline |
| `src/observation/` | Marktbeobachtung, Pattern Detection |
| `src/research/`, `src/research_ops/` | Research-Workflows, Replay, Provenienz |
| `src/knowledge/` | Knowledge Objects, Graph, Zitationen |
| `src/llm/` | Modell-Routing, Modelle |
| `src/analysis/`, `src/analytics/` | Feature- und Analyse-Berechnung |
| `src/tim_manager/` | Agenten-Ordnung, TimManager-Kern |
| `src/tim_v2/` | V2-Registry-Plattform (Dataset, Feature, Evaluation, ...) |
| `src/v2_completion/`, `src/v2_readiness/` | V2-Completion-Status, Readiness |
| `src/operational/` | Logging, Health, Audit |
| `src/memory/`, `src/models/`, `src/news/` | Speicher, Modelle, News-Intelligenz |
| `src/paper/` | Paper-Ausführung (Execution) |
| `src/benchmark/`, `src/assistant/`, `src/dashboard/`, `src/acceptance` | Werkzeuge, UI, Abnahme |

Hinweis: Die Auflistung beschreibt die tatsächliche Präsenz im Git-Stand.
Inhaltliche Details je Plattform folgen in den Fachkapiteln 05–23.

## 4. Wichtige Testdateien (Auswahl)

- `tests/test_*v2.py`: V2-Registry- und Completion-Konzepte.
- `tests/test_orderflow_*.py`: Orderflow-Einheiten.
- `tests/test_orderflow_scenario/`: Szenario-Pipeline-Tests.
- `tests/test_acceptance.py`, `tests/test_repository_*.py`: Governance.

Benennungskonvention: `test_<scope>[_v2|_scenario].py`.

## 5. Wichtige Dokumentation

- `docs/governance/*`: Band-Übernahmen und Adoptionen.
- `docs/orderflow_scenario/`: Orderflow-Szenario-Konzept.
- `docs/tim_v4_developer_manual/`: dieses Handbuch.

## 6. Pfadregel für neue Module

- Fachliche Domänen: `src/<domaene>/` als eigenständiges, getestetes Paket.
- Tests: `tests/test_<domaene>.py` oder `tests/<domaene>/`.
- Dokumentation: `docs/<domaene>/`.
- Schemas: `src/<domaene>/schemas/` oder `/schemas`.
- Artefakte: `artifacts/<domaene>/`.

## 7. Vermischungs-Verbot

- Keine Artefakte in `src` oder `docs`.
- Keine Dokumentation in `src`.
- Keine Testdaten in Produktionscode.
- Secrets niemals im Repo (siehe Kapitel 23).

## 8. Akzeptanzkriterien

- [ ] Strukturübersicht deckt die tatsächliche Git-Präsenz ab.
- [ ] Jede Aussage referenziert existierende Verzeichnisse.
- [ ] Keine erfundenen oder nur geplanten Pfade.

---

*Ende Kapitel 03.*