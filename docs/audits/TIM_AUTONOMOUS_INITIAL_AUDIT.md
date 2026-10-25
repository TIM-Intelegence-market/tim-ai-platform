# TIM – Autonomer Erst-Audit (Phase A)

Stand: 25.10.2026, 01:40 Ortszeit (UTC+2). Nur gelesen, nichts geändert.
Grundlage: GitHub (Issues, PRs, Actions), Uzis Mac mini (lesende Befehle), Projekt-Threads, Projekt-Gedächtnis.
Uhrzeiten in Ortszeit. Jede Aussage ist mit Quelle versehen; nicht gemessene Punkte stehen als **nicht geprüft**.

## 1. Kurzfazit

| Bereich | Status | Kern |
|---|---|---|
| Laufzeit (Mac mini) | PASS | Runtime, Datenbank, Stream GRÜN; letzte Kerze 01:39, Datenalter 0 s |
| Deploy-Stand | PARTIAL | `~/TIM-live` auf `d4a164d`, **36 Commits hinter** `platform-main` (`98e8bce`) |
| Dashboard-Agent | IN_PROGRESS | Bis 01:38 `HOLD study_protected_paths`; Sperre per PR #410 aufgehoben, erstes Einspielen läuft im Thread "23.10. Dashboard-Aktualisierungs-Agent" |
| CI auf platform-main | PASS | Letzte 9 Läufe grün außer #398 (rot, später behoben); Lauf für #410 läuft |
| Wissenschaft | FAIL (ehrlich) | `historical_scientific.audit_status = FAIL`, R0–R4 ohne Edge, `NOT_READY_FOR_V2` |
| Gesperrt (unverändert) | OK | Echtgeld AUS, Auto-Merge AUS, V2-Kampagne ABGEBROCHEN, Modus OBSERVE |

## 2. Laufzeit-Realität

