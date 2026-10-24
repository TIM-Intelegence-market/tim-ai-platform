# Paketinventar `src/` (T13 des gemeinsamen Verbesserungsplans)

Stand 22.10.2026, platform-main `e985971`. Erzeugt aus einer statischen Importanalyse (AST) über `main.py`, alle
Skripte in `scripts/` und `tools/` sowie Module mit `__main__`-Einstieg. Zeilen inklusive Kommentare und Leerzeilen.

**Lesart der Spalten.** *live*: von `main.py` (der Runtime) erreichbar. *werkzeug*: nur über ein Skript oder einen
eigenen Einstieg erreichbar. *unerreicht*: von keinem Einstiegspunkt aus importiert; solche Module werden nur von
Tests geladen. *in ops/CI*: ein Skript dieses Pakets oder das Paket selbst wird in `ops/`, `launchd/` oder
`.github/workflows` genannt.

**Grenzen.** Dynamische Importe (`importlib`, Strings in Konfigurationen) und Aufrufe von außerhalb des Repos
(Mac-Worker, Codex-Werkzeuge) sieht die Analyse nicht. „UNERREICHT“ heißt deshalb *Kandidat für die Prüfung*, nicht
„löschen“. Für jedes Paket entscheidet ein Verantwortlicher nach Nutzungsnachweis (Schritt 5 in T13).

