# Archiv: Übergang auf der Warpgate-Platte (INFRA-09, Entwurf)

Stand 24.11.2026. Das ist ein Entwurf: Auf dem Server wurde nichts angelegt, eingehängt oder
verändert. Alle Angaben stammen aus Abfragen, die nur gelesen haben. Genutzt wird der Datenträger
erst nach Chris' Zustimmung, einem Codex-PASS und Uzis ausdrücklicher Freigabe.
`TRADING_AUTHORIZED=NO`.

## 1 Befund (nur lesend)

| | Wert |
|---|---|
| Gerät | zweite logische Platte am RAID-Controller, LUKS-verschlüsselt, drehend |
| Dateisystem | ext4, 366 GB, 44 GB belegt, **303 GB frei**, 5 % reserviert (18,6 GB) |
| Eingehängt | `/var/lib/warpgate`, mit `nofail`. Ein Unterordner ist zusätzlich als `/var/lib/tim-restore-scratch` eingebunden |
| Warpgate selbst | rund 200 MB: SQLite-Datenbank 95 MB plus WAL, Sicherungen der Konfiguration, TLS |
| Wachstum | etwa 8 MB pro Tag. Das ist das Journal-Archiv von TIM, nicht Warpgate |
| Schon vorhandene TIM-Daten | `tim-offload` mit 45 GB (Home-Kopie 26 GB, Altbestand vom 20.10. 19 GB, Journal-Archiv 240 MB) |
| Dienst | `warpgate.service` mit `ProtectSystem=strict` und `ReadWritePaths=/var/lib/warpgate` |
| Last | Diese Platte ist zu 0,1 % ausgelastet. Die Systemplatte mit der Datenbank ist zu 7 % ausgelastet, im Mittel über 31 Tage deutlich höher |

Die Platte ist also schon heute gemischt belegt: Warpgate hat nur 0,2 GB, TIM 45 GB. An diesen
vorhandenen Daten wird nichts geändert.

## 2 Das eigentliche Risiko

Warpgate ist der einzige Zugang zu Server, PS4 und PS5. Läuft das Dateisystem voll, kann
Warpgate seine SQLite-Datenbank nicht mehr schreiben. Dann scheitern alle Anmeldungen, auch die
von Chris. Eine Grenze nur im Code reicht deshalb nicht. Die 100 GB müssen **auf Ebene des
Dateisystems** hart begrenzt sein.

## 3 Getrennter Bereich mit harter 100-GB-Grenze

**Empfehlung (Variante A): eine Image-Datei fester Größe mit eigenem Dateisystem.**

- In einem neuen Ordner neben den Warpgate-Daten (root, 0700) liegt eine Datei von 100 GiB,
  vorab fest belegt mit `fallocate`, nicht dünn angelegt. Darin steckt ein eigenes ext4 ohne
  Reserve.
- Diese Datei wird per Loop unter `/srv/tim-archive-tmp` eingehängt, mit
  `x-systemd.requires-mounts-for=/var/lib/warpgate`.
- Das Archiv kann so physisch nie mehr als 100 GiB belegen. Für Warpgate, die vorhandenen
  TIM-Daten und den Restore-Bereich bleiben rund 200 GB frei.
- Warpgate muss nicht angehalten werden, und es wird nichts ausgehängt.
- Rückweg: aushängen. Die Datei bleibt dabei erhalten.
- Umzug: `cold-migrate` auf die neuen Platten oder die Image-Datei als Ganzes kopieren.

Verworfen:

- **B, ext4-Projektquota:** Dafür müsste das Dateisystem ausgehängt und mit `tune2fs`
  umgestellt werden. Warpgate wäre so lange ausgefallen.
- **C, ein normaler Ordner nur mit Grenze im Code:** Eine fremde Schreiblast oder ein Fehler
  könnte die Platte trotzdem füllen.

Schritte für Chris, als Vorschlag. Ausgeführt ist davon nichts, und keiner der Schritte löscht
etwas:

```
# 1. Ordner und Image fester Größe (prüft vorher, dass nichts überschrieben wird)
test ! -e /var/lib/warpgate/tim-archive-img && install -d -m 0700 /var/lib/warpgate/tim-archive-img
fallocate -l 100G /var/lib/warpgate/tim-archive-img/archive.img
mkfs.ext4 -m 0 -L tim-archive /var/lib/warpgate/tim-archive-img/archive.img
# 2. Einhängepunkt und fstab-Eintrag (loop, nofail, abhängig von der Warpgate-Platte)
install -d -m 0750 /srv/tim-archive-tmp
#   /var/lib/warpgate/tim-archive-img/archive.img /srv/tim-archive-tmp ext4 loop,nofail,noatime,x-systemd.requires-mounts-for=/var/lib/warpgate 0 2
# 3. Eigentümer: der Import-Login aus E4, ohne sudo; Eingang und Store getrennt
#   /srv/tim-archive-tmp/inbox  (schreibt die Übertragung)
#   /srv/tim-archive-tmp/store  (schreibt nur cold-ingest)
```

