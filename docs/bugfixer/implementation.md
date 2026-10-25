# Bugfixer — Bedienung und Implementierungsstand

Stand: 9. September 2026. Foundation in Entwicklung, keine Produktionsfreigabe.

## Bedienung

Aus dem TIM-Code-Repository mit dem vorhandenen Python-Environment:

```sh
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 observe --source /explicit/errors.log
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 status
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 list --limit 100
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 inspect INCIDENT_ID
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 classify INCIDENT_ID
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 reproduce INCIDENT_ID --cutoff 2026-09-09T00:00:00Z
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 remediation-dry-run INCIDENT_ID --registry schemas/bugfixer/remediations.v1.json
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 verify
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 report
```

Pfade sind Platzhalter. `observe` liest einmal höchstens 200 vollständige Zeilen.
`--follow` pollt mit einer Sekunde Abstand bis SIGTERM/SIGINT. Ein Fehler beendet
den Lauf; der letzte bestätigte Cursor bleibt bestehen. Noch keinen Dienst oder
Scheduler dafür aktivieren. Bisher wurde ausschließlich mit künstlichen Testlogs
gearbeitet. Der Observer darf niemals seine eigene Statusausgabe als Quelle lesen.

## Speicherung und Verarbeitung

SQLite enthält nur redigierte Muster, Klassifikation, Lifecycle-Historie,
Fehleranzahl und Lesecursor. Ein Incident entspricht SHA-256 des versionierten
kanonischen Musters. Zeitstempel und UUIDs in Meldungen werden normalisiert;
fachliche Zahlen und Fehlercodes bleiben erhalten. Mehrfachmeldungen erhöhen die
Zähler; Einzelkopien werden unterdrückt. `suppressed_count` zählt unterdrückte
Evidence-Kopien, nicht verlorene Eingangszeilen.

Neue Fehler durchlaufen NEW, NORMALIZED und CLASSIFIED. Unbekannte Muster werden
ESCALATED; Integritätsverletzungen werden SAFE_STOP. Dieses SAFE_STOP ist der
Incident-Zustand; der Observer hat keine Berechtigung, TIM-Dienste anzuhalten.
Manuelle Lifecycle-Übergänge benötigen Evidence-Text. Eine bloße Transition ist
kein technischer Beweis einer Reparatur; spätere Remediation-Verifikation muss
Testnachweise prüfen. Rekurrenz nach RESOLVED öffnet INVESTIGATING erneut.

## Grenzen

- Normales Polling stoppt bei geänderter Dateiidentität. `reconcile-rotation`
  verarbeitet einen mit Seal bestätigten, abgeschlossenen Vorgänger vollständig.
  Komprimierte Vorgänger, copytruncate und fehlende Generationen bleiben gesperrt.
- Ein 256-Byte-Anker prüft die Nähe des Cursors. Er beweist nicht, dass ein
  gleichzeitig schreibender oder kopierend rotierender Prozess keine früheren
  Bytes ausgetauscht hat. Vollständige Rotationskoordination bleibt offen.
- Standard-Python-Tracebacks werden über Polls, Neustarts und bestätigte
  Rotationen hinweg zusammengeführt (maximal 128 Zeilen / 64 KiB). Andere
  mehrzeilige Formate bleiben zeilenweise; Exception-Groups benötigen eine eigene
  Erweiterung. Private-Key-Blöcke bleiben über Polls hinweg unterdrückt.
- CLI-Reproduktion prüft nur deterministische Fehlerverarbeitung mit Zeitlimit.
  Sie reproduziert keinen Produktionsdefekt und bestätigt keinen Codefix.
- Der neue explizite DB-Identitätsguard ist ein Bugfixer-Vertrag. Bestehende
  PostgreSQL-Laufzeitpfade wurden nicht umgebaut; deren Integration bleibt offen.