| Paket | Zeilen | live | werkzeug | unerreicht | Skripte (Auswahl) | in ops/CI | Einstufung | Verantwortlicher |
|---|---:|---:|---:|---:|---|---|---|---|
| `tim_incident` | 9320 | 0 | 9320 | 0 | tim_checkup.py | ja | WERKZEUG | offen |
| `orderflow_scenario` | 5769 | 0 | 4891 | 878 | openmarket_api_proof.py |  | WERKZEUG (teils unerreicht) | offen |
| `research_lab` | 5491 | 0 | 5189 | 302 | fred_store_key.py,research_lab_alfred_ingest.py,research_lab_cpi_volatility.py,research_lab_fetch.py… |  | WERKZEUG (teils unerreicht) | offen |
| `dashboard` | 4528 | 4527 | 0 | 1 | live_readonly_validate.py,research_case_browser_e2e.py |  | LIVE | offen |
| `data_ingestion` | 3774 | 3071 | 693 | 10 | acceptance_check.py,apply_live_cutover.py,audit_historical_gap_closure.py,backfill_gaps.py… | ja | LIVE | offen |
| `tim_manager` | 3147 | 0 | 3147 | 0 | run_local_qwen_daemon.py | ja | WERKZEUG | offen |
| `bugfixer` | 2658 | 0 | 1892 | 766 | m09_p1_10_repair_proof.py,m09_p1_14_self_heal_proof.py,tim_monitoring_agent.py,verified_live_collection.py |  | WERKZEUG (teils unerreicht) | offen |
| `local_first` | 2556 | 0 | 2556 | 0 | run_local_qwen_build_queue.py,run_local_qwen_daemon.py,run_local_qwen_developer.py,run_mac_qwen_issue.py | ja | WERKZEUG | offen |
| `graph_mcp` | 2325 | 0 | 2325 | 0 | agent_infra_acceptance.py,agent_infra_long_context.py |  | WERKZEUG | offen |
| `task_governance` | 2203 | 0 | 2186 | 17 | tim_checkup.py | ja | WERKZEUG (teils unerreicht) | offen |
| `collection_reporting` | 1828 | 0 | 1409 | 419 | audit_collection_accounting.py,autonomous_collection_report.py,build_collection_report.py,m09_p1_10_repair_proof.py… |  | WERKZEUG (teils unerreicht) | offen |
| `control_portal` | 1753 | 0 | 1748 | 5 | run_tim_control_portal.py |  | WERKZEUG (teils unerreicht) | offen |
| `v2_completion` | 1729 | 0 | 1723 | 6 | mac_live_install.py,v2_backfill_candidate.py,v2_qualification_daily.py,v2_qualification_monitor.py… | ja | WERKZEUG (teils unerreicht) | offen |
| `task_engine` | 1639 | 0 | 1586 | 53 | m09_p1_10_repair_proof.py,m09_p1_14_self_heal_proof.py |  | WERKZEUG (teils unerreicht) | offen |
| `operational` | 1370 | 330 | 1036 | 4 | acceptance_check.py,operational_validation.py,tim_candle_backfill.py,tim_history_recovery.py… | ja | LIVE+WERKZEUG | offen |
| `knowledge` | 1268 | 0 | 1265 | 3 | broncx_discord_bot.py,goathub_discord_bot.py,passive_ingest.py | ja | WERKZEUG (teils unerreicht) | offen |
| `agents` | 1241 | 0 | 1206 | 35 | tim_monitoring_agent.py,tim_priority_agent.py,tim_review_agent.py | ja | WERKZEUG (teils unerreicht) | offen |
| `research` | 1172 | 1106 | 29 | 37 | audit_historical_gap_closure.py,backfill_gaps.py,classify_ingestion_gaps.py,demo_trader_report.py… | ja | LIVE | offen |
| `market_data` | 1047 | 0 | 1045 | 2 | openmarket_api_proof.py,openmarket_store_key.py |  | WERKZEUG (teils unerreicht) | offen |
| `agent_infra` | 915 | 0 | 915 | 0 | agent_infra_acceptance.py,agent_infra_long_context.py,tim_monitoring_agent.py,tim_priority_agent.py… | ja | WERKZEUG | offen |
| `obsidian_vault` | 787 | 0 | 781 | 6 | agent_infra_acceptance.py,agent_infra_long_context.py,tim_monitoring_agent.py |  | WERKZEUG (teils unerreicht) | offen |
| `tim_v2` | 777 | 0 | 0 | 777 |  |  | UNERREICHT | offen |
| `sources` | 729 | 0 | 726 | 3 | broncx_discord_bot.py,goathub_discord_bot.py,passive_ingest.py | ja | WERKZEUG (teils unerreicht) | offen |
| `repair_diagnosis` | 693 | 0 | 637 | 56 |  |  | WERKZEUG (teils unerreicht) | offen |
| `research_intelligence` | 670 | 0 | 669 | 1 |  |  | WERKZEUG (teils unerreicht) | offen |
| `server_readiness` | 660 | 0 | 0 | 660 |  |  | UNERREICHT | offen |
| `research_evidence` | 626 | 0 | 0 | 626 |  |  | UNERREICHT | offen |
| `v2_readiness` | 617 | 0 | 596 | 21 | binance_backfill_probe.py,research_lab_alfred_ingest.py,research_lab_cpi_volatility.py,research_lab_fetch.py… |  | WERKZEUG (teils unerreicht) | offen |
| `orchestration` | 453 | 0 | 453 | 0 | tim_orchestrator.py |  | WERKZEUG | offen |
| `database` | 441 | 440 | 0 | 1 | audit_historical_gap_closure.py,backfill_gaps.py,bench_outbox_worker.py,classify_ingestion_gaps.py… | ja | LIVE | offen |
| `repair_gates` | 433 | 0 | 169 | 264 | m09_p1_10_repair_proof.py,m09_p1_14_self_heal_proof.py |  | WERKZEUG (teils unerreicht) | offen |
| `insights` | 418 | 418 | 0 | 0 | export_case.py,live_readonly_validate.py,research_case_browser_e2e.py,verify_case.py |  | LIVE | offen |
| `ops_mcp` | 353 | 0 | 353 | 0 |  |  | WERKZEUG | offen |
| `repair_observe` | 341 | 0 | 0 | 341 |  |  | UNERREICHT | offen |
| `research_ops` | 335 | 169 | 166 | 0 | export_case.py,live_readonly_validate.py,research_case_browser_e2e.py,research_infrastructure_review.py… |  | LIVE | offen |
| `options_gamma` | 334 | 0 | 0 | 334 |  |  | UNERREICHT | offen |
| `orderflow` | 290 | 283 | 0 | 7 | audit_historical_gap_closure.py,backfill_gaps.py,classify_ingestion_gaps.py,export_case.py… | ja | LIVE | offen |
| `collaboration` | 288 | 0 | 0 | 288 |  |  | UNERREICHT | offen |
| `analysis` | 272 | 94 | 161 | 17 | audit_historical_gap_closure.py,backfill_gaps.py,classify_ingestion_gaps.py,materialize_research_cases.py… | ja | LIVE+WERKZEUG | offen |
| `repair_workflow` | 270 | 0 | 0 | 270 |  |  | UNERREICHT | offen |
| `paper` | 261 | 0 | 258 | 3 | demo_trader_report.py |  | WERKZEUG (teils unerreicht) | offen |
| `repair_repro` | 225 | 0 | 0 | 225 |  |  | UNERREICHT | offen |
| `repair_registry` | 217 | 0 | 96 | 121 |  |  | WERKZEUG (teils unerreicht) | offen |
| `acceptance` | 214 | 0 | 211 | 3 | acceptance_check.py |  | WERKZEUG (teils unerreicht) | offen |
| `analytics` | 154 | 149 | 0 | 5 | live_readonly_validate.py,research_case_browser_e2e.py |  | LIVE | offen |
| `llm` | 135 | 134 | 0 | 1 | live_readonly_validate.py,research_case_browser_e2e.py,run_local_qwen_build_queue.py,run_local_qwen_daemon.py… | ja | LIVE | offen |
| `quality` | 133 | 0 | 130 | 3 | data_quality_report.py,research_lab_alfred_ingest.py,research_lab_cpi_volatility.py |  | WERKZEUG (teils unerreicht) | offen |
| `assistant` | 129 | 0 | 37 | 92 | operational_validation.py,run_benchmarks.py |  | WERKZEUG (teils unerreicht) | offen |
| `models` | 106 | 103 | 0 | 3 | acceptance_check.py,apply_live_cutover.py,audit_historical_gap_closure.py,backfill_gaps.py… | ja | LIVE | offen |
| `news` | 66 | 0 | 63 | 3 | passive_ingest.py |  | WERKZEUG (teils unerreicht) | offen |
| `observation` | 53 | 50 | 0 | 3 | audit_historical_gap_closure.py,backfill_gaps.py,classify_ingestion_gaps.py,materialize_research_cases.py… | ja | LIVE | offen |
| `memory` | 53 | 50 | 0 | 3 |  |  | LIVE | offen |
| `repair_recipes` | 51 | 0 | 0 | 51 |  |  | UNERREICHT | offen |
| `longterm` | 45 | 0 | 0 | 45 |  |  | UNERREICHT | offen |
| `benchmark` | 24 | 0 | 21 | 3 | operational_validation.py,run_benchmarks.py |  | WERKZEUG (teils unerreicht) | offen |

