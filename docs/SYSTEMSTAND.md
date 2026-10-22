# Systemstand TIM (T01 des gemeinsamen Verbesserungsplans)

Stand 22.10.2026, erstellt aus der Cloud nur lesend. Jede Zeile nennt ihre Quelle.
**[V]** im Repo oder auf GitHub nachgeprüft, **[N]** aus Projektnotizen übernommen, nicht neu
gemessen, **[?]** unbekannt. Diese Datei beschreibt, was gilt; sie ändert nichts.

## 1. Bestandsliste

| Gegenstand | Ort | Maßgeblicher Stand | Quelle |
|---|---|---|---|
| Control-/Entwicklungsrepo | github.com/uezeyiraydin-cell/tim-ai-platform (Organisation TIM-Intelegence-market) | Branch `platform-main`, HEAD `e985971` (Merge #360). `main` ist veraltet und wird nicht benutzt. | [V] |
| Livecheckout (Kampagne) | Mac mini, `~/TIM-live`, detached HEAD | Commit `f469ad66d2796ec39d6c8e646acd222ae5826f14` (Merge #350), eingefroren seit 20.10.2026 | [N] Kampagnenregistrierung, `ops/macos/LIVE_MAC.md` |
| Abstand Live ↔ platform-main | | 4 Merges nach f469ad6: #355 (Dashboard, CI-Timeout), #360 (Gamma/GEX). Keine davon in `~/TIM-live`. | [V] `git log f469ad6..e985971` |
| Uzis Arbeitsordner | Mac, `~/Documents/TIM/tim` | hat lokale Änderungen, nicht Grundlage des Livebetriebs | [N] |
| Issue-Worker | Mac, `~/TIM-worker`, Konto apoman74-art | Stand unbekannt | [N] [?] |
| Datenbank (Runtime) | Mac, PostgreSQL 18, 127.0.0.1:5432, Benutzer postgres | Schema-Version [?] | [N] |
| Test-Datenbank CI | Mac, PostgreSQL 16, 127.0.0.1:5434, `tim_test` | `ops/macos/setup_ci_runner.sh` | [V] ci.yml |
| Kampagne | Mac, `~/TIM-live/data/qualification/qualification_campaign.json` (außerhalb Git) | Start 2026-10-20 20:34 UTC, Mindestdauer 34 Tage bis 2026-11-23 20:34 UTC, Software-Commit f469ad6 | [N] Plan Abschnitt 2 |
| Vorregistrierung | `artifacts/v2_completion/qualification_preregistration.json` | Hash `82bfe439…14ca6` (configuration_hash), Ziel 95 % Coverage, 1.000 Einheiten, 9 Start-Gates, 6 Abbruchbedingungen | [V] |
| Tagesbelege | `~/TIM-live/data/qualification/` (Mac) sowie `artifacts/v2_completion/qualification_daily_manifests/` im Repo (bisher nur README) | ein unveränderlicher Beleg je abgeschlossenem UTC-Tag | [V] Repo, [N] Mac |
| CI | Runner `mac-mini-tim` (self-hosted, Benutzer timrunner), Workflows `ci.yml` (test), `pr-gate.yml` (PR gate), `tim-priority-board.yml`; `tim-full-suite.yml` und `auto-merge-controller.yml` auf ubuntu-latest, nur manuell | Pflichtchecks laut Ruleset: `test`, `PR gate`, Branch muss aktuell sein | [V] Workflows, [N] Ruleset |
| Backups | Mac, `~/Library/Application Support/TIM/backups/live`, täglich 03:15 Ortszeit, 3 Stände; Ordner `~/TIM-Backups` existiert | Inhalt und Vollständigkeit nicht geprüft | [N], Ordnername [V] get_device_info |
| Server tim-core-01 | Debian, `/opt/tim` | seit 20.10. nicht Teil des Betriebs (Uzi: „100 % auf dem Mac“) | [N] |

## 2. Bindungen und Freeze

- Eingefroren sind Commit f469ad6, die fünf gerenderten Plists in `~/Library/LaunchAgents` und die
  Konfiguration (Start-Gate `configuration_and_commit_frozen`). Jede Änderung in `~/TIM-live` ist eine
  registrierte Abbruchbedingung (`protected_state_change`). [V] Vorregistrierung, LIVE_MAC.md
- Laufende Dienste auf dem Mac (Soll laut `ops/launchd/`): runtime, watchdog, server-health,
  history-recovery, qualification-daily; außerdem awake (caffeinate). Welche der 18 Vorlagen
  tatsächlich geladen sind: [?], nur per `launchctl list` auf dem Mac prüfbar.
- Suite-Nachweis für f469ad6: push-CI-Lauf 39482022376 (success, 20.10. 19:40 UTC). [N]
- Python/Paketstand der Live-venv: **erfasst am 22.10. 01:26 UTC** von Uzi, lesend auf dem Mac
  (`docs/systemstand/live-env-2026-10-22/`: Python 3.13.16, 50 Pakete, Prüfsummen im README). [V]
  Der Export beweist nicht den Stand vom 20.10.; er dokumentiert den Ist-Zustand ab Exportdatum.
  Betriebssystemabhängigkeiten (Homebrew, libpq, OpenSSL) sind nicht erfasst. [?]
- Abhängigkeiten im Repo sind Bereiche ohne Sperrdatei (`requirements.txt`: asyncpg, websockets,
  pytest, pytest-asyncio, langchain-ollama, langgraph, duckduckgo-search). [V]

## 3. Offene PRs und ihr Rolloutstatus (22.10., 01:00 UTC; #365 seit 01:56 UTC Entwurf mit Korrektur-Commit d86baea nach Uzis Nachprüfung, am 22.10. ~09:45 UTC auf platform-main 1554101 aktualisiert; D01-A/D02-A als Design freigegeben, nicht zu mergen)

Keiner der offenen PRs ist in `~/TIM-live`. „Merge“ heißt nur: in `platform-main`; ausgerollt wird
während der Kampagne nichts.

| PR | Thema | Quelle | Bezug zum Plan |
|---|---|---|---|
| #364 | B06: leere Review-Workbooks nicht als PASS | Codex | T04. Test grün, Branch war „behind“, am 22.10. aktualisiert, Gate ausstehend |
| #363 | Dashboard: TIM-Chart, Pläne im Setup-Pfad | Claude | kein Plan-Paket |
| #362 | Orderflow-Kontexttypen (Funding, OI, Orderbuch, TPO) | Claude | kein Plan-Paket, neue Funktion → Paket-Moratorium prüfen |
| #361 | Wöchentliche Reflexion gegen Basisrate (nur lesend) | Claude | T08/T09 Vorarbeit |
| #359 | Skill aus Anthropic-Plugin | Claude | kein Plan-Paket |
| #357 | Health-Snapshot-Zeit im Tagesbeleg erhalten | Codex | T09 |
| #356 | gemeinsamer Mac-Backup-Pfad | Codex | T02 |
| #354 | Startfreigaben auf gültige UTC-Zeit prüfen | Codex | T04/T09 |
| #353 | Kampagnenhash vor Tagesbelegen prüfen | Codex | T05/T09 |
| #352 | Tagesbelege mit Runtime-Zählern | Codex | T09 |
| #351 | Startberichte: Hashgleichheit, eindeutige PASS-Gates | Codex | T05 |
| #349 | Legacy-Herkunft lesend inventarisieren | Codex | T05 (B05) |
| #348 | unveränderliche Belege gegen Überschreiben | Codex | T05 |
| #347 | Fallzahl-PASS und wissenschaftliche Freigabe getrennt | Codex | T04/T09 |
| #333 (Draft) | Auto-Merge: ein Merge-Pfad | Codex | T11, bleibt aus (Uzi: Auto-Merge vorerst nein) |

Quelle: GitHub-API, 22.10.2026 01:03 UTC. [V]

## 4. Geschützte Dateien und Dienste (Zone C, während der Kampagne nicht anfassen)

- `~/TIM-live/**` (Code, `.venv`, `data/qualification/`, Plists daraus gerendert)
- `~/Library/LaunchAgents/com.tim.*.plist`
- PostgreSQL 18 auf 5432: Schema, Indizes, Retention, `ingestion_outbox`
- macOS-Updates, Neustart, Ruhezustand, Stromversorgung des Mac mini und des Routers
- Netz: Router (pfSense, Chris), Tailnet tailnet.example.ts.net (Konto fleckbarti-ai)
- Im Repo durch das PR-Gate gesperrt (`.github/pr-gate-policy.json`, gilt für Worker-Branches):
  `.github/`, `.claude/`, `scripts/`, `config/`, `schemas/`, `ops/`, `artifacts/`, `src/database/`,
  `src/tim_incident/`, CLAUDE.md, CI.md, requirements, pytest.ini u. a. [V]

## 5. Was dieser Stand nicht leistet

- Kein Gesundheitsnachweis der Kampagne (Coverage heute, Queue, Frische): dafür die Tagesbelege.
- Kein Nachweis des Live-Paketstands (siehe Abschnitt 2).
- Keine Aussage über tatsächlich geladene Dienste oder Datenbankgröße auf dem Mac.

Jeder Test und Bericht, der auf diesen Stand verweist, nennt: Quellcommit, Datenstand (Cut-off),
Umgebung (Cloud-Container, Mac-Live, Mac-Worker, CI-Runner) und Gültigkeitsbereich.
