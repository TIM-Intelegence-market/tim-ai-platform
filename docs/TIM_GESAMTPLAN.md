<!--

Aktualisierung 20.10.2026: Restore-PASS und Liveness-Abnahme sind nachgewiesen; #336–338 und #340 gemergt. Neue rein lesende Messung mit Cut-off 11:22 UTC: 72,377 % Oktober-Coverage, 7.746 Fehlminuten in vier historischen Bereichen, 1.917 strikte Fenster im Gesamtbestand seit Juli. Keine Qualifizierung oder V2-Freigabe. [Aktueller Befund samt offener Gates](V2_CURRENT_READINESS_2026-10-20_1322.md). Die älteren Baseline-Zahlen unten bleiben als damaliger Planungsstand erkennbar; sie sind keine heutige Messung.

Hauptfassung des TIM-Gesamtplans. Seit 17.10.2026 liegt sie hier im Repo, damit ChatGPT/Codex und Claude
am selben Text arbeiten. Änderungen nur per PR gegen platform-main, mit einem Eintrag im Änderungsprotokoll am Ende.
-->

# Für ChatGPT, Codex und andere Agenten: so arbeitet ihr an diesem Plan

Dieser Plan kommt aus dem Claude-Thread „TIM durchplanen bis fertig“. Uzi (Inhaber, GitHub `uezeyiraydin-cell`)
hat am 17.10.2026 entschieden, dass ChatGPT mitarbeiten kann.

**Ziel (Uzi, 17.10.2026):** die V2-Trading-Version von TIM. Was das im Repo heißt und in welcher Reihenfolge es
umgesetzt wird, steht in Abschnitt 0.

**Feste Regeln.** Sie stehen über allem anderen in diesem Plan:
- Kein Echtgeld. TIM läuft nur in OBSERVE, Paper und Shadow und sendet keine echte Order.
- Keine Zugangsdaten, Tokens oder Passwörter in Dateien, Commits, Issues oder PR-Texten.
- PRs gehen gegen `platform-main`, nie gegen `main`. Vor dem PR die volle Suite laufen lassen:
  `python -m pytest tests/ -q -m "not local_env"` unter Python 3.13.
- Gemergt wird nur auf Uzis Wort. Das PR gate sperrt die Pfade aus `.github/pr-gate-policy.json`, Näheres in `CI.md`.
- Server tim-core-01: Schreibende oder sudo-Schritte führt nur Uzi aus. Agenten liefern dafür fertige Befehle.
- Keine erfundenen Ergebnisse. Jede Zahl braucht eine Quelle (Datei, Commit, Messung). Unsicheres wird als unsicher markiert.
- Uzi schreibt Deutsch. Antworten und Doku sind auf Deutsch.

**Arbeitsteilung, damit nichts doppelt passiert:**
- Plan ändern: PR auf diese Datei, kleine Schritte, je Schritt ein Eintrag im Änderungsprotokoll.
- Code-Aufgaben: als GitHub-Issue nach `docs/ISSUE_WORKFLOW.md` anlegen. Den Rest übernimmt der Mac-Issue-Worker.
- Offene Fragen an Uzi stehen in Abschnitt 5 (F1 bis F11). Bitte nicht selbst beantworten.

**Stand am 17.10.2026:**
- 8 V2-Blocker (B01 bis B08) sind offen. Die Belege stammen vom August und wurden seitdem nicht neu gemessen.
- Der nächste Schritt ist V1: den Ist-Stand auf dem Server nur lesend neu messen, mit `scripts/v2_readiness_audit.py --no-write`. Das übernimmt die Claude-Sitzung mit Serverzugang, sobald der Server wieder erreichbar ist. Die Ergebnis-Artefakte kommen danach per PR.
- Größtes Risiko sind Netzausfälle am Router. Sie setzen das etwa 34 Tage lange Qualifizierungsfenster zurück.
- Offen bei Uzi: F8 (kein Echtgeld in V2 bestätigen) und F10 (Rollen für die Freigaben).

---

# TIM Gesamtplan: von heute bis "fertig"

Stand: 17.10.2026. Version 0.5, Ziel jetzt V2-Trading-Version (Abschnitt 0). Ursprünglich 06.10.2026, Version 0.2 (Entwurf, wird im Thread "TIM durchplanen bis fertig" mit Uzi weiterentwickelt).
Grundlage, gelesen und nicht neu erfunden: Issue #82 (Master-Vision mit Definition of Done),
`docs/autonomous_trader/IMPLEMENTATION_ROADMAP.md`, `DEBIAN_MAC_OPERATING_PLAN.md`, `AUTONOMY_LEVELS.md`,
`TIM_V2_BLOCKER_REGISTER.md`, `CI.md` (alle auf `platform-main` 7947052), die Pläne unter `plaene/`,
`issue-resolution/`, `server/`, `reviews/wochenuebersicht-prs-2026-10-05.md`, Projektspeicher,
25 offene Issues und 19 offene PRs (GitHub, 06.10. 00:45 UTC) und die laufenden Threads.

