# Grün-Plan: alle 11 Sichten auf Grün

Stand 25.10.2026, Thread „25.10. Alle 11 Sichten auf Grün bringen“. Auftrag Uzi: „ziel ist es am ende alle 11 sichten
auf gruen zu kriegen“. Grundlage ist die Gesamtbild-Analyse vom 25.10. (Claude Doc „TIM Gesamtbild in 11 Sichten“,
platform-main `ed9e929`). Die 11 Sichten sind die zehn Rollen aus dem TIM-Masterprompt plus die Sicht des Inhabers.

## Was „Grün“ heißt

Grün heißt: Das Kriterium der Sicht ist erfüllt und der Nachweis liegt im Repo oder auf dem Mac. Grün heißt nicht
„profitabel“. Für die Forschung (Sicht 5) heißt Grün: Die offene Frage ist mit einer vorab registrierten Studie
beantwortet und die Entscheidung über die Regeln ist dokumentiert. Ein ehrliches „kein Vorteil“ ist dabei ein gültiges
Grün. Ergebnisse werden nicht erfunden; was nicht gemessen ist, bleibt offen.

Feste Grenzen, die kein Paket verschiebt: kein Echtgeld, keine echte Order, Holdout ab 2025 nur mit Uzis Wort, keine
zweite Studie derselben Art auf 2020 bis 2024 ohne neue Registrierung, Merge nur auf Uzis „merge“, keine Zugangsdaten
in Dateien.

## Die 11 Sichten: Kriterium, Pakete, Nachweis