Schutz gegen eine fehlende Einhängung: Kommt die Platte nicht hoch, fehlt im Store die Datei
`STORE.json`. Dann bricht `cold-ingest` ab und schreibt nicht auf die Systemplatte. `cold-init`
läuft nur einmal von Hand, nie automatisch.

## 4 Format: Original-Batchdateien, Parquet als spätere Abfragekopie

Messung an den echten Batches vom 22.11.2026: 1.003.991 Trades, 116 MB Rohtext.

| Format | Größe | Byte/Trade | Schreiben | Lesen |
|---|---|---|---|---|
| PostgreSQL Layout v2 (zum Vergleich) | 147,9 MB | 147,3 | 14,2 s Import | |
| **Original-Batchdateien (CSV + gzip)** | 13,5 MB | **13,5** | (Export) | |
| Parquet zstd 3 | 12,2 MB | 12,1 | 0,25 s | 0,43 s |
| Parquet zstd 9 | 12,0 MB | 12,0 | 0,55 s | 0,02 s |
| Parquet zstd 19 | 11,3 MB | 11,2 | 6,4 s | 0,03 s |
| **Parquet zstd 9 + Delta/Byte-Split** | 11,2 MB | **11,1** | 0,27 s | 0,01 s |
| CSV zstd 3 | 16,8 MB | 16,8 | 0,6 s | |
| CSV zstd 19 | 9,7 MB | 9,6 | 24,6 s | |

Verlustfreiheit ist geprüft. Die Parquet-Datei wurde in PostgreSQL zurückgeladen und dort
kanonisch neu gehasht. Alle drei `content_sha256` stimmen, und der Tages-Digest ist
`cd07c50c…e79317`, also derselbe Wert wie in S2.

Empfehlung:

1. **Gespeichert werden die Original-Batchdateien, unverändert.** Damit bleiben `batch_id`,
   `content_sha256` und `file_sha256` bitgenau die Herkunft. Es gibt keinen Umwandlungsschritt,
   der etwas verfälschen könnte, und der PostgreSQL-Importer kann später direkt aus dem Store
   importieren.
2. **Parquet mit zstd 9 und Delta-Kodierung ist die beste Abfragekopie.** Sie ist nur etwa 17 %
   kleiner als gzip, lässt sich aber spaltenweise und ohne Datenbank lesen. Parquet braucht
   `pyarrow`, das in den Abhängigkeiten noch fehlt. Die Abhängigkeitslisten sind gesperrte Pfade,
   deshalb ist das ein eigenes Paket mit eigener Freigabe.
3. CSV mit zstd 19 ist das kleinste Format, aber zu langsam und nicht abfragbar.

**Was 100 GiB fassen** (Byte pro Trade wie gemessen, die drei weiteren Börsen geschätzt):

- Nur Binance Spot, 1,5 Mio. Trades pro Tag zu je 13,5 B: etwa 20 MB pro Tag, das reicht für
  rund 14 Jahre.
- Alle vier Trade-Ströme, 7 Mio. pro Tag zu je 15 bis 20 B: 0,1 bis 0,14 GB pro Tag, das reicht
  für rund 2 bis 3 Jahre.
- Das volle Orderbuch braucht allein 0,58 GB pro Tag. Es würde die 100 GiB in etwa 170 Tagen
  füllen und gehört deshalb nicht in diesen Übergangsbereich.

## 5 Übertragung: der vorhandene Weg über Warpgate

Die Übertragung läuft über den vorhandenen Weg Mac → Warpgate → Server:

- `transfer --host <login>@<server> --port <warpgate-port> --remote-dir <inbox>` nutzt
  `SshTarget` aus S1. Jede Datei wird zuerst als `.part` geschrieben, auf dem Server per sha256
  geprüft und erst dann umbenannt. Die Daten gehen vor dem Manifest. Die freie Fläche wird vor
  dem Senden geprüft.
- Danach läuft auf dem Server `cold-ingest --root <store> --dir <inbox>`. Der Store lässt die
  Eingangsdateien liegen, gelöscht wird nichts.
- Login und Ziel kommen nur aus Aufrufparametern und nie in das Repo. Gebraucht wird der
  eingeschränkte Import-Login aus E4 mit Schreibrecht nur auf `inbox`.
- Die Leitung schafft rund 5 MB/s, für einen Spot-Tag sind das etwa 3 s.

## 6 Code im Entwurf (`src/archive_sync/cold_store.py`)

- `ColdStore.init`: legt den Store nur in einem leeren Ordner an und weigert sich, einen fremden
  Ordner wie die Warpgate-Daten zu übernehmen. Die Grenze steht in `STORE.json` und lässt sich
  nicht still ändern.
- `ingest_directory` macht vor dem Schreiben dieselben Prüfungen wie der Importer: Manifest,
  sha256, Größe, `batch_id`, gzip, `content_sha256` und die genaue ID-Menge mit Lücken. Danach
  prüft es zwei Grenzen. Ist `belegt + neu > Grenze`, meldet es **BUDGET_STOP**: Für dieses Paket
  wird nichts geschrieben, und kein weiteres Paket wird versucht. Fällt der freie Platz unter
  15 %, meldet es **DISK_STOP**.