Harte Grenzen für jede Phase: kein Echtgeld, nur OBSERVE/Papier, keine Zugangsdaten in Dateien oder Commits.
Dieser Plan setzt nichts um. Uzi startet die Umsetzung phasenweise.

---

## 0. Ziel seit 17.10.2026: die V2-Trading-Version

Uzi im Projekt-Chat, 17.10. 09:38 UTC: „V2 Tradind version von TIM als ziel“. Der Abschnitt ordnet die Phasen unten auf
dieses Ziel aus. Die Belege sind aus dem Repo gelesen (`platform-main` 9663582). Was zum Stand seit dem 12.10. hier steht,
kommt aus dem Projektspeicher und wurde nicht neu gemessen.

### 0.1 Was „V2“ im Repo heißt

- **Fahrplan** (`docs/tim_v2/roadmap.md`, `milestones.md`): V2.0 bis V2.9, danach V3.0. Zwei Meilensteine betreffen den Handel:
  - **V2.8 Paper Trading**: ein isolierter Fake-Ausführungsadapter mit Kill-Switch, Abgleich und Vorfall-Abläufen. Abgenommen ist er mit dem technischen Nachweis, dass kein echter Order-Endpunkt erreichbar ist.
  - **V2.9 Shadow Trading**: Live-Daten bei technisch abgeschaltetem Order-Pfad. Gemessen werden Latenz und Entscheidungsqualität. Abgenommen ist er mit dauerhaft null Orders plus Governance-Freigabe.
- **Echtgeld gehört nicht zu V2.** `docs/tim_v2/goals.md` trennt Research, Simulation, Paper, Shadow und Live als eigene Bereiche und hält fest: „No milestone automatically authorizes the next execution mode.“ Die V2-Trading-Version heißt also **Paper plus Shadow, ohne Echtgeld**. Für Live bräuchte es ein eigenes Programm nach V2, siehe F8.
- **Eintrittsschranke ist das V2-Readiness-Gate** (`TIM_V2_READINESS_CHECKLIST.md`, `TIM_V2_BLOCKER_REGISTER.md`): Es gibt 8 Blocker, alle OPEN. Die Belege stammen vom 01.08. (`artifacts/v2_readiness/v2_readiness_matrix_final.json`) und vom 03.08. (`artifacts/v2_completion/implementation_state.json`):

| Blocker | Inhalt | Stand August |
|---|---|---|
| V2-B01 | Durchgehende Abdeckung ≥ 95 % | 67,3 % (9.487 von 14.087 Minuten) |
| V2-B02 | jede Datenlücke erklärt, keine offene | 63 offene Lücken |
| V2-B03 | Artefakt-Audit | FAIL |
| V2-B04 | Research-Qualität | FAIL |
| V2-B05 | Herkunft der Alt-Historie | unvollständig |
| V2-B06 | manuelle wissenschaftliche Prüfung durch einen Menschen | fehlt |
| V2-B07 | Governance-Freigabe HC-1.0 | fehlt |
| V2-B08 | Verantwortungsmatrix (RACI) mit Namen | fehlt |

- **Warum das Control Center rot zeigt:** `src/dashboard/operations.py` liest diese eingecheckten Artefakte vom August, nicht den Server von heute. Rot heißt also „seit August nicht neu gemessen“, nicht unbedingt „heute schlecht“.
- **Qualifizierungskampagne** (`artifacts/v2_completion/qualification_preregistration.json`): Sie ist vorab registriert, wurde aber nie gestartet.
  - Damit sie starten kann, müssen diese Bedingungen grün sein: PostgreSQL-Sicherheit, sicheres Stoppen, dauerhafte Ingestion, Cursor und Outbox, Watchdog, Log-Rotation, volle Suite, eingefrorene Konfiguration und eingefrorener Commit.
  - Abgeschlossen ist sie mit ≥ 95 % Abdeckung, 1.000 gültigen, nicht überlappenden Einheiten, Negativ- und Neutralkontrollen, Regime-Abdeckung, bestandenem Replay- und Lookahead-Test und einer echten menschlichen Freigabe.
  - Hochgerechnet dauert sie etwa 48.500 Minuten, rund **34 Tage ohne Ausfall**.

### 0.2 Was sich seit August getan hat (laut Speicher, nicht neu geprüft)

- Der Server läuft seit 01.10. live aus `/opt/tim`. Gemergt sind die Catch-up-Fixes #145 und #159, der Kerzen-Nachbau #178 und #183 und die Backup-Rotation #190. Der Checkup ist seit 14.10. installiert, Melden ist aus.
- Seit 14.10. kommt es zu Netzausfällen über den pfSense-Router: 64 Stück bis 16.10. Für das 34-Tage-Fenster ist das das größte einzelne Risiko.
- Das Control Center auf dem Mac misst 24 h Abdeckung 100 %. Das ist die Mac-Runtime und zählt nicht als Qualifizierung.
- CI läuft auf dem eigenen Runner, und der Mac-Issue-Worker arbeitet Code-Issues ab. Am Engpass ändert das nichts: Der liegt bei Datenkontinuität und menschlicher Prüfung, nicht bei Code.

