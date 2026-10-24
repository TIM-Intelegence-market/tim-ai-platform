# T02 und T14: Wiederherstellbarkeit, Sicherung, kontrollierter Rollout (Vorbereitung)

Stand 22.10.2026. Alles hier ist Vorbereitung. Keine Kopie, kein Restore, kein Rollout wurde ausgeführt.

## T02 Sicherung und Restore

### 1. Was heute vorliegt (abzugleichen auf dem Mac, nur lesend)

| Punkt | Stand | Prüfbefehl (lesend) |
|---|---|---|
| Täglicher Dump | 03:15 Ortszeit nach `~/Library/Application Support/TIM/backups/live`, 3 Stände [N]; PR #356 vereinheitlicht den Pfad für Health und Backup (offen) | `ls -la "$HOME/Library/Application Support/TIM/backups/live"` |
| Ordner `~/TIM-Backups` | existiert; Inhalt unbekannt | `ls -la ~/TIM-Backups` |
| Zweite Kopie außerhalb der internen SSD | **keine** bekannt | – |
| Restore geübt | **nein** (Server-Restore 20.10. war ein anderer Stand, `docs/RESTORE_STORAGE_2026-10-20.md`) | – |
| Ziele für Datenverlust/Wiederanlauf | nicht festgelegt | Betreiber (Uzi) legt vor dem Restore fest; Vorschlag: höchstens 24 h Datenverlust, Wiederanlauf unter 4 h |

### 2. Zweite Kopie (störungsarm, nur abgeschlossene Dumps)

Voraussetzungen: externe SSD am Mac, APFS verschlüsselt (Passwort im Schlüsselbund), Zielordner
`/Volumes/TIM-Backup/live/`. Platz: mindestens das Fünffache eines Dumps.

```sh
# nur lesend prüfen, bevor kopiert wird
du -sh "$HOME/Library/Application Support/TIM/backups/live"/*
df -h /Volumes/TIM-Backup
# Kopie eines fertigen Dumps (ältester zuerst, einzeln, mit Prüfsumme; nie die Datei, die gerade geschrieben wird)
SRC="$HOME/Library/Application Support/TIM/backups/live/<dump>"
nice -n 19 rsync -a --bwlimit=20000 "$SRC" /Volumes/TIM-Backup/live/
shasum -a 256 "$SRC" "/Volumes/TIM-Backup/live/$(basename "$SRC")"
```

Lastgrenze: `--bwlimit` 20 MB/s, `nice 19`, nur nach 03:30 Ortszeit, abbrechen wenn `server_health.json` Frische
verliert. Wöchentlich eine Kopie außer Haus (zweite SSD oder verschlüsselter Cloud-Speicher). Wenn das nicht
störungsarm geht, wird das Restrisiko hier eingetragen und nicht als „gesichert“ ausgegeben.

### 3. Restore (Zone B, nicht auf dem Kampagnen-Mac)

Ziel: getrennter Rechner (ab 29.10. die Workstation) mit PostgreSQL 18, leerer Datenbank `tim_restore`.
Protokoll je Schritt mit Zeit, Befehl, Ergebnis:

1. Dump-Prüfsumme gegen Original.
2. `pg_restore` (oder `psql < dump.sql`) in `tim_restore`; Dauer messen.
3. Prüfungen: Schema- und Extension-Liste gegen `src/database/schema.sql`; Zeilenzahlen `agg_trades`, `candles_1m`,
   `ingestion_outbox` je Status, `gap_incidents`; min/max `event_time`; Cursor-Tabelle und -Hash; Stichprobe von
   100 Trades gegen Replay aus dem Binance-Archiv (gleicher Tag).
4. Ausweisen: Backup-Alter, Datenverlust zwischen Dump und Restore-Zeitpunkt, Wiederherstellungsdauer.
5. Abnahme: eine zweite Person wiederholt den Restore aus Anleitung und Dump, ohne Hilfe.

### 4. USV und Netz

USV für Mac mini und Router mit USB-Signal an den Mac (sauberes Herunterfahren). Einbau erst nach dem 23.11. oder in
einem Moment, in dem die Kampagne ohnehin beendet oder neu gestartet wird: das Umstecken ist eine Stromunterbrechung.
Bis dahin: bestellen, Platz vorbereiten, nichts umstecken.

## T14 Abnahme und Rollout

### 1. Releaseumfang

Je Paket eine Zeile nach dem Nachweisformat aus Plan Abschnitt 8: Code, Test, Review, Integration, Einsatzstand.
Was nur Experiment ist (RAG, S2 bis zum Ergebnis) steht als Experiment, nicht als Produkt.

### 2. Kampagnenentscheidung

Frühestens 2026-11-23 20:34 UTC. Entscheidung dokumentiert: abgeschlossen (alle Kriterien, Dossier T09) oder
begründete separate Entscheidung (Abbruch/Neustart). Das Datum allein öffnet kein Wartungsfenster.

### 3. Wartungsfenster (Reihenfolge, je Schritt Rückweg)

1. Backup-Doppel vor dem Fenster, Prüfsumme.
2. `~/TIM-live` auf neuen Commit (Tag `live-<datum>`), neue venv aus Sperrdatei (T10), Plists neu rendern.
3. Start-Gates neu rechnen (`v2_start_gates_check.py`), erst dann Dienste einzeln laden: server-health, runtime,
   watchdog, history-recovery, qualification-daily.
4. Beobachtung 48 h: Frische, Queue, Coverage, Load. Betriebskriterien vorab notiert.
5. Erst danach T12-Migration (Archiv, Löschung, Index), wieder mit Beobachtung.
6. Rückweg: alter Commit, alte venv, alte Plists (alle vorher gesichert), Datenbank aus Backup-Doppel, falls eine
   Migration lief. Destruktive Migrationen nur mit geübtem Restore (T02).

### 4. Erneute Benotung

Eine andere Person reproduziert mindestens ein Forschungsergebnis (S2 oder R4 mit Protokoll 1.1) und einen Lauf des
KI-Vergleichs (T07) aus den gebundenen Quellen. Danach neue Gesamtprüfung nach den sieben Gebieten aus Plan
Abschnitt 6, mit den unbedingten Sperren. Keine Echtgeldfreigabe ist Teil davon.
