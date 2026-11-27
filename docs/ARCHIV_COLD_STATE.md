# INFRA-09: `cold-state` (Archivstand aus dem Kaltarchiv)

Stand 27.11.2026. Entwurf, nirgends eingerichtet, kein Zeitplan. INFRA-09 = HOLD.

## Wozu

Der Exporter (`export --server-state`) braucht den Archivstand `{symbol, start_id, watermark, holes}`.
Bisher kam er nur aus der Server-Datenbank (`state`). Im Mac-first-Betrieb gibt es diese Datenbank nicht;
das Archiv ist das Kaltarchiv (`cold-init` / `cold-ingest`). `cold-state` liest den Stand aus dessen
`LEDGER.jsonl` und den gespeicherten Manifesten und schreibt dieselben Schlüssel, die `export` liest.

```
python -m src.archive_sync cold-state --root STORE --symbol BTCUSDT --out /pfad/state.json [--deep]
python -m src.archive_sync export --symbol BTCUSDT --out INBOX --server-state /pfad/state.json
python -m src.archive_sync cold-ingest --root STORE --dir INBOX --symbol BTCUSDT
```

Eine Runde = neuer, leerer `INBOX`-Ordner. Alte Exporte erneut einzulesen schadet nicht (`ALREADY`).

## Wiederverwendung

Neues Modul `src/archive_sync/cold_state.py`; die abgenommenen Komponenten bleiben unverändert.
Es nutzt `importer._placement` (wohin ein Batch gehört), `importer._merge` und die Lochaufteilung des
Importers nach einem angenommenen Batch, sowie aus `cold_store` Sperre, Volume-Prüfung, `verify`,
Ledger-Leser, Manifest-Prüfung und die symlinkfreien Lesefunktionen. `__main__.py` bekommt nur den Unterbefehl.

## Regeln (fail-closed)

- Die ganze Ausführung hält die gemeinsame Sperre des Archivs. Läuft gerade ein `cold-ingest`, bricht
  `cold-state` ab, statt einen halb geschriebenen Stand zu lesen.
- Ein gebundenes Archiv braucht sein eingehängtes, richtig gekennzeichnetes Volume; sonst kein Stand.
  Ungebundene Archive nur mit `--unbound-ok` (Tests).
- Zuerst `verify`: jede Datei neu gehasht, nichts Unbekanntes unter `batches/`, keine Reste.
- Jedes gespeicherte Manifest wird gegen seinen Ledger-Eintrag (sha256, Größe), die Felder des
  Ledgers, den Eintrag seiner Datendatei und seine eigene `batch_id` geprüft (sie bindet Art, Bereich,
  Inhalt und Löcher). `--deep` packt zusätzlich jede Datendatei aus und prüft die exakten Trade-IDs.
- Bilanz: `watermark - start_id + 1 - Löcher` muss gleich der Summe der Zeilen der angewandten Batches sein.
- Jede Abweichung: Fehlermeldung, Exit 2, **kein** Stand. Der Befehl schreibt nie ins Archiv;
  `--out` innerhalb des Archivs wird abgelehnt.
- Batches, die nicht passen, zählen nicht als archiviert (der Stand behauptet eher zu wenig, dann
  exportiert die nächste Runde den Bereich erneut): `STALE` (Bereich schon abgedeckt), `OUT_OF_ORDER`
  (schließt nirgends an), `INCOMPLETE` (Datendatei ohne Manifest, abgebrochener Ingest).
  Sie stehen in `not_applied`.
- Reihenfolge wie wiederholte Importer-Läufe: Ledger-Reihenfolge, ein noch nicht anschließender Batch
  wird nach jedem angenommenen erneut versucht.

Die Ausgabe enthält zusätzlich `archived_trades`, `used_bytes`, `limit_bytes`, `remaining_bytes`.
Das Budget selbst setzt weiterhin `cold-ingest` durch (`BUDGET_STOP`, 15-%-Tor), unverändert.

## Nachweise