**Summe:** 67386 Zeilen, davon 10924 live (16 %), 49688 Werkzeug (73 %), 6774 unerreicht (10 %).

## Prüfaufträge aus der Tabelle

1. **UNERREICHT, ganzes Paket:** `tim_v2`, `server_readiness`, `research_evidence`, `options_gamma` (gerade mit #360 gemergt,
   noch ohne Einstieg), `collaboration`, `repair_workflow`, `repair_repro`, `repair_observe`, `repair_recipes`, `longterm`.
   Für jedes: Nutzungsnachweis außerhalb des Repos suchen (Worker, Codex), sonst per Tag sichern und aus `platform-main`
   nehmen. Die Tests dieser Pakete gehen mit.
2. **Vermeintliche Doppelungen** (T13 Schritt 2, erst Verantwortlichkeiten vergleichen, dann zusammenlegen):
   Reparatur: `bugfixer` (1 892 Zeilen Werkzeug) neben `repair_diagnosis`, `repair_gates`, `repair_observe`, `repair_repro`,
   `repair_registry`, `repair_recipes`, `repair_workflow` (zusammen 2 230 Zeilen, davon 1 328 unerreicht).
   Aufgaben: `task_engine`, `task_governance`, `tim_manager`. Readiness: `v2_readiness`, `v2_completion`, `server_readiness`.
   Research: `research`, `research_lab`, `research_evidence`, `research_intelligence`, `research_ops`.
3. **Größtes Paket** `tim_incident` (9 320 Zeilen) hängt an genau einem Skript (`tim_checkup.py`, Server-Checkup). Der Server
   ist seit 20.10. nicht im Betrieb. Entscheiden, ob das Paket bis zur Rückkehr des Servers ruht.
4. **Live-Kern** (11 000 Zeilen): `dashboard`, `data_ingestion`, `database`, `research`, `insights`, `operational` (Teil),
   `orderflow`, `analytics`, `llm`, `models`, `observation`, `memory`, `analysis` (Teil), `research_ops` (Teil).
   Nur hierfür gilt die Abdeckungszahl aus T10.

## Paket-Moratorium (Vorschlag für `CI.md`)

Bis V2.8 kein neues Top-Level-Paket unter `src/` ohne Eintrag in dieser Tabelle mit Verantwortlichem, Einstufung und
Bezug zu einem Schritt V1 bis V10 des Gesamtplans. Das PR-Gate kann das prüfen (neue Verzeichnisse unter `src/`).