Produktion ist **der Mac mini**, nicht `tim-core-01`. Uzi 22.10.: „TIM soll 100 % auf dem Mac laufen“. Der Debian-Server ist vorerst raus (Server-Issues #75–#78, #88 bleiben offen, aber ruhend).

Gemessen 25.10. 01:39 auf dem Mac:

- `~/TIM-live` = `d4a164d` (Apache-Lizenz #401), Arbeitsbaum sauber. `deployment.json`: deployed 01:04, CI-Test dazu grün.
- `git rev-list HEAD..origin/platform-main` = 36 Commits, 52 Dateien. Darin u. a. #403–#410 (Level-Pläne, Kosten-Schwelle, Journal-Robustheit, timctl, Core vor CI).
- `~/TIM-trading-team` = `ddb8b90`.
- `/api/health`: `status GREEN`, `runtime/database/stream/dashboard GREEN`, `queue_depth 2` (Postgres-Outbox), `ollama_availability DISABLED_BY_POLICY`, `mode OBSERVE`, `core_status FROZEN`, `readiness_status NOT_READY_FOR_V2`, `validator_status RUNNING`, `audit_status FAIL`, `quality_status FAIL`.
- Ports: 8765 (Control Center) 200 in 0,04 s; `/neu` 200 in 0,23 s; `/journal` 200; 8767 (Worker-Dashboard) 200; 8769 (Chart-Vorschau) 200.
- launchd mit laufendem Prozess: `com.tim.runtime`, `validator`, `watchdog`, `caffeinate`, `mac-worker-dashboard`, `qwen-chat`, `local-qwen-worker`. Zeitgesteuert ohne Prozess (Exit 0): `trading-team`, `readiness-inputs`, `db-backup`, `dashboard-refresh`, `log-maintenance`, `history-recovery`, `server-health`, `dashboard-open`, `graph-refresh`.
- Backups: letzter Stand `tim_20261024T011503Z.dump` mit `.sha256`. Disk: 4 % belegt, 314 GiB frei.
- Last: Load Average 11,3 / 9,2 / 8,2 (hoch). Größter Verbraucher war ein kurzlebiger Python-Prozess (100 % CPU, 2 min alt, vermutlich eine Remote-Sitzung). **Ursache nicht geprüft.**
- Ollama: nur `qwen3.5:9b` geladen.

**Nicht geprüft:** Datenbank-Inhalt direkt (Lücken, Duplikate), Restore-Probe, Watchdog-Logs, Ingestion-Latenz über längere Zeit (letzte Messung 24.10. im Thread ChatGPT-Befunde: Outbox p99 13 s, max 92 s).

## 3. GitHub

Repo: `TIM-Intelegence-market/tim-ai-platform`, Basis `platform-main` = `98e8bce` (#410).

### 3.1 Offene PRs (4)

| PR | Titel | Autor | Bewertung |
|---|---|---|---|
| #393 | tim-ops `data_coverage` aus Postgres (#152 M3b) | Chris | READY zur Prüfung; seit 24.10. ruhig |
| #387 | BTC Research Engine V1.2: FOMC-Daten (Draft) | Chris | IN_PROGRESS bei Chris |
| #367 | CI auf getrennte GitHub-Runner (Codex) | Uzi/Codex | BLOCKED: gehostete Actions-Minuten aufgebraucht (seit 12.10.); Ersatz teils durch #405/#407 (Core vor CI) |
| #333 | Auto-Merge: ein geprüfter Merge-Pfad (Draft) | Uzi/Codex | BLOCKED by policy: Auto-Merge AUS ("vorerst nein") |

### 3.2 Offene Issues (25)

| Gruppe | Issues | Status |
|---|---|---|
| Plan-Journal mit Evidenz-Gate | #376 (status:verify) | IN_PROGRESS: Kern gemergt (#374, #378, #385, #405, #408, #409); Abnahme fehlt |
| Server/Debian, Qwen-Checkup | #75, #76, #77, #78, #88, #332, #334, #335 | BLOCKED: Server vorerst raus; #77/#78 warten auf Chris (Router/Tailscale) |
| M09 Selbstreparatur | #9, #13–#21 | BLOCKED/eingefroren; #13 inhaltlich fertig (status:verify) |
| MCP | #152 (Epic), #393 offen | IN_PROGRESS |
| Research-Werkzeuge | #144 (Epic) | NOT_STARTED in diesem Sinn, P3 |
| Governance-Rest #68 | #134 | NOT_STARTED, niedrige Schwere |
| Kollaboration | #67 | BLOCKED (observe-only) |
| Vision / Board | #82, #116 | Dach-Issues, kein Arbeitspaket |

### 3.3 CI

Workflows: `ci.yml` (Pflicht: test), `pr-gate.yml` (Pflicht), `tim-full-suite.yml`, `tim-priority-board.yml`, `auto-merge-controller.yml` (inaktiv). Ein Runner auf dem Mac mini. Läufe auf `platform-main` 24.10.: alle grün außer #398 (13:09, rot, mit #399 behoben). Lauf für `98e8bce` startete 01:37 und lief bei Abfrage noch.

## 4. Symbolkonfiguration und Multi-Coin

- `settings.symbol` kommt in **22 Dateien** unter `src/`, `tests/`, `scripts/` vor (gemessen heute auf `98e8bce`, deckt sich mit dem Befund-Doc vom 24.10.).
- Feste Vorgaben `symbol='BTCUSDT'` bzw. `symbol: str = SYMBOL` u. a. in `src/collection_reporting/campaign_writer.py`, `src/research_lab/data/archive.py`, `src/v2_readiness/backfill.py`, `src/v2_completion/sk_report.py`.
- Datenschicht (Aggregator, Outbox-Identität) ist schon nach Symbol getrennt; Runtime hört einen Stream. Multi-Coin ist damit ein Umbau, kein Schalter. Entwurf läuft im Thread „25.10. Multi-Coin-Architektur isoliert entwerfen“.

## 5. Forschung und Plan-Journal

- Research Lab R0–R4: kein Edge. Glückstest SPA auf R4: p ≈ 0,45 (#386). Arena: keine der 48 Varianten erfüllt K1.
- Plan-Journal live (`/api/plan-journal`, Schema `tim_plan_journal/2`, letzte Plankerze 01:30). Seit Log-Neustart 24.10. nur 2 geschlossene Trades, beide Stop (Thread ChatGPT-Befunde). Kernbefund: Kosten fressen enge Stops (0,15 % Stop, Kosten ≈ 1,2 R).
- Kosten-Schwelle 0,25 R (#408): gemergt, **noch nicht live** (Teil der 36 Commits).
- Strategieziel „Winrate ≥ 75 % mit positivem Netto-Erwartungswert“: **nicht begonnen, Ergebnis offen.** Der Thread „25.10. Strategie-Forschung mit Vorab-Registrierung“ ist dafür angelegt. Holdout 2025 ist verbraucht bzw. nur mit Uzis Wort nutzbar.

## 6. Lokale KI-Werkzeuge

| Werkzeug | Nachweis heute | Status |
|---|---|---|
| billion-context | `~/TIM-bili-test` vorhanden, `claude-bili` in `~/.zshrc` | DONE (Terminal), Funktionstest heute **nicht** wiederholt |
| Trader-Skills | 10 `trader-*` in `~/.claude/skills`, kein Broker-Skill | DONE; SEC-Absender fehlt noch (Uzi) |
| Ollama | nur `qwen3.5:9b`; TIM-Policy `DISABLED_BY_POLICY` | Worker nutzt es; TIM selbst nicht |
| Benchmarks lokaler Modelle | keine aktuellen Messungen | NOT_STARTED (keine Zahlen erfunden) |

## 7. Aufgabenregister

Priorität: P0 Datenintegrität/Sicherheit/Kosten/Risiko, P1 Forschung/Multi-Coin/Journal/Dashboard, P2 Performance/UX/Doku, P3 optional.

| ID | Ziel | P | Abhängig von | Thread / Branch | Status | Nächster Schritt |
|---|---|---|---|---|---|---|
| A01 | `~/TIM-live` auf `platform-main` bringen (36 Commits) | P0 | #410 | „23.10. Dashboard-Aktualisierungs-Agent“ | IN_PROGRESS | Agent spielt ein; danach Health und Seiten prüfen |
| A02 | Kosten-Schwelle 0,25 R live sehen | P0 | A01 | „24.10. ChatGPT-Befunde…“ | READY (gemergt #408) | Nach A01 `/journal` und `cost_check` prüfen |
| A03 | Kosten-Schwelle prüfen (LONG/SHORT, Gebühren, Slippage, Rundung, fehlende Stops) + Kostenstudie mit Varianten | P0 | – | „24.10. ChatGPT-Befunde…“ | NOT_STARTED | Tests gegen `src/dashboard/plan_cost_check.py`, Varianten nur als Forschung |
| A04 | Plan-Journal-Abnahme (#376) | P1 | A01 | – | IN_PROGRESS | Akzeptanzkriterien #376 gegen Live prüfen, dann Uzi |
| A05 | Analyse-Steckbrief je Zeitrahmen (Paket 2) | P1 | – | „24.10. TIM-Chart-Pläne…“ | IN_PROGRESS | Thread baut; Vorschau 8769 bleibt bis Abnahme |
| A06 | Abnahme `/neu` (5 Bereiche) und Umschalten (P4) | P1 | A01 | „24.10. Neues TIM-Dashboard“ | BLOCKED (Uzis Abnahme) | Abnahmebericht alt vs. neu, dann Entscheidung Uzi |
| A07 | Multi-Coin-Architektur entwerfen | P1 | – | „25.10. Multi-Coin-Architektur…“ | IN_PROGRESS | Entwurf, keine Live-Änderung |
| A08 | Strategie-Forschung (75 %-Ziel, vorab registriert) | P1 | A03 | „25.10. Strategie-Forschung…“ | IN_PROGRESS | Präregistrierung S4 (Entwurf, eigener Doku-PR unter `docs/research_lab/studien/`); hier nicht doppelt geführt; Ergebnis kann FAIL sein |
| A09 | S-K-Studie auswerten (T0 23.10. 15:55) | P1 | Laufzeit | – | IN_PROGRESS (läuft) | Wöchentlicher Zwischenstand, verblindet |
| A10 | Apache-Lizenz: Zustimmung Chris für alte Commits | P2 | Chris | „24.10. Apache-2.0-Lizenz“ | BLOCKED (Chris) | Chris um „ok“ auf GitHub bitten; Drittlizenzen-Liste fehlt noch |
| A11 | GoatHub-Bot direkt mit Treta einrichten | P3 | Treta, Uzi | „12.10. GoatHub-Kanal mitlesen“, #400 | BLOCKED (Treta) | Entwurf in `docs/knowledge/GOATHUB_DISCORD_FEED.md` an Treta geben; keine Nachrichten ohne Uzi |
| A12 | Trader-Skills: SEC-Absender, Nasdaq-Perp-Idee | P3 | Uzi | „24.10. Trader-Skill…“ | BLOCKED (Uzi) | Uzi beantwortet Bauplan-Frage |
| A13 | billion-context Funktionstest wiederholen | P3 | – | „24.10. Claude nach billion-context…“ | READY | Kurzer Probelauf im Terminal |
| A14 | Lokale Modelle messen (Code, Logs, Doku) | P2 | – | – | NOT_STARTED | Reproduzierbares Benchmark-Skript, keine Orders/Risiko aus LLM |
| A15 | PR #393 tim-ops `data_coverage` | P2 | Chris | – | READY (Review) | Review, Suite, dann Uzis „merge“ |
| A16 | PR #387 FOMC-Daten | P2 | Chris | – | IN_PROGRESS (Chris) | abwarten |
| A17 | PR #367 getrennte Runner | P2 | – | „25.10. Alle 11 Sichten…“ | READY (schließen) | Überholt durch #405/#407 (Runner entkoppelt); Schließen auf Uzis Wort (Grün-Plan P3) |
| A18 | PR #333 Auto-Merge | P3 | Policy | – | BLOCKED (Auto-Merge AUS) | ruhen lassen |
| A19 | Server-Issues #75–#78, #88, #332–#335 | P3 | Server zurück | – | RUHEND (Label `status:ruhend` seit 25.10.) | ruhen lassen bis Uzi den Server zurückholt |
| A20 | M09-Issues #9, #13–#21 | P3 | – | – | RUHEND (Label `status:ruhend` seit 25.10.) | #13 abnehmen und schließen (Uzi) |
| A21 | Hohe Mac-Last klären (Load 11) | P2 | – | – | NOT_STARTED | Prozessliste über 15 min messen |
| A22 | Offsite-Backup und Restore-Probe (Gutachten K1) | P0 | Uzi (Hardware/Ziel) | „25.10. Alle 11 Sichten…“ (B1–B3) | BLOCKED (Uzi: Ziel) | Ziel klären (externe Platte oder zweiter Rechner), dann Skript und Restore-Probe |
| A23 | DemoTrader-Altcode entfernen | P3 | Uzi (Go) | „25.10. Alle 11 Sichten…“ (C2) | READY | kleiner PR, nur mit Uzis Go; Umfang in `docs/PAKETINVENTAR.md` (`paper`) |
| A24 | Qwen-Chat auf dem Mac | P3 | Uzi | „22.10. Qwen-Chat…“ | BLOCKED (Uzi) | Frage im Thread offen |
| A25 | Hardware-Ausbau GPUs | P3 | Uzi | „21.10. Hardware-Ausbau…“ | BLOCKED (Uzi) | Entscheidung offen |

> **Nachtrag 25.10.2026 (Grün-Plan P1):** A17, A19, A20, A22, A23 nachgeführt; neue Pakete des Grün-Plans (H1, H2, T1, T3, F1, S1, P2) stehen in `docs/audits/GRUEN_PLAN_11_SICHTEN.md`, nicht doppelt hier.

## 8. Harte Grenzen (unverändert)

Echtgeld AUS. Auto-Merge AUS. V2-Kampagne ABGEBROCHEN. Holdout 2025 nur mit Uzis ausdrücklichem Wort. Merges nur nach „merge“. Änderungen an der Mac-Produktion nur mit Uzis Ja.

## 9. Offene Risiken

- 36 Commits Rückstand: Fehler aus den neuen PRs zeigen sich erst nach dem Einspielen (A01).
- Ein Rechner trägt Produktion, CI und Worker; Backup liegt auf derselben Platte (A22).
- Wissenschaftlicher Teil weiter FAIL; das 75 %-Ziel ist eine Hypothese, kein Ergebnis.