- Zur Belegung zählt der größere von zwei Werten: was das Ledger verzeichnet oder was wirklich
  auf der Platte liegt.
- Nichts wird überschrieben. Eine andere Datei unter einem gespeicherten Namen ist ein
  **CONFLICT** und stoppt den Lauf. Geschrieben wird über `.part` mit fsync und sha256-Vergleich,
  danach per Hardlink, der nie ersetzt.
- `LEDGER.jsonl` wird nur ergänzt. Jede Datei steht darin mit sha256, Größe, `batch_id`,
  `content_sha256` und Bereich.
- Nach einem Absturz setzt ein neuer Lauf fort und meldet **RESUMED**, ohne Doppelte.
- `verify` hasht jede Datei neu und findet geänderte, fehlende und unbekannte Dateien.
- `migrate_store` kopiert nur in einen leeren Zielordner, prüft dort alles nach und schreibt
  `MIGRATION.json`. Die Quelle bleibt unverändert.
- **Keine Löschfunktion:** Ein Test stellt sicher, dass das Modul außer seinen eigenen
  `.part`-Dateien nichts entfernt.
- Kommandos: `cold-init`, `cold-ingest`, `cold-verify`, `cold-migrate`.

Tests: `tests/test_archive_cold_store.py` mit 15 Fällen, ohne Datenbank. Echtdatenprobe am Mac
mit den drei Batches vom 22.11.:

- Gespeichert wurden 3 Batches mit 13,5 MB. Ein zweiter Lauf meldet 3 × ALREADY.
- `verify` ist OK.
- Der Umzug kopiert 6 Dateien, sie sind gleich groß, und die Prüfung ist OK.
- Die gespeicherten Dateien haben dieselbe sha256 wie das Original.
- Mit einer Grenze von 10 MB ergibt sich STORED, BUDGET_STOP, NOT_TRIED.

## 7 Spätere Migration auf neue Platten

1. Die neuen Platten richtet Chris ein, siehe `docs/ARCHIV_SPEICHERPLAN.md`.
2. Mit `cold-migrate --root /srv/tim-archive-tmp/store --to <neu>` wird kopiert und am Ziel
   nachgeprüft, das Ergebnis steht in `MIGRATION.json`.
3. Optional wird aus dem neuen Store in das PostgreSQL-Archiv mit Layout v2 importiert. Das ist
   derselbe Importer, er bekommt dieselben Dateien.
4. Der Übergangsbereich bleibt stehen, bis Uzi und Chris ausdrücklich über ihn entscheiden.
   Eine automatische Löschung gibt es nicht.

## 8 Auswirkungen auf Warpgate und laufende Dienste

| Dienst | Auswirkung |
|---|---|
| Warpgate | Die Image-Datei begrenzt die Belegung hart auf 100 GiB, rund 200 GB bleiben frei. Es gibt keine Unterbrechung und keine Konfigurationsänderung. Weil Warpgate auf die ganze Platte schreiben darf, gilt das auch für die Image-Datei. Das ist dasselbe wie heute bei `tim-offload` |
| Restore-Bereich (`tim-restore-scratch`) | Er liegt auf derselben Platte. Mit den 100-GiB-Deckel bleiben genug Platz für Restore-Tests, für einen vollen 99-GB-Restore wird es aber eng. Chris sollte das bewerten |
| Journal-Archiv | 8 MB pro Tag, unkritisch |
| PostgreSQL | Liegt auf der Systemplatte und ist nicht betroffen. Der Store ist eine reine Dateiablage |
| Platten-Last | Ein Spot-Tag ist 14 MB und in unter 1 s gespeichert. Ein volles `verify` liest den ganzen Store, deshalb wöchentlich und nicht nächtlich |
| CPU/RAM | Gemessen am Mac 0,7 s pro Tag. Auf dem Server liegt ein Lauf außerhalb der Dump-Zeit (03:15 bis 04:45) |

Offen für Chris:

- Welcher RAID-Level gilt für diese Platte? Gibt es eine Sicherung der Platte selbst?
- Soll `tim-offload` mit 45 GB dort bleiben?
- Passt der Platz für den Restore-Bereich?

## 9 Freigaben vor der produktiven Nutzung

1. Chris stimmt Variante A zu und richtet Image, Einhängung und Import-Login (E4) ein.
2. Codex-PASS für diesen Entwurf sowie für #389, #390, #392 und #393.
3. Uzis ausdrückliche Freigabe für den ersten Lauf von Hand. Ein Zeitplan braucht danach eine
   eigene Freigabe, wie S4.

Abbruch bei: BUDGET_STOP, DISK_STOP, CONFLICT, FILE_INVALID, einem `verify` mit FAIL, oder wenn
Warpgate langsamer reagiert. Rückweg: Lauf anhalten und aushängen. Nichts wird gelöscht.
