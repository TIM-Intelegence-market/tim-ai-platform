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
| 1 | Inhaber und Ziel | GELB | Zieldefinition V2 im Gesamtplan enthält Uzis Entscheid zum 75-%-Ziel (Messlatte oder nicht) und die DoD aus #82 | Z1 Entscheid eintragen | Eintrag im Änderungsprotokoll von `docs/TIM_GESAMTPLAN.md` | Uzi entscheidet, Claude trägt ein |
| 2 | Projektleitung | GELB | Kein offenes P0 im Register; höchstens 3 offene PRs; ruhende Issues (M09, Server) als `status:ruhend` gekennzeichnet oder geschlossen; ein Plan | P1 Register pflegen, P2 Issues kennzeichnen, P3 #367 schließen (überholt durch #407) | Register-Tabelle im Audit, GitHub-Listen | Claude, Schließen auf Uzis Wort |
| 3 | Architektur | GELB | 4h- und 1d-Kerzen live; Nachprüfung 1h/4h/24h läuft als eigene Version neben 5/15/30; Paketinventar entschieden (jedes UNERREICHT-Paket archiviert oder mit Einstieg); Symbol-Kopplung mit Umbaupfad dokumentiert | H1 lange Horizonte, H2 HTF-Kerzen, I1 Inventar entscheiden | `src/orderflow/validation.py` v2 mit Tests; `TIM_TIMEFRAMES` enthält 4h,1d; `docs/PAKETINVENTAR.md` ohne „offen“ | Claude |
| 4 | Technik und Code | GELB | #417 gemergt; DemoTrader-Altcode entfernt; Abhängigkeiten gesperrt (`requirements.lock` oder Constraints) und gegen Live-venv geprüft; kein Test misst Wanduhrzeit | C1 #417, C2 A23 Altcode, C3 Sperrdatei, C4 canary ohne Zeitmessung | Suite grün, `pip freeze` = Sperrdatei | Claude, Merge Uzi |
| 5 | Forschung | ROT (Ergebnis) | S2 gerechnet (Live-Regeln 5/15/30 auf Historie); HTF-Nachprüfung mindestens 30 Tage gesammelt und ausgewertet; Entscheidung über die Live-Regeln dokumentiert | F1 S2 Power-Simulation + Freigabe 1.0, F2 S2 rechnen, F3 HTF-Auswertung nach 30 Tagen | Berichte unter `docs/research_lab/reports/`, Eintrag im Register | Claude rechnet, Uzi gibt S2 1.0 frei |
| 6 | Daten | ROT (Backup) | Tägliches Backup außerhalb des Mac; Restore-Probe PASS mit Dauer; neue Abdeckungsmessung seit Mac-Umzug ≥ 95 % oder Lücken erklärt; Deploy-Lücken bewusst begrenzt (gebündeltes Einspielen oder dokumentierte Ausnahme) | B1 Ziel klären (externe Platte oder zweiter Rechner), B2 Backup-Skript auf zweites Ziel, B3 Restore-Probe, M1 Coverage neu messen, M2 Deploy-Fenster | `docs/ops/restore_und_rollout_t02_t14.md` mit PASS-Protokoll; Messbericht | Uzi (Hardware), Claude (Skripte, Messung) |
| 7 | Tests und CI | GRÜN mit Einschränkung | Roter Push-Lauf auf platform-main meldet sich selbst (Issue oder Dashboard-Kachel); Server als zweiter Runner aktiv; Zeilenabdeckung steht in der Doku | T1 Push-Rot-Melder, T2 Server-Runner (Chris), T3 Coverage-Zahl | Workflow + Test; Runner-Liste; Zahl in `docs/TESTMATRIX.md` | Claude, Chris |
| 8 | Unabhängige Prüfung | GELB | Review-Pflicht für kritische Pfade (CODEOWNERS + Ruleset „Review von Code-Eignern“) aktiv; erstes echtes Review mit Attestierung (B06); B05-Integritätsprüfung erledigt | R1 CODEOWNERS-Vorschlag, R2 Ruleset-Schalter (Uzi), R3 Attestiertes Review, R4 B05-Prüfung | `.github/CODEOWNERS`; Ruleset-Export; Attestierung im Repo | Claude schlägt vor, Uzi schaltet, Chris prüft |
| 9 | Betrieb | GELB | Mac-Last erklärt und unter 8 im Normalbetrieb; USV entschieden und dokumentiert; Server als CI-Runner aktiv; Deploy-Agent prüft Health nach jedem Einspielen und meldet Rot | O1 Last messen (A21), O2 USV-Entscheid, O3 Health-Check nach Deploy | Messprotokoll; `ops/macos/LIVE_MAC.md`; Agent-Log | Claude, Uzi (USV) |
| 10 | Sicherheit | GRÜN mit Punkten | Home-Git: TIM-Datenpfade und Schlüsseldateien nachweislich ignoriert (Prüfskript); Tailnet-Eigentum geklärt (eigenes Tailnet oder dokumentierter Fallback); 2FA auf allen Konten bestätigt | S1 Prüfskript `.gitignore`, S2 Tailnet-Entscheid, S3 2FA-Bestätigung | Skript-Ausgabe; Eintrag in `docs/governance/` | Claude (S1), Uzi (S2, S3) |
| 11 | Dokumentation | GELB bis ROT | Einstiegsdokumente (`README.md`, `CI.md`, `docs/TIM_IN_10_MINUTEN.md`, `docs/SYSTEMSTAND.md`) tragen den Stand vom 25.10. oder neuer; jede dieser Dateien nennt ihr Stand-Datum; monatlicher Doku-Check im Register | D1 Einstiegsdoku aktualisieren, D2 Stand-Datum als Pflicht, D3 Doku-Check als wiederkehrendes Paket | Dateien im Repo; dieser Plan | Claude |