### 0.3 Reihenfolge bis zur V2-Trading-Version

| Schritt | Inhalt | Phase unten | V2-Bezug | Wer |
|---|---|---|---|---|
| V1 | V2-Readiness neu messen: `scripts/v2_readiness_audit.py --no-write` (nur lesend) auf Server-Daten mit neuem Cut-off, danach die Ergebnis-Artefakte per PR, damit das Control Center den Stand von heute zeigt | A/B | Ist-Stand B01 bis B05 | Mac-Sitzung lesend, PR aus der Cloud |
| V2 | Netz stabil: Ursache am Router (Chris), falls nötig USV oder zweiter Uplink; dazu die Netzausfall-Probe A2 | A | Voraussetzung für B01 | Uzi/Chris |
| V3 | Start-Bedingungen der Qualifizierung prüfen und grün machen (siehe 0.1) | A/B | Startfreigabe | Repo + Server |
| V4 | Governance: RACI mit echten Namen, Freigabeweg HC-1.0 (`TIM_V2_GOVERNANCE_APPROVAL_WORKFLOW.md`) | neu | B07, B08 | **nur Uzi** (F10) |
| V5 | Qualifizierungskampagne starten, etwa 34 Tage. Sie **ersetzt B3/B4**: gleiche Wartezeit, aber nach V2-Regeln | B | B01, B02 | Server |
| V6 | Parallel zu V5: Artefakt-Audit, Research-Qualität, Herkunft der Historie (H1 bis H3 liefern dafür) | B/H | B03 bis B05 | Repo |
| V7 | Manuelle wissenschaftliche Prüfung durch einen Menschen, danach V2 freigegeben | Abschluss B | B06 | **Mensch** |
| V8 | Plattformen V2.1 bis V2.7 sind die Pakete C, D und E: Wissensgraph = D1, Research Engine und Datensätze = H/E2, Orderflow = C, Evaluation = E3, Decision = D4/F1, Simulation = E2/F2-Replay | C/D/E | V2.1 bis V2.7 | Repo + Worker |
| V9 | **V2.8 Paper Trading** = F1 bis F4. Abnahme: Negativtest „kein echter Order-Endpunkt erreichbar“, danach 30 bis 60 Tage Dauerlauf | F | V2.8 | Server |
| V10 | **V2.9 Shadow Trading** = neue Phase S: Live-Daten, Order-Pfad technisch aus, Latenz und Entscheidungsqualität messen, Vorfall-Übungen | S (neu) | V2.9 | Server, Freigabe Uzi |

Phase S liegt nach F und vor G. „TIM fertig“ (Abschnitt 1) bleibt das inhaltliche Ziel. Die V2-Trading-Version ist erreicht, wenn V10 abgenommen ist.

**Feste Wartezeiten bis dahin:** rund 34 Tage Qualifizierung (V5), 30 bis 60 Tage Paper (V9) und ein Shadow-Fenster, für das noch keine Länge festgelegt ist (siehe F11). Jeder längere Netzausfall setzt das jeweilige Fenster zurück. Deshalb kommt V2 (Netz) vor V5.

**Nächster Schritt:** V1, den Ist-Stand neu messen. Er ist nur lesend und klärt, wie weit B01 bis B05 heute wirklich offen sind.

---

## 1. Was heißt "TIM fertig"?

Uzi hat das in Issue #82 selbst festgelegt ("Definition of Done"). TIM ist fertig, wenn es