| Prüfung | Wo | Ergebnis |
|---|---|---|
| 23 Datei-Tests `tests/test_archive_cold_state.py` (Löcher, Backfill, Prefix, Reihenfolge, STALE, OUT_OF_ORDER, INCOMPLETE, Abbruch und Wiederanlauf, Budget, Sperre, Volume, Symlink, Migration, CLI) | Linux (Cloud), CI | grün |
| Rundlauf mit PostgreSQL `tests/test_archive_cold_state_pg.py`: Export → Kaltarchiv → cold-state → Export (Backfill, Prefix, Neu), Wiederholung ohne neue Batches, Migration auf neue Platte, Import derselben Dateien in den Server-Importer | Linux (Cloud), CI | gleicher Stand, exakt die Trade-Menge des Mac |
| `test_archive_cold_store.py` + `test_archive_cold_state.py` nativ | macOS 27.2.1, arm64, Python 3.13, APFS | 103 bestanden |
| CLI auf zwei hdiutil-APFS-Testvolumes (64 MB, synthetische Daten): init gebunden, Ingest, Stand, Plan des Exporters, Budget-Stopp, Wiederanlauf `ALREADY`, `--deep`, Abbruch bei Volume ausgehängt, Symlink `/tmp`, Datei im Archiv, laufender Schreiber; Migration A → B mit gleichem Stand | macOS | alle Schritte wie erwartet |
| Das auf dem Mac erzeugte Archiv unter Linux: gebundenes Archiv wird abgelehnt (Volume fehlt); Ledger lesbar; `cold-ingest` der gespeicherten Dateien in ein Linux-Archiv; `cold-state`; Server-Importer (2 Läufe) | Linux | Stand überall `start 1, watermark 4000, Loch 1420–1425, 3.994 Trades` |

Spätere Linux-Migration: die Batch-Dateien unter `batches/BTCUSDT/` per `transfer` auf den Server, dort
`cold-ingest` in ein neues Kaltarchiv oder `import` in das Archivschema. Beides ergibt denselben Stand
(Nachweis oben). `cold-migrate` kopiert ein Archiv auf derselben Maschine auf neue Platten.

## Feed-Abdeckung der 8,6-GB-Jahresprognose

Die Prognose (Mac-first-Plan, 27.11.) gilt **nur** für einen Feed:

| Enthalten | Wert |
|---|---|
| Tabelle | `public.agg_trades` auf dem Mac, Spalten `COLUMNS` in `common.py`, `source = BINANCE_SPOT_AGGTRADE` |
| Symbol | nur `BTCUSDT` (andere Symbole gibt es in der Tabelle nicht) |
| Bestand | seit 22.07.2026, rund 113,3 Mio. Trades × 13,5 B = 1,53 GB |
| Zuwachs | Mittel 1,43 Mio. Trades/Tag × 365 × 13,5 B = 7,05 GB |
| Summe nach 365 Tagen | **8,6 GB** |
| Schwankung | 0,96 bis 1,83 Mio. Trades/Tag (letzte 7 Tage) ergibt 6,3 bis 10,6 GB nach einem Jahr |

13,5 B je Trade ist die gemessene Größe der gzip-Batchdateien (Manifest und Ledger zusammen rund 1 KB je
Batch von 500.000 Trades). Das 26-GiB-Budget (27,9 GB) reicht nach dieser Rechnung mindestens 2,5 Jahre.

**Nicht enthalten** (eigene Dateien oder Tabellen, gehören nicht in diese Kette):

| Feed | Größe |
|---|---|
| `ingestion_outbox` (PostgreSQL, 50,7 GB) | Zwischenpuffer, wird nicht archiviert |
| Orderbuch-Recorder (Dateien) | ~0,52 GB/Tag, ~195 GB/Jahr; Tagesdateien 110 bis 743 MB (NEEDS_EVIDENCE) |
| Bitunix-Recorder | ~22,9 GB/Jahr (geschätzt) |
| Options-Flow-Recorder | ~12 MB/Tag, ~4,4 GB/Jahr |
| Perp-Daten, Kraken, Kerzen, Journale | nicht Teil dieses Archivs |

## Grenzen

- Kein Inhaltsvergleich bei überlappenden Batches (`STALE`): sie werden nur nicht gezählt. Den
  Zeilenvergleich macht erst der Server-Importer beim späteren Import.
- Ein Loch, das es auch auf dem Mac nie gibt (fehlende IDs bei Binance), bleibt offen; der Exporter
  zählt es dann als `backfill_ranges_still_empty`.
- `cold-state` hasht bei jedem Lauf das ganze Archiv (nach einem Jahr ~8,6 GB, auf der Mac-SSD
  Größenordnung Minuten, nicht gemessen).