| Nr | Sicht | Stand 25.10. | Grün-Kriterium | Pakete | Nachweis | Wer |
|---|---|---|---|---|---|---|
| 1 | Inhaber und Ziel | GRÜN (Z1 entschieden 26.10.) | Zieldefinition V2 im Gesamtplan enthält Uzis Entscheid zum 75-%-Ziel (Messlatte oder nicht) und die DoD aus #82 | Z1 Entscheid eintragen | Eintrag im Änderungsprotokoll von `docs/TIM_GESAMTPLAN.md` | Uzi entscheidet, Claude trägt ein |
| 2 | Projektleitung | GRÜN (P1–P3 erledigt; kein offenes P0: A02 live geprüft, A03 durch #413; 26.10. auf Uzis Wahl #428 gemergt und #333 geschlossen: 3 offene PRs #437, #393, #387) | Kein offenes P0 im Register; höchstens 3 offene PRs; ruhende Issues (M09, Server) als `status:ruhend` gekennzeichnet oder geschlossen; ein Plan | P1 Register pflegen, P2 Issues kennzeichnen, P3 #367 schließen (überholt durch #407) | Register-Tabelle im Audit, GitHub-Listen | Claude, Schließen auf Uzis Wort |
| 3 | Architektur | GRÜN (26.10.: 4h/1d-Kerzen und Nachprüfung long-1.0.0 live auf dem Mac geprüft, Inventar I1 erledigt, Symbol-Kopplung in `docs/MULTI_SYMBOL_ARCHITEKTUR.md`) | 4h- und 1d-Kerzen live; Nachprüfung 1h/4h/24h läuft als eigene Version neben 5/15/30; Paketinventar entschieden (jedes UNERREICHT-Paket archiviert oder mit Einstieg); Symbol-Kopplung mit Umbaupfad dokumentiert | H1 lange Horizonte, H2 HTF-Kerzen, I1 Inventar entscheiden | `src/orderflow/validation.py` v2 mit Tests; `TIM_TIMEFRAMES` enthält 4h,1d; `docs/PAKETINVENTAR.md` ohne „offen“ | Claude |
| 4 | Technik und Code | GRÜN (C1 #417 am 26.10. gemergt, C2, C3, C4 erledigt) | #417 gemergt; DemoTrader-Altcode entfernt; Abhängigkeiten gesperrt (`requirements.lock` oder Constraints) und gegen Live-venv geprüft; kein Test misst Wanduhrzeit | C1 #417, C2 A23 Altcode, C3 Sperrdatei, C4 canary ohne Zeitmessung | Suite grün, `pip freeze` = Sperrdatei | Claude, Merge Uzi |
| 5 | Forschung | GELB: S2 gerechnet und beendet (NICHT BEURTEILBAR), Entscheidung über die Live-Regeln dokumentiert (Beobachtungen, keine Signale); offen bleibt F3 (HTF-Nachprüfung nach 30 Tagen) | S2 gerechnet (Live-Regeln 5/15/30 auf Historie); HTF-Nachprüfung mindestens 30 Tage gesammelt und ausgewertet; Entscheidung über die Live-Regeln dokumentiert | F1 S2 Power-Simulation + Freigabe 1.0, F2 S2 rechnen, F3 HTF-Auswertung nach 30 Tagen | Berichte unter `docs/research_lab/reports/`, Eintrag im Register | Claude rechnet, Uzi gibt S2 1.0 frei |
| 6 | Daten | GRÜN mit Vermerk (26.10.: Restore-Probe PASS, M1 erfüllt; keine Kopie außerhalb des Mac, von Uzi bewusst als Restrisiko angenommen) | Tägliches Backup außerhalb des Mac; Restore-Probe PASS mit Dauer; neue Abdeckungsmessung seit Mac-Umzug ≥ 95 % oder Lücken erklärt; Deploy-Lücken bewusst begrenzt (gebündeltes Einspielen oder dokumentierte Ausnahme) | B1 Ziel klären (externe Platte oder zweiter Rechner), B2 Backup-Skript auf zweites Ziel, B3 Restore-Probe, M1 Coverage neu messen, M2 Deploy-Fenster | `docs/ops/restore_und_rollout_t02_t14.md` mit PASS-Protokoll; Messbericht | Uzi (Hardware), Claude (Skripte, Messung) |
| 7 | Tests und CI | GRÜN (T1, T2, T3 erledigt) | Roter Push-Lauf auf platform-main meldet sich selbst (Issue oder Dashboard-Kachel); Server als zweiter Runner aktiv; Zeilenabdeckung steht in der Doku | T1 Push-Rot-Melder, T2 Server-Runner (Chris), T3 Coverage-Zahl | Workflow + Test; Runner-Liste; Zahl in `docs/TESTMATRIX.md` | Claude, Chris |
| 8 | Unabhängige Prüfung | GRÜN mit Vermerk (26.10.: Uzi verzichtet vorerst bewusst auf eine erzwungene Zweitprüfung, weil keine zweite Person dafür zur Verfügung steht; Schranke bleibt Uzis „merge“) | Review-Pflicht für kritische Pfade (CODEOWNERS + Ruleset „Review von Code-Eignern“) aktiv; erstes echtes Review mit Attestierung (B06); B05-Integritätsprüfung erledigt | R1 CODEOWNERS-Vorschlag, R2 Ruleset-Schalter (Uzi), R3 Attestiertes Review, R4 B05-Prüfung | `.github/CODEOWNERS`; Ruleset-Export; Attestierung im Repo | Claude schlägt vor, Uzi schaltet, Chris prüft |
| 9 | Betrieb | GRÜN (26.10.: Last im Normalbetrieb 3–5, USV entschieden und dokumentiert, zweiter CI-Runner auf dem Server seit 25.10., Health-Check nach Deploy; Vermerk: USV noch nicht angeschlossen) | Mac-Last erklärt und unter 8 im Normalbetrieb; USV entschieden und dokumentiert; Server als CI-Runner aktiv; Deploy-Agent prüft Health nach jedem Einspielen und meldet Rot | O1 Last messen (A21), O2 USV-Entscheid, O3 Health-Check nach Deploy | Messprotokoll; `ops/macos/LIVE_MAC.md`; Agent-Log | Claude, Uzi (USV) |
| 10 | Sicherheit | GRÜN (S1 PASS; Tailnet bleibt bei Chris, dokumentierter Fallback; 2FA von Uzi bestätigt 26.10.) | Home-Git: TIM-Datenpfade und Schlüsseldateien nachweislich ignoriert (Prüfskript); Tailnet-Eigentum geklärt (eigenes Tailnet oder dokumentierter Fallback); 2FA auf allen Konten bestätigt | S1 Prüfskript `.gitignore`, S2 Tailnet-Entscheid, S3 2FA-Bestätigung | Skript-Ausgabe; Eintrag in `docs/governance/` | Claude (S1), Uzi (S2, S3) |
| 11 | Dokumentation | GRÜN (26.10.: README 26.10., CI.md, TIM_IN_10_MINUTEN und SYSTEMSTAND 25.10., je mit Stand-Datum; Doku-Check A26 monatlich, nächster 25.11.) | Einstiegsdokumente (`README.md`, `CI.md`, `docs/TIM_IN_10_MINUTEN.md`, `docs/SYSTEMSTAND.md`) tragen den Stand vom 25.10. oder neuer; jede dieser Dateien nennt ihr Stand-Datum; monatlicher Doku-Check im Register | D1 Einstiegsdoku aktualisieren, D2 Stand-Datum als Pflicht, D3 Doku-Check als wiederkehrendes Paket | Dateien im Repo; dieser Plan | Claude |

## Reihenfolge

1. **Sofort, ohne Freigabe:** D1 (diese Doku-Runde), H1 und H2 (lange Horizonte, HTF-Kerzen), C2 bis C4, I1, S1, T1, T3, P1 bis P3.
2. **Braucht Uzis Wort:** R2 (Ruleset), O2 (USV), Merge aller Paket-PRs, Freigabe S2 1.0. Entschieden am 26.10.: Z1 (75 % gestrichen), B1 (SSD), S2 (Tailnet bleibt bei Chris), S3 (2FA bestätigt).
3. **Braucht Chris:** T2 (Server-Runner), R4 (B05-Prüfung), Tailnet.
4. **Braucht Zeit:** F3 (30 Tage HTF-Daten ab Einspielen von H1), M1 (Messfenster seit Mac-Umzug).

Jedes Paket kommt als eigener, kleiner PR gegen `platform-main`, mit voller Suite in der Cloud vor der Meldung
„merge-fertig“. Pakete, die `~/TIM-live` ändern, wirken erst nach Uzis „merge“ und dem Einspielen durch den
Dashboard-Agenten.

## Status

| Paket | Status | PR / Nachweis |
|---|---|---|
| D1 Einstiegsdoku | VERIFIED | dieser PR: `README.md`, `CI.md`, `docs/TIM_IN_10_MINUTEN.md`, `docs/SYSTEMSTAND.md` |
| H1 lange Horizonte 1h/4h/24h | VERIFIED (Live 26.10. 13:45): `/api/validations-long` Version long-1.0.0, OBSERVE, Beobachtungen 25.10. 11:29Z bis 26.10. 11:43Z, 169 vollständig, Abdeckung 100 % | dieser PR: `src/orderflow/validation_long.py`, Migration 008, `tests/test_orderflow_validation_long.py`, `docs/ORDERFLOW_VALIDATION_LONG.md` |
| H2 4h-/1d-Kerzen | VERIFIED (Live 26.10. 13:45): `/api/candles-derived?tf=4h` 300 Kerzen, jüngste 08:00–12:00Z; `tf=1d` 87 Kerzen bis 26.10. 00:00Z | dieser PR: `src/data_ingestion/derived_candles.py`, Migration 009, `tests/test_derived_candles.py`, `docs/HTF_KERZEN.md` |
| T1 Push-Rot-Melder | VERIFIED (Code), wirkt ab dem ersten roten Push-Lauf | dieser PR: Job `report-red-main` in `.github/workflows/ci.yml`, Issue mit Label `ci-red` |
| T3 Coverage-Zahl | VERIFIED 26.10.: 89,7 % Zeilen `src/` (42 827/47 762) auf 2fbbe78, in der Cloud gerechnet (Artefakt-Host in der Cloud gesperrt, Runner-Ordner nicht lesbar); CI schreibt die Zahl je Lauf in die Zusammenfassung | `docs/TESTMATRIX.md` Abschnitt 3 |
| C4 Tests ohne Wanduhrzeit | DONE (vorab) | `test_canary_15` prüft seit #380 eine Schranke von 1,5 s gegen 3,0 s Verzögerung, kein enges Zeitmaß mehr |
| F1 S2 Zähllauf + Power-Simulation | VERIFIED: Zähllauf PASS (`docs/research_lab/reports/s2_count_2026-10-25T2249Z.md`), Power-Gate gerechnet und NICHT BESTANDEN (`s2_power_2026-10-25T2345Z.md`, alle 72 Szenarien mit ICC > 0 unter 90 %) | Mac mini, Worktree `s2-zaehllauf`, PR #432; Studie Abschnitt 8 |
| F2 S2 rechnen (Ergebnislauf) | DONE (entfällt): Studie am Power-Gate NICHT BEURTEILBAR; **Uzis Entscheid 26.10. 01:24: S2 beendet, Live-Orderflow-Regeln = Beobachtungen, keine Signale, kein S3** | Studie Abschnitt 8, Status-Zeile |
| F4 Survivorship-Grenze und Abschnittsregel (Protokoll 1.2) | VERIFIED (Regel in 3.1/3.2 + Code + Test); Universum mit delisteten Coins nur als Vorschlag, braucht Uzis Wort | PR #429: `docs/research_lab/PROTOKOLL.md`, `src/research_lab/protocol.py`, `stats/inference.py` (`section_trades`), `runner.py`, `stats/guard.py`, `tests/test_research_lab_stats.py` |
| P1 Register nachführen | DONE | dieser PR: A17, A19, A20, A22, A23 in `docs/audits/TIM_AUTONOMOUS_INITIAL_AUDIT.md` |
| P2 ruhende Issues kennzeichnen | DONE | Label `status:ruhend` auf #9, #13–#21, #75–#78, #88, #332–#335 (25.10.) |
| P3 #367 schließen | DONE 26.10. (Uzis „weiter“) | PR #367 geschlossen mit Hinweis auf #405/#407 (Mac-Runner entkoppelt, zweiter Runner auf dem Server) |
| I1 Paketinventar entscheiden | DONE 26.10. (Uzis „weiter“): 7 Pakete samt Tests entfernt, Stand im Zweig `archiv/unerreichte-pakete-2026-10-26` (06c8bc2); `repair_repro` bleibt (Korrektur: `repair_gates` importiert es) | Archiv-PR; `docs/PAKETINVENTAR.md` Abschnitt „Ausführung vom 26.10.2026“ |
| C2 DemoTrader-Altcode | DONE 26.10. (Uzis „weiter“, A23) | Archiv-PR: entfernt `src/paper/demo_trader_v1.py`, `scripts/demo_trader_report.py`, `tests/test_demo_trader_v1.py`, `tests/test_paper_demo_setup.py`, `config/paper_demo.json`; `src/paper/automation.py` bleibt |
| S1 Prüfskript Home-Git | VERIFIED 26.10.: Mac-Lauf erst FAIL (15 Pfade nicht ignoriert), nach Eintrag in `~/.git/info/exclude` PASS | `docs/governance/home_git_pruefung_2026-10-26.md` |
| O1 Mac-Last messen | VERIFIED 26.10. 20:22–20:27 (Mac-Sitzung, nur lesend, CI frei seit 20:17): Last 1 min 2,95–4,83 (5 Proben), Kriterium < 8 erfüllt; Health GREEN, Daten 0 s alt. Mit CI-Job 9–16. Treiber der Spitzen: `pytest -n 4` (CI unter timrunner und lokale Läufe anderer Claude-Sitzungen unter tim-user), dazu Chrome, WindowServer, Claude-App; TIM selbst (Runtime, Postgres) kein Haupttreiber. Frühere Messung 10:06 während CI: 10,7/7,9/5,3 | Protokoll der RC-Sitzung, siehe Änderungsprotokoll |
| O2 USV-Entscheid | DONE 26.10. (Uzi „ja“, 20:12): USV wird angeschafft; Gerät, Einrichtung (`pmset -u haltlevel 30 haltremain 10`, `autorestart 1`) und Probe in `ops/macos/LIVE_MAC.md`. Kauf und Anschluss bei Uzi; offen: Autostart der LaunchAgents nach Neustart ohne Anmeldung | `ops/macos/LIVE_MAC.md` |
| F4-Folge: Universum mit delisteten Coins | Machbarkeit geprüft 26.10.: data.binance.vision hält Monatsarchive delisteter USD-M-Perpetuals noch vor (LUNAUSDT 2022-04, FTTUSDT 2022-10, SRMUSDT 2022-10, BTCDOMUSDT 2023-01: HTTP 200). Eine Studie mit point-in-time-Universum ist damit möglich; ob sie kommt, entscheidet Uzi | HEAD-Abfragen von der RC-Sitzung, nichts geladen |
| C3 Sperrdatei | VERIFIED 26.10.: `requirements.lock` = `pip freeze` der Live-venv (51 Pakete, Python 3.13.16), Prüfskript + 5 Tests; `httpx2`/`httpcore2` geprüft (pydantic/httpx2, legitim). Offen: Live-Install und CI auf `-c requirements.lock` umstellen (eigener PR, ändert Runtime-Setup) | `requirements.lock`, `scripts/check_requirements_lock.py`, `tests/test_requirements_lock.py` |
| D2 Stand-Datum als Pflicht | DONE 26.10.: README trägt jetzt ein Stand-Datum; CI.md, TIM_IN_10_MINUTEN, SYSTEMSTAND hatten eines | `README.md` |
| D3 Doku-Check wiederkehrend | DONE 26.10.: Register A26, monatlich, nächste Fälligkeit 25.11.2026 | `docs/audits/TIM_AUTONOMOUS_INITIAL_AUDIT.md` |
| M2 Deploy-Fenster | DONE 26.10. (dokumentierte Ausnahme): Uzis Entscheid vom 25.10. (Agent wartet nicht auf Studienenden), Mindestabstand 20/60 min, Sammelwirkung | `ops/macos/LIVE_MAC.md` Abschnitt Dashboard-Agent |
| O3 Health-Check nach Deploy | VERIFIED 26.10. (Code + Live): `dashboard_refresh.restart_runtime` prüft `/api/health` nach jedem Neustart, bei Rot `ROLLED_BACK` mit `failure=restart_or_health_failed`; Live-Status 26.10. 10:20: `health_ok=true`, deployed dbaa3e1, Ziel 2fbbe78 wartet auf Ende des CI-Jobs. Beobachtung für den Dashboard-Thread: `checked_at_utc`/`target_commit` werden bei WAIT nicht mitgeschrieben | `src/operational/dashboard_refresh.py`, `~/TIM-live/data/operational/dashboard_refresh.json` |
| M1 Abdeckung seit Mac-Umzug | VERIFIED 26.10. (Uzi im Terminal): 1m lückenlos seit 22.10. (6362 Kerzen = Soll), alle Zeitstufen passen, kein Tag unter 95 % | `docs/ops/kerzen_abdeckung_mac_2026-10-26.md` |
| B3 Restore-Probe | VERIFIED 26.10. 13:45 (Uzi im Terminal): PASS, 26,5 min, `agg_trades` exakt gleich, `candles` −2 = nach dem Dump nachgetragen; Scratch-DB gelöscht, Health GREEN. Vorher drei FAIL ohne Schaden (template1, CREATEDB, pg_hba-Reihenfolge hinter dem Härtungs-include) | `docs/ops/restore_und_rollout_t02_t14.md` Zeile „Restore geübt“ |
| B1 Backup-Ziel | DONE 26.10. 13:46 (Uzi auf der Karte „Nur interne Platte, Risiko annehmen“): keine zweite Kopie außerhalb des Mac. Restrisiko: Plattendefekt, Diebstahl oder Verschlüsselung des Mac vernichtet Datenbank und alle drei Dumps zugleich. Vorher 12:28 „ssd“, aber keine SSD vorhanden (13:44) | Thread „25.10. Alle 11 Sichten auf Grün bringen“; `docs/ops/restore_und_rollout_t02_t14.md` |
| B2 Backup-Skript auf zweites Ziel | DONE (Code, PR #442): `tim_db_backup.py mirror` + `ops/launchd/com.tim.db-backup-mirror.plist` liegen bereit, **nicht installiert** (kein Ziel). Wird eine externe SSD `TIM-Backup` angeschlossen, reicht der Block in `ops/macos/LIVE_MAC.md` | `scripts/tim_db_backup.py`, `ops/macos/LIVE_MAC.md` |
| S2 Tailnet | DONE 26.10. 12:32 (Uzi: „chris bleibt“): Tailnet `tailnet.example.ts.net` bleibt bei Chris' Konto; Fallback bei Ausfall: Dashboards nur lokal auf dem Mac (127.0.0.1) | Memory-Eintrag; `docs/governance/` |
| S3 2FA | DONE 26.10. 12:32 (Uzi: „ja“ auf die Frage nach 2FA für GitHub, Binance-Testnet, Apple-Konto); keine eigene Prüfung durch Claude möglich | Uzis Wort im Thread |
| R1 CODEOWNERS | DONE (vorhanden): `.github/CODEOWNERS`, Eigner uezeyiraydin-cell für config/, scripts/, workflows, src/database/ | `.github/CODEOWNERS` |
| R2 Ruleset „Review von Code-Eignern“ | ENTSCHIEDEN: vorerst nicht (Uzi 26.10. 19:57). Claude-PRs laufen unter Uzis Konto, ein Pflicht-Review bräuchte Chris für jeden kritischen PR; Vorschlag #449 geschlossen. Neu prüfen, sobald eine zweite Person regelmäßig verfügbar ist | GitHub-Einstellungen |
| T2 Server-Runner | DONE 25.10.: `tim-core-01-ci` auf Chris' Server aktiv (PR #416) | Runner-Liste |
| Z1 75-%-Ziel | DONE 26.10. 11:09: Uzi auf der Karte „75 % streichen, DoD aus #82 gilt“; eingetragen als v0.7 im Gesamtplan | `docs/TIM_GESAMTPLAN.md` Abschnitt 1 und Änderungsprotokoll |
| alle anderen | PLANNED | – |

Statuswerte: PLANNED, RUNNING, BLOCKED (wer), VERIFIED (Nachweis), DONE. Eine Delegation allein ist kein Abschluss.

## Änderungsprotokoll

- 25.10.2026: Plan angelegt (Thread „25.10. Alle 11 Sichten auf Grün bringen“).
- 25.10.2026 (abends): Status D1, H1, H2, T1, T3, F1, S1, P1, P2, I1 eingetragen; offen auf Uzis Wort: P3, C2, Z1, B1, R2, O2, S2/S3 (Sicht 10), Ort für den S2-Lauf, Freigabe S2 1.0.
- 26.10.2026 (10:05, Uzis „weiter“): P3 (#367 geschlossen), I1 (Archiv von 7 Paketen, `repair_repro` bleibt), C2 (DemoTrader-Altcode) als Archiv-PR; S1 auf dem Mac FAIL → behoben → PASS; O1 erste Messung (während CI-Job); F4-Folge: delistete Symbole auf data.binance.vision vorhanden. Weiter offen auf Uzis Wort: Z1, B1, R2, O2, Tailnet, 2FA, Studie mit delisteten Coins.
- 26.10.2026 (10:45): PR #436 gemergt. C3 (Sperrdatei), D2, D3, M2, O3, R1, T2 eingetragen; M1 und B3 brauchen Uzis Terminal (Cloud und Mac-Sitzung dürfen die Live-DB nicht lesen); F3 bleibt Zeit (ab 24.11.); B1/B2, R2, O2, Tailnet, 2FA, Z1 bleiben bei Uzi.
- 26.10.2026 (11:10): PR #440 gemergt (3a18466). M1 VERIFIED (Uzis Terminal-Lauf, 1m lückenlos). B3 FAIL an pg_hba/template1: Code-Fix `--maintenance-db`, Admin-Schritte bei Uzi.
- 26.10.2026 (11:12): Z1 entschieden (75 % gestrichen, DoD #82), Sicht 1 GRÜN.
- 26.10.2026 (12:40): B1 entschieden (SSD), B2 gebaut (`mirror`, LaunchAgent); S2/S3 entschieden, Sicht 10 GRÜN. B3: zweiter Lauf 12:28 FAIL an fehlendem CREATEDB (pg_hba-Zeile greift); postgres-Admin nur über lokalen Socket. Offen bei Uzi: SSD anschließen und Agent laden, B3 wiederholen, R2, O2.
- 26.10.2026 (13:50): B3 Restore-Probe PASS (26,5 min). Sicht 3 GRÜN (HTF live geprüft). Uzi hat keine SSD und will die Kopie auf dem Mac; eine zweite Kopie auf derselben Platte erfüllt „außerhalb des Mac“ nicht. Entscheidungskarte 13:46: Uzi wählt „Nur interne Platte, Risiko annehmen“. Sicht 6 GRÜN mit Vermerk.
- 26.10.2026 (14:00): PR #445 gemergt. Sicht 11 GRÜN. Stand: GRÜN 1, 3, 6, 7, 10, 11; GELB 2 (PR-Zahl, P0 A02/A03), 4 (#417), 8 (Ruleset, B05), 9 (USV, Lastmessung ohne CI), 5 (F3 ab 24.11.).
- 26.10.2026 (16:30): PR #417 auf platform-main gebracht (Merge-Commit, Konflikte: Scharfschaltung und Stop-Regel be_cost/1 beide behalten) und gemergt. Sicht 4 GRÜN. A03 war schon durch #413 (Studie K1) erledigt, Register nachgezogen: kein offenes P0. Sicht 2 bleibt GELB nur wegen der PR-Zahl. Stand: GRÜN 1, 3, 4, 6, 7, 10, 11; GELB 2, 8, 9, 5.
- 26.10.2026 (19:40): Uzi wählt auf der Karte „#428 mergen und #333 schließen“. #428 gemergt (074ccc4), #333 geschlossen. Sicht 2 GRÜN. Stand: GRÜN 1, 2, 3, 4, 6, 7, 10, 11; GELB 8 (Ruleset, B05), 9 (USV, Lastmessung ohne CI); 5 (F3 ab 24.11.).
- 26.10.2026 (19:57): Uzi wählt für Sicht 8 „bewusst ohne“ (keine zweite Person verfügbar). CODEOWNERS-Vorschlag #449 geschlossen, R2 entschieden: vorerst nicht. Sicht 8 GRÜN mit Vermerk. Stand: GRÜN 1, 2, 3, 4, 6, 7, 8, 10, 11; GELB 9 (USV, Lastmessung ohne CI); 5 (F3 ab 24.11.).
- 26.10.2026 (20:35): O2 entschieden (Uzi „ja“: USV wird angeschafft, Anleitung in `ops/macos/LIVE_MAC.md`), O1 im Normalbetrieb gemessen (Last 2,95–4,83). Sicht 9 GRÜN mit Vermerk (USV-Gerät fehlt noch). Stand: GRÜN 1, 2, 3, 4, 6, 7, 8, 9, 10, 11; offen nur 5 (F3 ab 24.11.).
