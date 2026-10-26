# Paketinventar `src/` (T13 des gemeinsamen Verbesserungsplans)

Stand 22.10.2026, platform-main `e985971`; Entscheidungen je Paket vom 25.10.2026 (siehe unten). Erzeugt aus einer statischen Importanalyse (AST) über `main.py`, alle
Skripte in `scripts/` und `tools/` sowie Module mit `__main__`-Einstieg. Zeilen inklusive Kommentare und Leerzeilen.

**Lesart der Spalten.** *live*: von `main.py` (der Runtime) erreichbar. *werkzeug*: nur über ein Skript oder einen
eigenen Einstieg erreichbar. *unerreicht*: von keinem Einstiegspunkt aus importiert; solche Module werden nur von
Tests geladen. *in ops/CI*: ein Skript dieses Pakets oder das Paket selbst wird in `ops/`, `launchd/` oder
`.github/workflows` genannt.

**Grenzen.** Dynamische Importe (`importlib`, Strings in Konfigurationen) und Aufrufe von außerhalb des Repos
(Mac-Worker, Codex-Werkzeuge) sieht die Analyse nicht. „UNERREICHT“ heißt deshalb *Kandidat für die Prüfung*, nicht
„löschen“. Für jedes Paket entscheidet ein Verantwortlicher nach Nutzungsnachweis (Schritt 5 in T13).

