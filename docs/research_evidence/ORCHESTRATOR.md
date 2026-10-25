# Research-Evidenz-Ablauf (#144)

`src/research_evidence/orchestrator.py::ResearchOrchestrator` verbindet die gelieferten Bausteine #252–#257 zu
einem Lauf:

| Schritt | Baustein | Regel |
|---|---|---|
| Web-Quelle holen | `Crawl4AIProvider` (#254) | nur mit `TIM_RESEARCH_WEB_ENABLED=1`; URL-Richtlinie (#253) vor jedem Aufruf; Umleitung auf private oder nicht erlaubte Ziele wird verworfen |
| Ausweichen | Browser-Provider hinter `BrowserPolicy`/`BrowserBudget` (#257) | nur bei Transport-/Parse-/Serverfehlern, nie nach einer Richtlinien-Ablehnung; aus in CI und Produktion; Not-Aus wirkt sofort |
| Dokument | `StirlingPdfProcessor` (#255) | Ergebnis wird kanonische `Evidence` (#252) mit `parent_ids` = Prüfsumme der Originaldatei |
| Ergebnis | `validate_research_result` (#256) | angenommen nur, wenn jede Aussage Evidenz dieses Laufs zitiert |
| Telemetrie | je Werkzeugaufruf | `run_id`, Werkzeug, Provider, Domain, Start/Ende, ok/Fehlercode, Bytes, Ausweichgrund |

Teilausfälle werden im Lauf festgehalten und beschädigen bereits gesammelte Evidenz nicht. Inhalte von außen
bleiben Daten: Anweisungen in einer Seite ändern weder Richtlinie noch Ablauf.

Tests: `tests/test_research_evidence_orchestrator.py` (18 Fälle, ohne Netz).

Weiter offen in #144 (Entscheidungen bzw. Betrieb, nicht per Code in der Cloud):
Persistenz der Evidenz in PostgreSQL (Migration braucht Freigabe), Sidecar-Betrieb von Crawl4AI/Stirling,
Benchmark mit echtem Quellenkorpus, OpenAI-Werkzeugdefinitionen, ADR zur Einordnung der zehn Systeme.
