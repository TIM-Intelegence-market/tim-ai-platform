# Archiv-Abgleich Mac → Server, Paket S1

Stand 24.11.2026, Plan in Issue #285 (INFRA-08). S1 ist nur Code und Tests: **nichts läuft
automatisch, nichts ist eingeplant, nichts ist auf Mac oder Server eingerichtet.** S2 (Einrichtung),
S3 (erster Lauf) und S4 (Zeitplan) brauchen je eine eigene Freigabe. `TRADING_AUTHORIZED=NO`.

## Was es tut

| Schritt | Wo | Befehl (`python -m src.archive_sync …`) | Schreibt |
|---|---|---|---|
| Stand holen | Server | `state --symbol BTCUSDT` | nichts |
| Export | Mac | `export --symbol … --out DIR --server-state state.json` | nur Dateien in `DIR` |
| Übertragen | Mac | `transfer --symbol … --dir DIR --host … --remote-dir …` | Dateien im Zielordner |
| Import | Server | `import --symbol … --dir DIR --gate-path PFAD` | nur Schema `archive_mac` |
| Prüfen | Server | `health --symbol … [--source-cursor-id N]` | nichts |

Verbindungen kommen nur aus `TIM_ARCHIVE_SOURCE_URL` (Mac) und `TIM_ARCHIVE_TARGET_URL` (Server).
Es gibt keinen Rückfall auf die Laufzeit-Datenbank. Host, Port und Schlüssel werden beim Aufruf
übergeben und stehen nicht im Code.

## Sicherheitsregeln im Code

- **Ein Schnappschuss:** Der Export liest in einer `REPEATABLE READ READ ONLY`-Transaktion. Die
  Obergrenze ist der Ingestion-Cursor aus demselben Schnappschuss, also werden Trades, die gerade
  noch geschrieben werden, nicht exportiert.
- **Vollständigkeit statt Zeilenzahl:** Jedes Paket deckt einen ID-Bereich `[lo, hi]` ab und nennt
  die fehlenden IDs ausdrücklich als Lücken. Der Import beweist, dass die IDs genau `[lo, hi]` ohne die
  Lücken sind. Dafür prüft er Anzahl, Eindeutigkeit, Bereich und dass keine Zeile in einer Lücke liegt.
- **Nachgetragene Trades gehen nicht verloren:** Lücken bleiben auf dem Server offen (`archive_mac.holes`).
  Sobald der Mac sie nachgetragen hat, exportiert jeder Lauf sie als `backfill`-Paket, auch unterhalb des
  Wasserstands. Ältere Daten vor dem ersten Paket kommen als `prefix`.
- **Alles oder nichts:** Ein Paket wird in einer einzigen Transaktion übernommen. Bei Hash-, Bereichs-,
  Eindeutigkeits- oder Inhaltskonflikt wird alles zurückgerollt und das Paket als `QUARANTINED` vermerkt,
  ohne Zeilen. Die Kette hält danach an und `health` wird rot, bis ein Mensch nachsieht.
  Ist die Datei nur kaputt übertragen (falscher Datei-Hash), wird sie nicht angenommen (`FILE_INVALID`).
  Dann reicht es, sie erneut zu übertragen.
- **Gleiche Bytes auf PostgreSQL 16 und 18:** Der Inhalts-Hash wird über eine feste CSV-Form gebildet.
  Die Ausgabe-Einstellungen (UTC, ISO, `extra_float_digits=1`) werden in jeder Transaktion lokal gesetzt.
- **Wiederaufnahme:** Die Übertragung schreibt jede Datei erst als `.part`, prüft den sha256 auf der
  Gegenseite und benennt sie dann um. Daten gehen vor dem Manifest, und der Import sieht nur Manifeste.
  Bereits vorhandene Dateien mit gleichem Hash werden übersprungen. Ein erneuter Import ist ein No-op.
- **Platz-Sperren:** Export, Übertragung und Import brechen ab, bevor sie schreiben, wenn danach weniger
  als 15 % frei wären.
- **Nicht angefasst:** `public`-Tabellen und Cursor des Servers, `tim-market-feeds`/`venue_trades`,
  alle historischen Daten. Der Import verweigert das Schema `public`.

## Tests

`tests/test_archive_sync.py` (26 Tests, echte PostgreSQL über `TIM_DURABLE_TEST_DATABASE_URL`, je Test
eigene Wegwerf-Schemas). Sie decken ab:

- exakte ID-Menge;
- Cursor-Grenze;
- Idempotenz;
- Nachtrag unter dem Wasserstand (teilweise und ganz);
- Prefix;
- Reihenfolge;
- kaputte Übertragung;
- Hash-Konflikt mit Kettenstopp;
- doppelte IDs, fehlende Zeile, falsches Symbol oder falsche Quelle bei sonst stimmigen Hashes;
- Zeile in deklarierter Lücke;
- Inhaltskonflikt mit Archiv;
- nachträglich veränderte Archivzeilen;
- veraltetes Archiv;
- Schnappschuss gegen gleichzeitiges Schreiben;
- Platz-Sperren;
- abgebrochene Übertragung mit Wiederaufnahme;
- ssh-Hash-Prüfung vor dem Umbenennen;
- unsichere Namen;
- kein Rückfall auf die Laufzeit-Datenbank.