- Keine automatische Remediation, kein Codepatching, keine Handelsausführung.
- `verify` prüft Observer-Policy und SQLite-Integrität, keine PostgreSQL-, Queue-
  oder TIM-Laufzeitgates. `report` ist eine kompakte Zählerübersicht.
- Ingestion-Lag, Checkpoint-Alter und ein belastbarer Shadow-Betriebsnachweis
  fehlen noch. Externe bereinigte Evidence-Bundles sind implementiert.
  Deshalb Mission weiterhin nicht PASS.

## Rücknahme

Der neue Code wird vom bisherigen TIM-Start nicht importiert. Einen separat
 gestarteten Observer geordnet stoppen und seinen Speicher zur Diagnose behalten.
Keine Queue, Outbox, Produktionsdaten oder Versuchsanzahlen zurücksetzen.


## Bestätigte Rotationsübernahme

```sh
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 reconcile-rotation --source /explicit/errors.log --rotated-source /explicit/errors.log.1 --seal /explicit/rotation-seal.json
```

Seal-Format (Werte vom Produzenten/Operator verifizieren, niemals raten):

```json
{
  "schema_version": 1,
  "generation": 0,
  "old_identity": [123, 456],
  "successor_identity": [123, 789],
  "size": 1234,
  "sha256": "vollstaendiger-64-stelliger-sha256-des-abgeschlossenen-vorgaengers",
  "writer_closed": true,
  "contiguous_successor": true
}
```

Das Beispiel ist kein gültiger realer Seal. `generation` kommt aus dem vorhandenen
Checkpoint. Identitäten sind Device und Inode. SHA-256 und Größe beziehen sich
auf die gesamte Altdatei. Der Produzent muss den alten Writer geschlossen haben
und den lückenlosen direkten Nachfolger bestätigen; ein Hash beweist dies allein
nicht. Bei `complete=false` denselben Seal erneut verwenden. Erst nach
`complete=true` normales Polling fortsetzen. Ein anderer Nachfolger während einer
begonnenen Übernahme wird abgewiesen. Pro Batch maximal 200 Zeilen, pro altem
Segment maximal 64 MiB. Bei ungeklärter Rotation keine neuen Seals erfinden.

## Belege exportieren und wiedergeben

```sh
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 export-evidence INCIDENT_ID --directory /explicit/bundles
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 replay-evidence --bundle /explicit/bundles/DIGEST.json --cutoff 2026-09-09T00:00:00Z
```

Exportdateien enthalten bereinigte Ereignisse, keine Befehle oder ausführbaren
Pfade. Manipulierte, unbereinigte, übergroße oder über Symlinks gelieferte Belege
werden abgewiesen. Das Replay bleibt eine Prüfung der Ereignisverarbeitung;
eine isolierte Reproduktion des eigentlichen Defekts ist der nächste Arbeitsschritt.

## Seal erzeugen (Produzentenseite, #14)

Der Produzent (wer den Log-Schreiber besitzt) benennt das Log um, öffnet den Nachfolger, schließt den alten
Schreiber und erzeugt danach den Seal. Der Befehl misst nur Größe, Prüfsumme und Dateiidentitäten; die beiden
Zusicherungen gibt der Produzent ausdrücklich ab. Er öffnet den Incident-Store nicht, schreibt die Seal-Datei
einmalig mit 0600 und überschreibt nie.

```sh
.venv/bin/python -m src.bugfixer --store /explicit/observer.sqlite3 seal-rotation --rotated-source /explicit/errors.log.1 --successor /explicit/errors.log --generation 0 --out /explicit/rotation-seal.json --attest-writer-closed --attest-contiguous-successor
```

Abgelehnt werden: fehlende Zusicherung, copytruncate (gleiche Identität), Symlinks und ein Vorgänger, der mitten
in einem Datensatz endet. Eine logrotate-/launchd-Anbindung ist Betriebsarbeit (`ops/`) und nicht Teil davon.
Offen in #14 bleiben die Rate-Limit-Entscheidung und der Laufzeitnachweis auf dem Zielsystem.