| Paket | Zeilen | live | werkzeug | unerreicht | Skripte (Auswahl) | in ops/CI | Einstufung | Entscheid 25.10.2026 / Verantwortlicher |
|---|---:|---:|---:|---:|---|---|---|---|
| `tim_incident` | 9320 | 0 | 9320 | 0 | tim_checkup.py | ja | WERKZEUG | RUHEND bis der Server zurück ist (Uzi 20.10.: Server vorerst raus); kein Umbau, keine neuen Tests; Uzi |
| `orderflow_scenario` | 5769 | 0 | 4891 | 878 | openmarket_api_proof.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `research_lab` | 5491 | 0 | 5189 | 302 | fred_store_key.py,research_lab_alfred_ingest.py,research_lab_cpi_volatility.py,research_lab_fetch.py… |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `dashboard` | 4528 | 4527 | 0 | 1 | live_readonly_validate.py,research_case_browser_e2e.py |  | LIVE | Betrieb (Uzi), Pflege Claude |
| `data_ingestion` | 3774 | 3071 | 693 | 10 | acceptance_check.py,apply_live_cutover.py,audit_historical_gap_closure.py,backfill_gaps.py… | ja | LIVE | Betrieb (Uzi), Pflege Claude |
| `tim_manager` | 3147 | 0 | 3147 | 0 | run_local_qwen_daemon.py | ja | WERKZEUG | Claude (in ops/CI genutzt) |
| `bugfixer` | 2658 | 0 | 1892 | 766 | m09_p1_10_repair_proof.py,m09_p1_14_self_heal_proof.py,tim_monitoring_agent.py,verified_live_collection.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `local_first` | 2556 | 0 | 2556 | 0 | run_local_qwen_build_queue.py,run_local_qwen_daemon.py,run_local_qwen_developer.py,run_mac_qwen_issue.py | ja | WERKZEUG | Claude (in ops/CI genutzt) |
| `graph_mcp` | 2325 | 0 | 2325 | 0 | agent_infra_acceptance.py,agent_infra_long_context.py |  | WERKZEUG | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `task_governance` | 2203 | 0 | 2186 | 17 | tim_checkup.py | ja | WERKZEUG (teils unerreicht) | Claude (in ops/CI genutzt) |
| `collection_reporting` | 1828 | 0 | 1409 | 419 | audit_collection_accounting.py,autonomous_collection_report.py,build_collection_report.py,m09_p1_10_repair_proof.py… |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `control_portal` | 1753 | 0 | 1748 | 5 | run_tim_control_portal.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `v2_completion` | 1729 | 0 | 1723 | 6 | mac_live_install.py,v2_backfill_candidate.py,v2_qualification_daily.py,v2_qualification_monitor.py… | ja | WERKZEUG (teils unerreicht) | Claude (in ops/CI genutzt) |
| `task_engine` | 1639 | 0 | 1586 | 53 | m09_p1_10_repair_proof.py,m09_p1_14_self_heal_proof.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `operational` | 1370 | 330 | 1036 | 4 | acceptance_check.py,operational_validation.py,tim_candle_backfill.py,tim_history_recovery.py… | ja | LIVE+WERKZEUG | Betrieb (Uzi), Pflege Claude |
| `knowledge` | 1268 | 0 | 1265 | 3 | broncx_discord_bot.py,goathub_discord_bot.py,passive_ingest.py | ja | WERKZEUG (teils unerreicht) | Claude (in ops/CI genutzt) |
| `agents` | 1241 | 0 | 1206 | 35 | tim_monitoring_agent.py,tim_priority_agent.py,tim_review_agent.py | ja | WERKZEUG (teils unerreicht) | Claude (in ops/CI genutzt) |
| `research` | 1172 | 1106 | 29 | 37 | audit_historical_gap_closure.py,backfill_gaps.py,classify_ingestion_gaps.py,demo_trader_report.py… | ja | LIVE | Betrieb (Uzi), Pflege Claude |
| `market_data` | 1047 | 0 | 1045 | 2 | openmarket_api_proof.py,openmarket_store_key.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `agent_infra` | 915 | 0 | 915 | 0 | agent_infra_acceptance.py,agent_infra_long_context.py,tim_monitoring_agent.py,tim_priority_agent.py… | ja | WERKZEUG | Claude (in ops/CI genutzt) |
| `obsidian_vault` | 787 | 0 | 781 | 6 | agent_infra_acceptance.py,agent_infra_long_context.py,tim_monitoring_agent.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `tim_v2` | 777 | 0 | 0 | 777 |  |  | UNERREICHT | BEHALTEN als Entwurf (V2-Kern laut `docs/tim_v2/architecture.md`), Frist 30.11.: Einstieg oder Archiv; Uzi |
| `sources` | 729 | 0 | 726 | 3 | broncx_discord_bot.py,goathub_discord_bot.py,passive_ingest.py | ja | WERKZEUG (teils unerreicht) | Claude (in ops/CI genutzt) |
| `repair_diagnosis` | 693 | 0 | 637 | 56 |  |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `research_intelligence` | 670 | 0 | 669 | 1 |  |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `server_readiness` | 660 | 0 | 0 | 660 |  |  | UNERREICHT | ARCHIVIERT 26.10.2026: mit Tests aus `platform-main` entfernt, Stand 06c8bc2 im Zweig `archiv/unerreichte-pakete-2026-10-26`; Claude |
| `research_evidence` | 626 | 0 | 0 | 626 |  |  | UNERREICHT | ARCHIVIERT 26.10.2026: mit Tests aus `platform-main` entfernt, Stand 06c8bc2 im Zweig `archiv/unerreichte-pakete-2026-10-26`; Claude |
| `v2_readiness` | 617 | 0 | 596 | 21 | binance_backfill_probe.py,research_lab_alfred_ingest.py,research_lab_cpi_volatility.py,research_lab_fetch.py… |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `orchestration` | 453 | 0 | 453 | 0 | tim_orchestrator.py |  | WERKZEUG | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `database` | 441 | 440 | 0 | 1 | audit_historical_gap_closure.py,backfill_gaps.py,bench_outbox_worker.py,classify_ingestion_gaps.py… | ja | LIVE | Betrieb (Uzi), Pflege Claude |
| `repair_gates` | 433 | 0 | 169 | 264 | m09_p1_10_repair_proof.py,m09_p1_14_self_heal_proof.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `insights` | 418 | 418 | 0 | 0 | export_case.py,live_readonly_validate.py,research_case_browser_e2e.py,verify_case.py |  | LIVE | Betrieb (Uzi), Pflege Claude |
| `ops_mcp` | 353 | 0 | 353 | 0 |  |  | WERKZEUG | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `repair_observe` | 341 | 0 | 0 | 341 |  |  | UNERREICHT | ARCHIVIERT 26.10.2026: mit Tests aus `platform-main` entfernt, Stand 06c8bc2 im Zweig `archiv/unerreichte-pakete-2026-10-26`; Claude |
| `research_ops` | 335 | 169 | 166 | 0 | export_case.py,live_readonly_validate.py,research_case_browser_e2e.py,research_infrastructure_review.py… |  | LIVE | Betrieb (Uzi), Pflege Claude |
| `options_gamma` | 334 | 0 | 0 | 334 |  |  | UNERREICHT | BEHALTEN mit Frist 30.11. (gemergt 21.10. mit #360, Einstieg fehlt): Einstieg oder Archiv; Claude |
| `orderflow` | 290 | 283 | 0 | 7 | audit_historical_gap_closure.py,backfill_gaps.py,classify_ingestion_gaps.py,export_case.py… | ja | LIVE | Betrieb (Uzi), Pflege Claude |
| `collaboration` | 288 | 0 | 0 | 288 |  |  | UNERREICHT | ARCHIVIERT 26.10.2026: mit Tests aus `platform-main` entfernt, Stand 06c8bc2 im Zweig `archiv/unerreichte-pakete-2026-10-26`; Claude |
| `analysis` | 272 | 94 | 161 | 17 | audit_historical_gap_closure.py,backfill_gaps.py,classify_ingestion_gaps.py,materialize_research_cases.py… | ja | LIVE+WERKZEUG | Betrieb (Uzi), Pflege Claude |
| `repair_workflow` | 270 | 0 | 0 | 270 |  |  | UNERREICHT | ARCHIVIERT 26.10.2026: mit Tests aus `platform-main` entfernt, Stand 06c8bc2 im Zweig `archiv/unerreichte-pakete-2026-10-26`; Claude |
| `paper` | 261 | 0 | 258 | 3 | demo_trader_report.py |  | WERKZEUG (teils unerreicht) | WERKZEUG; Altcode `demo_trader_v1.py` + `scripts/demo_trader_report.py` + Tests + `config/paper_demo.json` am 26.10.2026 entfernt (A23, Grün-Plan C2), Stand im Zweig `archiv/unerreichte-pakete-2026-10-26`; `automation.py` bleibt; Claude |
| `repair_repro` | 225 | 0 | 0 | 225 |  |  | UNERREICHT | BEHALTEN (Korrektur 26.10.2026): `src/repair_gates/integrity.py` importiert `repair_repro.guards`, und `repair_gates` hängt an `task_engine/fix_first.py`; bleibt, solange `repair_gates` bleibt (Frist 30.11.); Claude |
| `repair_registry` | 217 | 0 | 96 | 121 |  |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `acceptance` | 214 | 0 | 211 | 3 | acceptance_check.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `analytics` | 154 | 149 | 0 | 5 | live_readonly_validate.py,research_case_browser_e2e.py |  | LIVE | Betrieb (Uzi), Pflege Claude |
| `llm` | 135 | 134 | 0 | 1 | live_readonly_validate.py,research_case_browser_e2e.py,run_local_qwen_build_queue.py,run_local_qwen_daemon.py… | ja | LIVE | Betrieb (Uzi), Pflege Claude |
| `quality` | 133 | 0 | 130 | 3 | data_quality_report.py,research_lab_alfred_ingest.py,research_lab_cpi_volatility.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `assistant` | 129 | 0 | 37 | 92 | operational_validation.py,run_benchmarks.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `models` | 106 | 103 | 0 | 3 | acceptance_check.py,apply_live_cutover.py,audit_historical_gap_closure.py,backfill_gaps.py… | ja | LIVE | Betrieb (Uzi), Pflege Claude |
| `news` | 66 | 0 | 63 | 3 | passive_ingest.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |
| `observation` | 53 | 50 | 0 | 3 | audit_historical_gap_closure.py,backfill_gaps.py,classify_ingestion_gaps.py,materialize_research_cases.py… | ja | LIVE | Betrieb (Uzi), Pflege Claude |
| `memory` | 53 | 50 | 0 | 3 |  |  | LIVE | Betrieb (Uzi), Pflege Claude |
| `repair_recipes` | 51 | 0 | 0 | 51 |  |  | UNERREICHT | ARCHIVIERT 26.10.2026: mit Tests aus `platform-main` entfernt, Stand 06c8bc2 im Zweig `archiv/unerreichte-pakete-2026-10-26`; Claude |
| `longterm` | 45 | 0 | 0 | 45 |  |  | UNERREICHT | ARCHIVIERT 26.10.2026: mit Tests aus `platform-main` entfernt, Stand 06c8bc2 im Zweig `archiv/unerreichte-pakete-2026-10-26`; Claude |
| `benchmark` | 24 | 0 | 21 | 3 | operational_validation.py,run_benchmarks.py |  | WERKZEUG (teils unerreicht) | Claude; Nutzung bis 30.11. nachweisen, sonst Archiv |

**Summe:** 67386 Zeilen, davon 10924 live (16 %), 49688 Werkzeug (73 %), 6774 unerreicht (10 %).

## Entscheidungen vom 25.10.2026 (Grün-Plan Paket I1)

Jedes Paket hat jetzt einen Entscheid und einen Verantwortlichen (letzte Spalte). Grundlage: Nutzungsnachweis im
Repo (Tests, Skripte, `ops/`, `.github/`), letzte Änderung je Paket und die Lage am 25.10. (Server raus, Kampagne
abgebrochen). Löschen und Taggen sind Ausführung und passieren erst auf Uzis Go in einem eigenen PR.

| Entscheid | Pakete | Begründung |
|---|---|---|
| ARCHIVIEREN (Tag, dann aus `platform-main`) | `server_readiness`, `research_evidence`, `collaboration`, `repair_workflow`, `repair_repro`, `repair_observe`, `repair_recipes`, `longterm` | Von keinem Einstieg erreichbar, keine Nennung in `docs/`, `ops/`, `scripts/`, `.github/`; letzte Änderung 16.10. (Sammelumzug), nur Tests laden sie. Zusammen 2 750 Zeilen plus Tests. |
| BEHALTEN mit Frist 30.11. | `tim_v2`, `options_gamma` | `tim_v2` ist der in `docs/tim_v2/architecture.md` beschriebene V2-Kern (Verträge, Domänen, Dienste), 10 Testdateien; `options_gamma` kam am 21.10. mit #360 und hat noch keinen Einstieg. Bis 30.11. Einstieg bauen oder archivieren. |
| RUHEND | `tim_incident` | 9 320 Zeilen für den Server-Checkup; der Server ist seit 20.10. nicht im Betrieb. Ruht ohne Umbau bis zur Rückkehr des Servers. |
| LIVE: Betrieb Uzi, Pflege Claude | `dashboard`, `data_ingestion`, `database`, `research`, `insights`, `operational`, `orderflow`, `analytics`, `llm`, `models`, `observation`, `memory`, `analysis`, `research_ops` | Kern der Runtime; Änderungen nur über PR mit voller Suite. |
| WERKZEUG in ops/CI: Claude | `tim_manager`, `local_first`, `task_governance`, `v2_completion`, `knowledge`, `agents`, `agent_infra`, `sources` | Werden von Mac-Agenten, Worker oder CI aufgerufen. |
| WERKZEUG ohne ops-Bezug: Nutzung bis 30.11. nachweisen | `orderflow_scenario`, `research_lab`, `bugfixer`, `graph_mcp`, `collection_reporting`, `control_portal`, `task_engine`, `market_data`, `obsidian_vault`, `repair_diagnosis`, `research_intelligence`, `v2_readiness`, `orchestration`, `repair_gates`, `ops_mcp`, `repair_registry`, `acceptance`, `quality`, `assistant`, `news`, `benchmark` | Erreichbar nur über Skripte oder MCP; `research_lab` ist durch S1/S4/S2 belegt, `graph_mcp`/`ops_mcp` durch die MCP-Clients auf dem Mac (#384). Für den Rest gilt: Aufruf im Protokoll oder Archiv. |
| WERKZEUG, Altcode entfernt | `paper` | `demo_trader_v1.py` + Skript + Tests + `config/paper_demo.json` am 26.10.2026 entfernt (A23); `automation.py` bleibt. |

Doppelungen aus Prüfauftrag 2 (Reparatur-, Aufgaben-, Readiness-, Research-Familien) werden nicht zusammengelegt,
solange die Pakete ruhen oder archiviert werden; ein Zusammenlegen ohne Nutzer wäre Arbeit ohne Nutzen.

## Ausführung vom 26.10.2026 (Uzis „weiter“, Grün-Plan I1 und C2)

- Sicherung des Stands vor dem Entfernen: Zweig `archiv/unerreichte-pakete-2026-10-26` auf `06c8bc2` (ein Tag ließ sich
  aus der Cloud nicht pushen, HTTP 403; der Zweig ist für Cloud-Threads nicht löschbar).
- Entfernt aus `platform-main`: `src/server_readiness`, `src/research_evidence`, `src/collaboration`, `src/repair_workflow`,
  `src/repair_observe`, `src/repair_recipes`, `src/longterm` samt Tests (`tests/test_<paket>_*.py`), dazu der DemoTrader-Altcode
  (`src/paper/demo_trader_v1.py`, `scripts/demo_trader_report.py`, `tests/test_demo_trader_v1.py`, `tests/test_paper_demo_setup.py`,
  `config/paper_demo.json`). Beschreibende Seiten unter `docs/research_evidence/`, `docs/bugfixer/repair_pipeline.md` und
  `docs/collaboration/` tragen einen Archiv-Hinweis; `README.md` nennt `src/longterm` nicht mehr.
- Korrektur gegenüber dem Entscheid vom 25.10.: `repair_repro` bleibt. Der Entscheid „von keinem Einstieg erreichbar“ war
  für dieses Paket falsch: `src/repair_gates/integrity.py` importiert `repair_repro.guards`, und `repair_gates` wird von
  `src/task_engine/fix_first.py` genutzt. Es folgt der Frist von `repair_gates` (30.11.).
- Die Zeilenzahlen in der Tabelle oben sind der Stand vom 25.10. und wurden nicht neu gemessen.

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