## Reihenfolge

1. **Sofort, ohne Freigabe:** D1 (diese Doku-Runde), H1 und H2 (lange Horizonte, HTF-Kerzen), C2 bis C4, I1, S1, T1, T3, P1 bis P3.
2. **Braucht Uzis Wort:** Z1 (75-%-Ziel), B1 (Backup-Ziel), R2 (Ruleset), O2 (USV), S2 (Tailnet), S3 (2FA), Merge von #417 und allen Paket-PRs, Freigabe S2 1.0.
3. **Braucht Chris:** T2 (Server-Runner), R4 (B05-Prüfung), Tailnet.
4. **Braucht Zeit:** F3 (30 Tage HTF-Daten ab Einspielen von H1), M1 (Messfenster seit Mac-Umzug).

Jedes Paket kommt als eigener, kleiner PR gegen `platform-main`, mit voller Suite in der Cloud vor der Meldung
„merge-fertig“. Pakete, die `~/TIM-live` ändern, wirken erst nach Uzis „merge“ und dem Einspielen durch den
Dashboard-Agenten.

## Status

| Paket | Status | PR / Nachweis |
|---|---|---|
| D1 Einstiegsdoku | VERIFIED | dieser PR: `README.md`, `CI.md`, `docs/TIM_IN_10_MINUTEN.md`, `docs/SYSTEMSTAND.md` |
| H1 lange Horizonte 1h/4h/24h | VERIFIED (Code), RUNNING (Daten ab Einspielen) | dieser PR: `src/orderflow/validation_long.py`, Migration 008, `tests/test_orderflow_validation_long.py`, `docs/ORDERFLOW_VALIDATION_LONG.md` |
| H2 4h-/1d-Kerzen | VERIFIED (Code), RUNNING (Daten ab Einspielen) | dieser PR: `src/data_ingestion/derived_candles.py`, Migration 009, `tests/test_derived_candles.py`, `docs/HTF_KERZEN.md` |
| T1 Push-Rot-Melder | VERIFIED (Code), wirkt ab dem ersten roten Push-Lauf | dieser PR: Job `report-red-main` in `.github/workflows/ci.yml`, Issue mit Label `ci-red` |
| T3 Coverage-Zahl | VERIFIED (Code) | dieser PR: Schritt „Coverage summary“ schreibt die Zeilenabdeckung in die Lauf-Zusammenfassung; Zahl nach dem ersten Lauf in `docs/TESTMATRIX.md` eintragen |
| C4 Tests ohne Wanduhrzeit | DONE (vorab) | `test_canary_15` prüft seit #380 eine Schranke von 1,5 s gegen 3,0 s Verzögerung, kein enges Zeitmaß mehr |
| F1 S2 Zähllauf + Power-Simulation | VERIFIED (Werkzeuge), BLOCKED (Lauf: Archive nur außerhalb der Cloud, Ort braucht Uzis Wort) | dieser PR: `scripts/research_lab_s2.py`, `src/research_lab/studies/s2_orderflow.py`, `s2_power.py`, `src/research_lab/data/aggtrades.py`, `tests/test_research_lab_s2.py`; Studie Abschnitt 7 |
| F2 S2 rechnen | BLOCKED (Freigabe 1.0 nach F1) | – |
| P1 Register nachführen | DONE | dieser PR: A17, A19, A20, A22, A23 in `docs/audits/TIM_AUTONOMOUS_INITIAL_AUDIT.md` |
| P2 ruhende Issues kennzeichnen | DONE | Label `status:ruhend` auf #9, #13–#21, #75–#78, #88, #332–#335 (25.10.) |
| P3 #367 schließen | BLOCKED (Uzis Wort) | überholt durch #405/#407 |
| I1 Paketinventar entscheiden | DONE (Entscheid), Ausführung auf Uzis Go | dieser PR: `docs/PAKETINVENTAR.md` ohne „offen“, Abschnitt „Entscheidungen vom 25.10.2026“; Archiv-PR für 8 Pakete braucht Uzis Go |
| C2 DemoTrader-Altcode | BLOCKED (Uzis Go, Audit A23) | Umfang: `src/paper/demo_trader_v1.py`, `scripts/demo_trader_report.py`, `tests/test_demo_trader_v1.py`, `tests/test_paper_demo_setup.py`, `config/paper_demo.json` |
| S1 Prüfskript Home-Git | VERIFIED (Werkzeug), Lauf auf dem Mac steht aus | dieser PR: `ops/macos/check_home_git_ignore.py`, `tests/test_check_home_git_ignore.py`; Ausgabe des Mac-Laufs nach `docs/governance/` |
| alle anderen | PLANNED | – |

Statuswerte: PLANNED, RUNNING, BLOCKED (wer), VERIFIED (Nachweis), DONE. Eine Delegation allein ist kein Abschluss.

## Änderungsprotokoll

- 25.10.2026: Plan angelegt (Thread „25.10. Alle 11 Sichten auf Grün bringen“).
- 25.10.2026 (abends): Status D1, H1, H2, T1, T3, F1, S1, P1, P2, I1 eingetragen; offen auf Uzis Wort: P3, C2, Z1, B1, R2, O2, S2/S3 (Sicht 10), Ort für den S2-Lauf, Freigabe S2 1.0.