1. kontinuierlich reale Marktdaten verarbeitet,
2. daraus deterministische Marktbeobachtungen erstellt,
3. jede Analyse auf Evidenz zurückführen kann,
4. Gegenargumente systematisch prüft (Bull/Bear, Devil's Advocate),
5. Setup-Gültigkeit zeitlich und hierarchisch verwaltet,
6. externes Wissen (Broncx) versioniert integriert,
7. Community-Ideen gegen reale Marktdaten validiert,
8. Research-Setups reproduzierbar paper-simuliert,
9. seine Fehler und Unsicherheiten offen ausweist,
10. SHORT/MID/LONG getrennt und evidenzbasiert bewertet,
11. und keine reale Order ohne separate ausdrückliche Freigabe ausführt.

Ergänzend gilt das Erfolgskriterium aus der Roadmap: Paper Trading 30 bis 60 Tage ohne Integritätsfehler.

**Wichtig:** "Fertig" heißt nicht "profitabel". Das Research Lab (R4, 29.09.) hat keinen Edge gefunden.
TIM ist auch dann fertig, wenn es ehrlich zeigt, dass eine Idee nicht trägt. Echtgeld (Roadmap-Phasen 9 und 10,
Shadow und Limited Live) liegt ausdrücklich außerhalb von "fertig" und braucht ein eigenes Programm.

**Entschieden (Uzi, 06.10.2026):** Ziel ist **#82 komplett**, also auch MID und LONG. Die Historie dafür wird
heruntergeladen (Binance-Archiv), nicht live abgewartet. An den Regeln wird auf der Historie gearbeitet.

Damit das Anpassen der Regeln nicht zur Kurvenanpassung wird, gilt die Dreiteilung aus `docs/research_lab/PROTOKOLL.md` §3 (Spot-Archiv laut Protokoll erwartet ab 2017-08, Funding ab 2019-09):

| Datenteil | Zweck | Regel |
|---|---|---|
| Training (Archivbeginn bis 2022-12-31) | Regeln entwerfen und anpassen | beliebig oft |
| Validierung (2023-01-01 bis 2024-12-31) | Regel-Versionen vergleichen | jede geprüfte Variante wird im Register gezählt (Mehrfachtest-Korrektur) |
| Holdout (2025 bis heute) | einmaliger Endtest je Regel-Version | nur einmal, nach vorab registrierter Hypothese |
| Live ab Server (forward) | Bestätigung im Paper Trader | kann nicht überangepasst werden, darum bleibt sie Pflicht |

Was sich nicht herunterladen lässt und deshalb live gesammelt werden muss: Broncx-/Community-Beiträge vor
Feed-Start, eigene Beobachtungen und Research Cases von TIM selbst, Paper-Fills und die 30 bis 60 Tage Paper-Dauerlauf.
Orderbuch-Tiefe liegt im Archiv nur eingeschränkt vor (nicht geprüft).

---

## 2. Wo TIM heute steht

Höchste belegte Stufe laut `AUTONOMY_LEVELS.md`: **L1 (Research-Beobachtungen)**. Setups (L2) und Paper-Orders (L3) fehlen.

| #82-Baustein | Stand | Beleg |
|---|---|---|
| Daten sammeln (Binance Spot aggTrade, 1m-Kerzen) | läuft, aber nicht stabil: Lücken nach jedem längeren Netzausfall | Server live seit 01.10. aus `/opt/tim`; Kerzen standen am 03.10. und 05.10. still |
| Catch-up / Nachholen | drei Fixes: #145 (Resume, gemergt), #157 (Drossel, gemergt, Deploy läuft), #159 (WebSocket bleibt beim Nachladen am Leben, Draft, Merge läuft) | Threads "Neuem Repo-Plan folgen", "Binance-Reconnect und Watchdog" |
| Coverage-Nachweis (Gate ≥ 99,5 %) | nie erreicht, letzter Wert 60,7 %; V2-B01 bis B08 alle OPEN | `TIM_V2_BLOCKER_REGISTER.md` |
| Beobachtungen, Orderflow, Szenarien | gebaut (BOS, Orderflow-Engine, Szenario-Engine, Handelsplan 1,5R) | PR #120-#133 |
| Research Cases | gebaut, Server-Lauf fast fertig (validate wartet auf Uzis Satz) | Issue #3 zu, Thread "Research-Issue #3 erledigen" |
| Broncx-Wissen | Feed + Chartbild-Auswertung laufen auf dem Mac; noch kein versioniertes Regelwerk (Konzepte, Regeln, Gegenbeispiele) | PR #124, #127, #132 |
| Evidence Graph, Temporal Validity, Bull/Bear, Devil's Advocate | **fehlt** (keine Fundstelle in `src/`) | Code-Suche 06.10. |
| Community-Calls validieren (GoatHub) | Ansätze in `src/knowledge/goathub`, kein Validator, keine Caller-Statistik | Bauplan 29.09. |
| Strategie-Vertrag, Backtest mit Kosten | Research Lab R0-R4 fertig, Nullergebnis; Holdout 2025+ unberührt | PR #117, #118 |
| Risk Engine, Paper Trader | **fehlt**; `src/paper/automation.py` ist nur ein TEST_ONLY-Journal | `AUTONOMY_LEVELS.md` |
| SHORT/MID/LONG-Readiness | **fehlt** | #82 §14 |
| Dashboard | vorhanden (read-only), zeigt noch keine Setups/Gültigkeit/Gegenargumente | `src/dashboard` |
| Agenten-Plattform | Vertrag, Project Manager, Review, Monitoring, Task Engine gemergt; Auto-Merge-Pipeline gemergt, aber **inaktiv** | PR #114, #115, #119, #146-#150 |
| MCP | tim-graph gemergt (#153), tim-ops als #155 im Merge | Thread "MCP für TIM" |
| Selbstheilung M09 | P2-P10 (#13-#21) offen, #19 wartet auf #18 | Projektspeicher |

---

## 3. Phasen

Reihenfolge folgt den Gates aus #82 und der Roadmap. Jede Phase hat ein Abnahmekriterium. Eine Phase gilt erst
als bestanden, wenn der Nachweis sichtbar ist (Bericht, Test, Zahl), nicht weil Code existiert.

### Phase A: Aufräumen und Server stabil (läuft jetzt)

Ziel: Der Server schreibt Live-Kerzen und übersteht einen Netzausfall ohne Handarbeit.

| Paket | Inhalt | Abnahme | Wer/wo |
|---|---|---|---|
| A1 | Cutover mit #157 und #159 nach `/opt/tim`, danach `tim_catchup.py --open-gaps`, `tim-backfill` neu starten | neueste 1m-Kerze ≤ 180 s alt; offene Lücken 0 oder erklärt | Thread "Neuem Repo-Plan folgen" (läuft) |
| A2 | Netzausfall-Probe: Uplink kurz trennen bzw. Binance-Socket abbrechen, ohne Eingriff warten | Kerzen laufen nach Rückkehr von allein weiter, Lücke wird von allein geschlossen | neu, nach A1 |
| A3 | sudo-Regel `90-tim-bootstrap` löschen, `sudo -n true` muss scheitern | Prüfbefehl FAIL wie erwartet | Thread "Neuem Repo-Plan folgen" |
| A4 | Issue #3 abschließen (apply, validate PASS, Zahlen ins Issue) | validate PASS | Thread "Research-Issue #3", wartet auf Uzis Satz |
| A5 | #155 tim-ops mergen | CI grün, gemergt | Thread "MCP für TIM" (läuft) |
| A6 | Repo-Hygiene: Dependabot #103-#110 (pip einzeln, Actions gesammelt), alte PRs #10, #66, #72, #80, Pilot-PRs #91/#93/#95 schließen oder neu aufsetzen, 32 gemergte Branches löschen, flaky Test #131 | offene PRs nur noch aktive Arbeit | neu |
| A7 | `TIM full suite` grün machen und zum Pflicht-Check erheben (laut CI.md eigenes Paket) | Suite grün auf platform-main | neu |

### Phase H: Historie herunterladen (neu, startet sofort, parallel zu A und B)

Läuft auf Uzis Mac, weil die Cloud `data.binance.vision` blockiert. Vorhanden: `scripts/research_lab_fetch.py`
(Klines und Funding, sperrt Holdout-Monate). Fehlt: aggTrades, Open Interest/Metrics.

| Paket | Inhalt | Abnahme |
|---|---|---|
| H1 | Inventar: welche Archive gibt es für BTCUSDT (Spot und USD-M) ab wann (Klines, aggTrades, Funding, Metrics/OI, Orderbuch) | Tabelle mit Startmonat und Größe je Datensatz |
| H2 | Downloader um aggTrades und Metrics erweitern (Prüfsummen, Lückenbericht, Holdout-Sperre bleibt) | Test grün; Vollständigkeitsbericht je Monat |
| H3 | Historie laden: Klines und Funding komplett, aggTrades zuerst für Training/Validierung | Lückenbericht ohne unbekannte Lücke |
| H4 | Historische Daten durch dieselbe Feature- und Beobachtungs-Pipeline wie live schicken (Replay), getrennt von der Live-Datenbank | gleiche Eingabe live wie historisch = gleicher Hash |
| H5 | Kopie für den Server (Snapshot), damit Paper Trader und Backtest dieselben Daten sehen | Hash-Abgleich Mac = Server |

### Phase B: Datenbetrieb nachweisen (Gate 0/1, Roadmap Phase 1)

Ziel: belegte Datenkontinuität. Ohne sie ist jede spätere Auswertung wertlos.

| Paket | Inhalt | Abnahme |
|---|---|---|
| B1 | 72 h Beobachtung nach A2 | keine stille Lücke, Health GRÜN |
| B2 | Alarm, kostenlos, ohne neues Konto: `tim_server_health` erkennt den Fehler (deterministisch). Ein Melder sammelt Journal-Auszug, Unit-Status, Commit, Lückenbericht und öffnet bzw. aktualisiert genau ein GitHub-Issue je Vorfall (Dedupe wie #68). Die GitHub-App schickt die Push-Nachricht aufs Handy | Testfehler erzeugt genau ein Issue mit Log, zweiter Lauf kein Duplikat |
| B2a | Qwen-Diagnose als Kommentar am Vorfall-Issue: Qwen läuft auf dem Server (Ollama, CPU), liest Log und betroffenen Code, schreibt Ursache und Vorschlag. Nur lesend, repariert nichts | Kommentar nennt Datei/Zeile; kein Schreibzugriff auf Repo oder Dienste |
| B2b | Außenwache: Fällt das Netz aus, kann der Server nichts senden. Der Mac (oder ein GitHub-Zeitplan) prüft den Herzschlag des Servers und meldet, wenn er fehlt | Netzstecker-Test löst Meldung aus |
| B2c | Alten Qwen-Worker unter `/srv/tim` (läuft doppelt, nicht im Repo) abschalten, neuen nur aus `/opt/tim` betreiben | genau ein Qwen-Dienst aktiv |
| B3 | Messfenster vorab deklarieren (`scripts/tim_server_campaign.py`), Annahme 14 Tage | Deklaration committed vor Fensterbeginn |
| B4 | Fenster laufen lassen, Coverage unabhängig nachrechnen | ≥ 99,5 % Coverage, keine unbekannte Lücke, Provenienz je Zeile; schließt V2-B01/B02 |
| B5 | Kerzen aus DEFERRED-Outbox für alte Lücken erzeugen; Market-Feeds-Code (`venue_trades`) vom Server ins Repo | Lückenbericht ohne "UNKNOWN"; Feed-Code im Repo |
| B6 | Zusatzdaten je nach F4 (Funding, Open Interest, Mark Price, Orderbuch) mit gleichen Quality Gates | eigener Collector je Quelle, Coverage-Bericht |

Während B4 läuft (14 Tage Wartezeit), werden C und D auf dem Mac gebaut. Die Daten brauchen sie erst zur Abnahme.

### Phase C: Features und Beobachtungen festziehen (Gate 2/3)

| Paket | Inhalt | Abnahme |
|---|---|---|
| C1 | Feature-Register mit Version und Hash je Feature | gleiche Daten + gleiche Version = gleicher Hash (Golden Replay) |
| C2 | Observation-Schema nach #82 §5 (u. a. `born_at`, `evidence_refs`, `invalidation_conditions`, `parent_context`, Versionen) für alle bestehenden Regeln | Migration + Tests; Lookahead-Test PASS |
| C3 | Datenqualitäts-Sperre: keine Beobachtung bei unzureichender Qualität | Ablehnungstests grün |

### Phase D: Analyse-Intelligenz (Gate 4/5, der eigentliche Kern von #82)

| Paket | Inhalt | Abnahme |
|---|---|---|
| D1 | Evidence Graph: Setup verweist auf Struktur-, Volumen-, Orderflow-, Liquiditäts-, HTF/LTF-Evidenz | jede Analyse bis auf Datenzeilen rückverfolgbar |
| D2 | Temporal Validity: `born_at`, `half_life`, `expires_at`, Zustände ACTIVE … EXPIRED | Verfall deterministisch, Replay gleich |
| D3 | Hierarchische Invalidierung (4H kippt → 1H/15m-Setups kippen mit) | Eltern-Kind-Tests |
| D4 | Bull/Bear + Devil's Advocate verpflichtend je These | kein Case ohne Gegenseite (Test) |
| D5 | Broncx-Wissenssystem: Konzepte, Regeln (klassifiziert), Beispiele, Gegenbeispiele, Quellen; Feed-Beiträge werden zu Cases | jede codierte Regel mit Test und Gegenbeispiel |
| D6 | Community-Calls: Parser, Nachprüfung gegen Marktdaten (MFE, MAE, R), Caller-/Setup-Statistik | Calls "gemessen, nicht geglaubt"; Broncx als erster Caller |
| D7 | Dashboard: Setups, Gültigkeit, Bull vs Bear, fehlende Evidenz | Seite zeigt es mit echten Daten |

### Phase E: Strategie und harte Validierung (Roadmap 4-6)

| Paket | Inhalt | Abnahme |
|---|---|---|
| E1 | Genau ein maschinenlesbarer Strategie-Vertrag (Einstieg, Invalidierung, Ausstieg, Risiko), abgeleitet aus D-Setups | jeder hypothetische Trade rekonstruierbar |
| E2 | Neue Hypothesen vorab registrieren (Research-Lab-Protokoll, Änderungsprotokoll), Backtest mit Gebühren/Slippage/Funding | Look-ahead-Audit PASS |
| E3 | Walk-Forward/OOS mit vorab festgelegten Splits; Holdout 2025+ erst ganz am Ende und nur einmal | Kriterien vorab erfüllt oder sauber verworfen |

Risiko: Auch die nächste Runde findet keinen Edge. Dann geht trotzdem eine Strategie in Phase F, als
Messobjekt für den Paper Trader (Ziel ist technische Integrität und ehrliche Messung, nicht Gewinn).

### Phase F: Risk Engine und Paper Trader (Gate 6, Roadmap 7-8)

| Paket | Inhalt | Abnahme |
|---|---|---|
| F1 | Risk Engine mit Vetorecht, Limits, Kill-Switch (Papier-Parameter z. B. 0,25 % je Trade, 1 % Tag, max. 3 Trades) | Denial-/Bypass-Testsuite grün |
| F2 | Paper Trader: virtuelle Position, Order-Lebenszyklus, Fills/Rejects, Journal, Gebühren-/Slippage-Modell | reproduzierbarer Replay; kein Code-Pfad kann echte Orders senden (Negativtest) |
| F3 | Metriken: Setup-Qualität ≠ Ausführung ≠ Ergebnis getrennt (#82 §11) | Bericht zeigt alle Pflichtmetriken |
| F4 | Paper-Dauerlauf auf dem Server | **30 bis 60 Tage ohne Integritätsfehler** |

### Phase G: Horizonte bewerten und Abschluss

| Paket | Inhalt | Abnahme |
|---|---|---|
| G1 | Readiness-Vertrag je Horizont (maschinenlesbar, Modell darf nicht hochstufen) | Status-JSON je Horizont |
| G2 | SHORT bewerten | Gate 7 PASS → **TIM 1.0 fertig** |
| G3 | MID bewerten: Walk-Forward über Regime auf Historie (H), bestätigt durch Live-Paper | Gate 8 |
| G4 | LONG bewerten: Marktzyklen auf Historie (H; USD-M ab 2020-01 belegt, Spot vermutlich länger, H1 klärt das), Live nur als Bestätigung des aktuellen Zyklus | Gate 9 |
| G5 | Abschlussbericht Reproduzierbarkeit/Governance, Betriebshandbuch | Bericht liegt vor → **TIM fertig** |

Advisory Review (Gate 10), Shadow und Live gehören nicht zu "fertig".

### Nebenspur: Werkzeuge für die Entwicklung (parallel, nur so viel wie nötig)

Leitplanke aus Uzis Betriebsplan: "Engpass ist Edge, nicht Governance". Werkzeugarbeit nur, wenn sie eine Phase oben beschleunigt.

| Paket | Inhalt | Empfehlung |
|---|---|---|
| W1 | Auto-Merge-Pipeline: Code gemergt (#146, #147, #150, #160), Controller aus (nur Handstart, `enabled: false`, `dry_run: true`). Nächste Schritte: Gate-Lauf, Dry-Run-Matrix, Rulesets im Testrepo, Worker-/Merger-App, `timrunner` + 4a, Pilot (`docs/AUTO_MERGE_ROLLOUT.md`) | nach Phase A; Merge bleibt beim Menschen (F2) |
| W2 | MCP M2 (Codex/Mac), M4 (Router + Pipeline nutzen tim-ops), Postgres-Nur-Lese-Rolle | nach A5 |
| W3 | #68 Live-Lauf im echten Repo, Restbefunde #134 | klein, wenn Token bereit |
| W4 | Selbstheilung M09 (#13-#21) | **einfrieren** bis Phase B bestanden; die Catch-up-Fixes lösen das akute Problem direkter |
| W5 | Obsidian: launchd um pr_drafts erweitern, Entscheidungsnotizen | bei Gelegenheit |
| W6 | Server-Altlasten: Qwen doppelt (#75/#76), `/srv/tim` aufräumen, Tailscale/T.I.M.E.C. (#77), #78/#79/#88 | nach B1, nur über Uzi am iDRAC |

---

## 4. Abhängigkeiten (kurz)

```
A (Server stabil) ─► B1-B3 ─► B4 (14 Tage Messfenster) ─────────────┐
                         │                                           ▼
                         └─► C (Features) ─► D (Analyse) ─► E (Strategie) ─► F (Risk + Paper) ─► F4 (30-60 Tage) ─► G
H (Historie, ab sofort) ─► H4 Replay braucht C ─► Regeln in D/E auf Historie entwickeln ─► G3/G4 auf Historie
W1-W6 laufen nebenher und blockieren nichts davon.
```

Feste Wartezeiten, die sich nicht durch mehr Bauen verkürzen lassen: 72 h (B1), 14 Tage Messfenster (B4),
30 bis 60 Tage Paper (F4). Für MID/LONG ersetzt die Historie aus H das lange Warten auf Live-Daten. Jeder Datenausfall im Messfenster setzt es zurück.

---

## 5. Offene Entscheidungen von Uzi

| Nr. | Frage | Empfehlung | Blockiert |
|---|---|---|---|
| F1 | ~~Was ist zuerst "fertig"?~~ **Entschieden 06.10.: #82 komplett, Historie wird heruntergeladen** | | |
| F2 | ~~Merge ohne Menschen?~~ **Entschieden 06.10.: Nein, vorerst. CI.md gilt (Mensch genehmigt, GitHub merged). Neu entscheiden erst nach Pilot mit Rulesets und getrennten Apps.** | | |
| F3 | ~~Alarmkanal?~~ **Vorschlag 06.10. nach Uzis Idee: GitHub-Issue mit Log + Qwen-Diagnose (kostenlos, Push über GitHub-App), dazu Außenwache vom Mac. Telegram nur, falls GitHub-Pushes nicht reichen.** | | B2 |
| F4 | Nur Binance Spot, oder auch Futures-Daten (Funding, OI, Mark Price) bzw. Bybit? | Spot für Orderflow, USD-M für Funding/OI, kein zweiter Börsenplatz bis Phase G | B6, H1-H3, E2 |
| F5 | Messfenster 14 Tage und Coverage-Ziel 99,5 % bestätigen | ja | B3 |
| F6 | M09 Selbstheilung einfrieren bis Phase B? | ja | W4 |
| F8 | V2-Trading = Paper (V2.8) plus Shadow (V2.9), **kein Echtgeld**. Echtgeld nur als eigenes Programm nach V2 und nur auf deinen ausdrücklichen Wunsch | ja | Abschnitt 0 |
| F9 | Abdeckungsziel: V2 verlangt ≥ 95 %, dieser Plan hatte 99,5 % (F5). Vorschlag: 95 % als V2-Gate, 99,5 % als Betriebsziel | ja | V5 |
| F10 | Rollen für die RACI-Matrix (V2-B08): Scientific Lead, Integrity Lead, QA Lead, Governance Lead. Unabhängige Prüfung darf nicht dieselbe Person sein, die gebaut hat | Uzi: Governance + Scientific; Chris: Integrity + QA | V4, V7 |
| F11 | Länge des Shadow-Fensters (V2.9 nennt keine Zahl) | 30 Tage, nach bestandenem Paper | V10 |
| F7 | ~~Alte PRs schließen?~~ **Erledigt: #91/#93/#95 am 12.10., #10/#66/#72/#80 am 14.10. auf Uzis „schließen“** | | |

---

## 6. Größte Risiken

1. **Netz am Standort** (pfSense-Ausfälle 30.09. und 02.-05.10.): Jeder längere Ausfall kostet das Messfenster. Gegenmittel: A2 beweisen, Alarm (B2), ggf. USV/zweiter Uplink (Hardware, Uzi).
2. **Überanpassung an die Historie**: Regeln so lange drehen, bis die Vergangenheit passt. Gegenmittel: Dreiteilung Training/Validierung/Holdout, jede Variante im Register gezählt, Live-Paper als letzte Prüfung.
3. **Kein Edge**: Wahrscheinlich, siehe R4. Gegenmittel: "fertig" ist an ehrliche Messung gebunden, nicht an Gewinn.
4. **Werkzeug-Sog**: Pipeline, Selbstheilung und MCP können die Kernphasen C-F verdrängen. Gegenmittel: Nebenspur-Regel oben.
5. **Mac-gebundene Schritte**: Downloads, Bot, Codex/GLM, RC-Sitzungen hängen an Uzis Mac und an seinem Wortlaut für den Sicherheitsfilter. Gegenmittel: Server-Schritte gesammelt pro Phase freigeben.
6. **Repo-Umzug**: Teile kennen nur den alten Namen (live_check, legacy). Gegenmittel: in A6 prüfen.

---

## 7. Plan lebendig halten

- Jeder Thread, der ein Paket abschließt, trägt hier unten ins Änderungsprotokoll ein: Datum, Paket, Nachweis (PR/Commit/Bericht).
- Paketstatus in den Tabellen oben nur über das Änderungsprotokoll ändern, nie stillschweigend.
- Der Thread "TIM durchplanen bis fertig" zieht den Plan nach, wenn Uzi eine Frage aus Abschnitt 5 beantwortet.

## Änderungsprotokoll

| Datum | Änderung | Nachweis |
|---|---|---|
| 2026-10-06 | Version 0.1 angelegt | dieser Thread |
| 2026-10-06 | v0.2: F1 entschieden (#82 komplett), Phase H Historie herunterladen, Dreiteilung gegen Überanpassung, Risiko Überanpassung | Uzi im Thread, 11:16 UTC |
| 2026-10-06 | v0.3: F2 entschieden (kein Merge ohne Menschen, vorerst); W1-Stand nachgezogen (#159, #160, #161 gemergt) | Uzi im Thread, 23:28 UTC |
| 2026-10-06 | v0.4: Alarm über GitHub-Issue + Qwen-Diagnose auf dem Server (B2-B2c), Uzis Vorschlag | Uzi im Thread, 23:30 UTC |
| 2026-10-17 | v0.5: Neues Ziel V2-Trading-Version (Uzi 09:38 UTC). Abschnitt 0: V2 im Repo = Paper (V2.8) + Shadow (V2.9), kein Echtgeld; 8 V2-Blocker offen (Belege August); Reihenfolge V1-V10, neue Phase S (Shadow); Fragen F8-F11; F7 erledigt | dieser Thread |
| 2026-10-17 | v0.6: Plan ins Repo verlegt (docs/TIM_GESAMTPLAN.md) mit Arbeitsregeln für ChatGPT/Codex, Uzi 09:53 UTC | PR |
