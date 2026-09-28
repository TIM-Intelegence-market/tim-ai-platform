# Mission 09.1 — Zwischenabnahme

Datum: 9. September 2026. **PARTIAL / IN_PROGRESS**, keine Produktionsfreigabe.

| Nachweis | Ergebnis |
|---|---|
| Bugfixer-Komponententests | 50 PASS |
| Breite TIM-Suite | 920 PASS, 5 FAIL, 13 SKIP; 99,79 s |
| Gezielte Wiederholung der 5 Fehler | 1 PASS, 4 FAIL; 11,17 s |
| Event-Replay / historischer Cutoff | PASS im Foundation-Scope |
| Abrupter Prozessabbruch + SQLite-Rollback | PASS |
| Worker-Neustart in zweitem Prozess | PASS |
| Produktions-DB / Queue-Integrität | Nicht geprüft |
| Automatische Rotationsübernahme | Offen; aktueller Worker stoppt sicher |
| Runtime-Shadow / vollständige Observability | Offen |
| Gesamtabnahme / Release | Nicht erteilt |

Beim Start der breiten Suite waren 48 Bugfixer-Tests gesammelt; zwei weitere
Tests bestanden anschließend separat. Die Summen sind daher keine zwei
identischen Suite-Läufe.

Vier Fehler bleiben reproduzierbar: Der vorhandene Keychain-Helfer übergibt im
Mock-Test das Testpasswort als Prozessargument; drei Graphify-Tests erwarten einen
deaktivierten Standard, erhalten aber eine aktive Konfiguration. Die betroffenen
bestehenden Quell- und Konfigurationsdateien haben keinen Git-Diff. Es wurde weder
ein echtes Passwort geschrieben noch die lokale Graphify-Aktivierung verändert.

Der Snapshot-ID-Test bestand bei Wiederholung ohne parallele Quelländerungen.
Der erste Fehler kann durch während des breiten Laufs ergänzte Dateien beeinflusst
worden sein; eine bestätigte Produkt-Root-Cause liegt dafür nicht vor. Weitere
Scanner-Regressionen nur bei ruhendem Dateibestand ausführen.

Die breite Suite lief ohne übernommene TIM-/PG-/DB-/Credential-Variablen, mit
Testmodus und ohne PostgreSQL-Test-URL. DB-Tests wurden übersprungen; das ersetzt
keine Prüfung mit einer nachgewiesen isolierten PostgreSQL-Instanz.

Belege: `work/mission09_1/regression.xml`, `regression.log`,
`regression_summary.json`, `failure_recheck.log` und externe Missionsdatei
`.codex/MISSION_09_1_TEST_RESULTS.md` unter dem TIM-Elternordner.

Nächster Schritt: M09.1-E-003 — verlustlose Rotationsübernahme mit Regressionstest
für ungelesenen Altdateiinhalt; danach die offenen Tasks im Ledger. Weder
Fehlerzählung noch ein Dry-Run gelten als verifizierte Reparatur.


## Fortsetzung — Rotation, Stacktraces und Evidence

Neuer Teststand: **79 Bugfixer-Tests plus 30 angrenzende Regressionstests = 109 PASS**
in 0,77 s (Exit 0; Deprecation-Warnungen von pytest-asyncio/Python). Befehl:

```sh
.venv/bin/python -m pytest tests/bugfixer tests/test_collection_error_classification.py tests/test_database_safety.py tests/test_headless_recovery_cli.py tests/test_outbox_terminal_recovery.py -q
```

Abgedeckt: alter Dateirest vor Generationenwechsel; gebundener Seal bei Neustart;
Dateiänderung während Übernahme; falscher oder veränderter Nachfolger;
Checkpointfehler mit Rollback; gesperrte komprimierte/copytruncate-Fälle;
persistierte bereinigte Python-Tracebacks; immutable Evidence-Veröffentlichung,
Manipulations- und Secret-Erkennung; CLI-Export und historisches Replay.

Nur künstliche lokale Logdateien/SQLite und vorhandene isolierte Mock-Tests.
Keine Produktivaktivierung. Die oben dokumentierte breite Suite wurde nicht
wiederholt; ihre bestehenden vier reproduzierbaren Fehler bleiben offen.

Nächster Task: M09.1-G-004 — minimale isolierte Defekt-Reproduktionsfixtures;
die bereits vorhandene Event-Wiedergabe ist kein Root-Cause-Nachweis.

## P0-Abschlussprogramm — isolierter Datenbanklauf

Neue vollständige Suite mit PostgreSQL 18.4: **980 PASS, 4 FAIL, 0 SKIP**,
63,18 s (Exit 1). Quelle: `work/mission09_1/isolated_postgres_tests.xml`.
Die Instanz gehörte ausschließlich diesem Lauf; Datenverzeichnis und Datenbankname
wurden vor Tests überprüft und der Server wurde danach beendet. Dies bestätigt
Testisolation, nicht die Integrität der produktiven TIM-Daten.

Der Guard-Fix wurde durch neue Fehlertests begründet: Runtime-identische URL bei
testähnlichem Datenbanknamen sowie drei DSN-Zielüberschreibungen wurden zuvor
akzeptiert. Nun scheitern sie vor Connection/Pool-Erstellung. Erlaubt bleibt der
validierte isolierte search_path. Bestehender Nicht-Test-Runtimepfad unverändert.

Die vier verbleibenden Fehler betreffen ausschließlich Credential-Transport
(1) und die aktiv eingecheckte Graphify-Konfiguration gegenüber den Tests für
einen deaktivierten Standard (3). Keine Änderung der Graphify-Aktivierung.

## 2026-09-09T20:50:14.925483+00:00
Implemented minimal metrics_snapshot active-status WHERE predicate in src/data_ingestion/durable.py; no index/migration or runtime activation. Exact-schema tests cover empty/completed-only/mixed statuses and oldest active age, quarantine counts. Initial full run 1003 PASS/2 FAIL exposed invalid newly created COMPLETED fixture rows; fixed fixtures by supplying required completed_at/output_hash, preserving DB constraints. Final full isolated suite 1005 PASS, zero failed/skipped, 66.53s; own PostgreSQL stopped. Evidence work/mission09_1/isolated_postgres_1788986892522703000_summary.json and _tests.xml; failed run retained as isolated_postgres_1788986788401045000. Benchmark speedup applies only synthetic SQL experiment, not production throughput. No production data/queues/attempts/runtime touched. Next: audit P0 required gates against current evidence (K, L002/L003/L004/L005/L008), distinguish isolated gate verification from runtime readiness, and prepare remaining targeted acceptance; handler profiling remains a P1 performance task. Do not keep P0 indefinitely open solely for P1 production catch-up performance. Mission remains PARTIAL until its own required evidence reviewed.
