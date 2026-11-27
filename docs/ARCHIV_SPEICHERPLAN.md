# Archiv: Speicherplanung und Abnahmekriterien S3/S4 (INFRA-08, Entwurf)

Stand 24.11.2026. Alle Messungen sind nur lesend auf dem Server oder in Wegwerf-Datenbanken am Mac
entstanden. Es gibt keine Festplattenänderung, keine Löschung und keine Aktivierung.
`TRADING_AUTHORIZED=NO`. Das ist eine Planungsgrundlage für Uzi und Chris, keine Freigabe.

## 1 Korrekturen zu früheren Angaben

**251 statt 212,8 Byte pro Trade (S2-Bericht).** Der S2-Prüfstand (`dryrun.py`, Schritt
`11_resources`) summiert `pg_total_relation_size` über Tabellen **und** Indizes. Die Tabellengröße
enthält ihre Indizes aber schon. Dadurch werden Primärschlüssel und Batch-Index doppelt gezählt.
Nachgemessen auf der unveränderten S2-Datenbank (Schema `archive_mac`, 1.003.991 Trades):

| Rechnung | Bytes | Byte/Trade |
|---|---|---|
| Formel aus `dryrun.py` | 252.354.560 | 251,4 |
| `pg_total_relation_size` nur der Tabellen | 213.737.472 | 212,9 |
| Hauptdateien aller Tabellen und Indizes einmal | 213.630.976 | 212,8 |

Der richtige Wert für Layout v1 ist **212,9 Byte pro Trade**. Er stimmt mit der Messung in
`layout_bench` überein. Mehrfachimporte oder fehlendes VACUUM spielen keine Rolle: Es gibt 0 tote
Zeilen. Die Vermutung F3 aus dem S2.1-Bericht ist damit widerlegt. Korrigieren werde ich `dryrun.py`
erst nach der Codex-Prüfung, weil der Prüfstand bis dahin unverändert bleibt.

**Platte für E3.** Die 279-GB-Platte ist **nicht frei**. Sie ist die Systemplatte. Die
Volume-Group darauf hat noch 1 GB frei, `/srv` hat 21 GB frei und `/var` 6,9 GB. Die zweite Platte
(372 GB, verschlüsselt) gehört den Warpgate-Daten: 44 GB sind belegt, 303 GB frei. Auf dem Server
gibt es heute also keinen freien Datenträger für das Archiv.

## 2 Messwerte

Datenmengen pro Tag (22.11.2026 UTC, Samstag, Server `venue_trades`, nur lesend gezählt):

| Strom | Trades am 22.11. | Speicher heute |
|---|---|---|
| Binance Spot BTCUSDT (`agg_trades`, Mac) | 1.003.991 | v2: 147,3 B/Trade gemessen |
| Binance Futures (Perp) BTCUSDT | 1.683.600 | `venue_trades`: 251 B/Zeile |
| Bybit Perp BTCUSDT | 2.086.917 | `venue_trades`: 251 B/Zeile |
| Coinbase Spot BTC-USD | 901.385 | `venue_trades`: 251 B/Zeile |

`venue_trades` hat insgesamt 167,8 Mio. Zeilen und 42,2 GB, davon 19,5 GB Tabelle, 15,1 GB
Primärschlüssel (Text-`trade_id`) und 7,6 GB Zeitindex. Das sind rund 5,5 Mio. Zeilen pro Tag seit
dem 25.10. Ein Archiv-Layout für `venue_trades` gibt es noch nicht.

Orderbuch (Dateien am Mac, gzip): Das volle Binance-Perp-Buch BTCUSDT kommt auf 0,44 bis 0,66 GB
pro Tag (19. bis 23.11.), im Mittel 0,58 GB. Bitunix bis Stufe 15 sind rund 0,05 GB pro Tag.

WAL beim Import eines Tages (PG 18.4, `wal_level=replica`, `full_page_writes=on`):
v1 401 MB, **v2 278 MB**, also etwa das 1,9-Fache der Tabellengröße. Auf dem Server gilt
`archive_mode=off` und `max_wal_size=8GB`. Belegt sind 2,0 GB in 127 Dateien, es gibt keinen
Replikations-Slot. WAL wächst also heute nicht mit dem Archiv, es braucht nur eine feste Reserve.

Vollständige Sicherungen (statt einzelner Tagesexporte):

| Sicherung | Rohgröße | Sicherung | Anteil | Dauer |
|---|---|---|---|---|
| Server, voller `pg_dump -Fc` (DB 99 GB, davon 46 GB Outbox) | 99 GB | 16,8 GB | 17 % | ~88 min (03:15–04:43) |
| Server, Zuwachs des Dumps 22. → 24.11. | | +350 MB/Tag | | |
| Mac, voller `pg_dump -Fc` | | 14,45 GB | | ~31 min |
| Archiv v2, ein Tag, `pg_dump -Fc` | 148 MB | 15,0 MB | 10 % | 3,3 s |
| Physische Vollsicherung `pg_basebackup -Ft -z` (Testcluster 2,91 GB) | 2,91 GB | 370 MB + 29 MB WAL | 13,7 % | 69 s |
| Batch-Dateien eines Tages (die Exportpakete selbst) | | 14,7 MB | 10 % | |

Heute aufbewahrt: Am Server liegen 3 Dumps mit zusammen 47 GB unter `/var/backups/tim`, am Mac
2 Dumps mit zusammen 29 GB, auf der PS4 2 verschlüsselte Dumps.

## 3 Hochrechnung 1, 3 und 5 Jahre

Planwerte: Binance Spot 1,5 Mio. Trades pro Tag (Mittel am Mac seit Sommer), die drei Venue-Ströme
zusammen 5,5 Mio. pro Tag (Mittel seit 25.10.). Die Werte sind kumuliert und ohne Puffer. Für
volatile Phasen und Marktwachstum rechne ich mit dem Faktor **1,5** (letzte Zeile).

| Posten | 1 Jahr | 3 Jahre | 5 Jahre |
|---|---|---|---|
| A Binance Spot, Archiv v2 (147 B) | 81 GB | 242 GB | 403 GB |
| B Binance Perp, Bybit, Coinbase, heutiges Layout (251 B) | 505 GB | 1.515 GB | 2.525 GB |
| B' dieselben mit v2-artigem Archiv-Layout (Schätzung −30 %, nicht gebaut) | 355 GB | 1.065 GB | 1.775 GB |
| C Orderbuch Binance Perp + Bitunix (Dateien) | 230 GB | 690 GB | 1.150 GB |
| C' je weitere Börse mit vollem Buch (Schätzung, wie Binance) | +210 GB | +630 GB | +1.050 GB |
| D WAL-Reserve (fest; mit 7 Tagen WAL-Archiv für PITR) | 16 GB (32 GB) | 16 GB (32 GB) | 16 GB (32 GB) |
| E 3 volle Dumps (12 % von A+B je Dump) | 211 GB | 633 GB | 1.054 GB |
| F Batch-Dateien als dauerhafte Tageskopie (10 % von A+B) | 59 GB | 176 GB | 293 GB |
| **Server ohne Orderbuch (A+B+D+E+F)** | **0,87 TB** | **2,58 TB** | **4,29 TB** |
| **mit Orderbuch (+C)** | **1,10 TB** | **3,27 TB** | **5,44 TB** |
| **mit Faktor 1,5** | **1,65 TB** | **4,9 TB** | **8,2 TB** |
| zum Vergleich: heute frei auf dem Server | 21 GB (`/srv`) + 7 GB (`/var`) | | |

Daraus folgt dreierlei:

1. **Heute ist auf dem Server gar kein Platz für das Archiv.** `/srv` ist zu 87 % belegt
   (21 GB frei von 155 GB). Das Platztor des Importers verlangt mindestens 15 % frei nach dem
   Schreiben und würde damit schon den ersten Import ablehnen. Ohne neuen Datenträger oder
   Umverteilung ist auch ein kleines S3 nicht möglich.
2. **Der größte Posten sind nicht die Spot-Trades.** Den meisten Platz brauchen die drei
   Venue-Ströme (B) und das Orderbuch (C). Für B lohnt sich ein eigenes Archiv-Layout ähnlich v2,
   also ganzzahlige Schlüssel statt Text-IDs. Das ist ein eigenes Paket und noch nicht gebaut.
3. **Volle nächtliche Dumps wachsen nicht mit.** Heute schafft der Dump rund 19 MB Datenbank pro
   Sekunde. Bei 2,5 TB Datenbank würde ein voller Dump etwa 37 Stunden dauern. Vorschlag: die
   Batch-Dateien jedes Tages als dauerhafte inkrementelle Kopie (F) und monatlich eine physische
   Vollsicherung. Sobald das Archiv eigene Platten hat, kommt ein WAL-Archiv für eine
   Wiederherstellung auf einen bestimmten Zeitpunkt dazu. Volle logische Dumps braucht es dann nur
   noch für die kleine Betriebsdatenbank.

## 4 Fragen an Chris (E3 neu)

1. Sind neue Datenträger möglich? Für 3 Jahre mit Orderbuch und Puffer wären das etwa
   2 × 4 TB als Spiegel für Archiv und WAL, plus ein getrenntes Ziel für die Sicherungen (PS4 oder
   extern). Sicherungen sollen nicht auf derselben Platte wie die Daten liegen.
2. Bis dahin: `/srv` hat nur noch 13 % frei und liegt damit schon unter dem 15-%-Tor. Gibt es
   eine Übergangslösung ohne Löschung, etwa ein eigenes kleines Volume? Die Entscheidung bleibt
   bei dir und Uzi.
3. Soll das Orderbuch langfristig auf den Server oder auf einen eigenen Speicher (Mac + PS4)?
4. Die Warpgate-Platte bleibt unangetastet. Nach meinem Stand ist sie kein Archivziel, bitte bestätigen.

## 5 Abnahmekriterien S3: Erstlauf `archive_mac` von Hand, beobachtet

**Vorbedingungen, alle erfüllt und verlinkt:**

- Codex-PASS für #389, #390 und #392 sowie für die Korrektur der Größenformel in `dryrun.py`.
- Uzis ausdrückliche Freigabe „S3 starten“.
- E3 geklärt. Nach dem Import bleiben mindestens 15 % frei, und für 90 Tage Spot-Archiv ist
  nachweislich Platz.
- E4 geklärt: eigener Import-Login ohne sudo und Postgres-Rolle mit Rechten nur auf `archive_mac`.
- Ein frischer Server-Dump mit geprüfter sha256 existiert. Der Mac-Dump der Nacht ist grün.
- `archive_mac` existiert noch nicht und wird mit `init` angelegt, also als Layout v2. Die
  Schema-Prüfung belegt v2.

**Bestanden, wenn:**

1. Der Export am Mac lief in einer Transaktion `READ ONLY, REPEATABLE READ`, mit höchstens 60 s pro
   Lauf. Die Live-Verzögerung der Mac-Sammlung (p95) steigt um höchstens 1 s gegenüber der
   Stunde davor.
2. Jedes Paket ist ACCEPTED. Es gibt 0 QUARANTINED, 0 FILE_INVALID und 0 NOT_TRIED. Die
   Übertragung ist sha256-geprüft.
3. Für jeden Tag stimmt der Beweis der ID-Menge: Anzahl = Spanne − Lücken, keine Doppelten. Der
   kanonische Tages-Digest ist in Mac-Quelle und Archiv gleich.
4. Für die Überschneidung bis 23.11. ist der Digest von `archive_mac` und Server-`public` gleich,
   oder jede Abweichung ist einzeln erklärt.
5. Ein zweiter Import derselben Dateien ergibt nur ALREADY, die Zeilenzahl bleibt gleich.
6. `archive_health` meldet OK, oder WARN nur wegen dokumentierter Quell-Lücken.
7. Kein Schreibzugriff außerhalb von `archive_mac`. Das belegen die `pg_stat_user_tables`-Deltas
   vorher und nachher. `public`, Outbox, Cursor und Backups sind unverändert.
8. Ein `pg_dump` von `archive_mac`, in eine Wegwerf-Datenbank zurückgespielt, liefert denselben
   Digest, dieselbe Herkunft und eine grüne Health-Prüfung.
9. Der Bericht in #285 enthält Commit-SHAs, Datei- und Digest-Prüfsummen, Dauer, CPU, RAM und
   den Platz vorher und nachher.

**Sofortiger Abbruch:** jede Hash-Abweichung, jede Quarantäne, weniger als 15 % frei, mehr als
60 s Mac-Laufzeit, irgendein Schreibzugriff außerhalb von `archive_mac`. **Rückweg:** anhalten.
`archive_mac` bleibt als reine Ergänzung stehen, gelöscht wird nichts.

## 6 Abnahmekriterien S4: Zeitplan an

**Vorbedingungen:** S3 bestanden und von Codex geprüft, Uzis ausdrückliche Freigabe „S4 an“, und
E3 ist für mindestens 1 Jahr gelöst (Abschnitt 3).

**Bestanden, wenn:**

1. 7 aufeinanderfolgende Nächte laufen ohne Handarbeit grün: Export, Übertragung, Import und
   Health OK.
2. Der Wasserstand ist jederzeit höchstens 30 h hinter dem Mac-Cursor.
3. Ein absichtlich ausgelöster Fehler in einer Wegwerf-Kopie (fehlende Datei, falscher Hash) ist
   als FAIL sichtbar. Der nächste Lauf holt alles nach, ohne Doppelte.
4. Die Mac-Last bleibt in jeder Nacht unter dem S3-Budget, die Live-Sammlung zeigt keine Lücke.
5. Die wöchentliche Wiederherstellungsprobe ist grün: ein Archiv-Dump in eine Wegwerf-Datenbank,
   gleicher Digest.
6. Der Not-Aus ist geprüft: „Zeitplan aus“ stoppt beide Seiten innerhalb eines Laufs, und danach
   läuft nichts mehr.
7. Platzprognose: Der tatsächliche Zuwachs der 7 Tage liegt höchstens 20 % über dem Planwert aus
   Abschnitt 3, und der Platz reicht damit noch mindestens 180 Tage.
8. Erst danach und mit eigener Freigabe kommen die Pausen aus E2, also die Live-Prüfungen und
   History-Recovery auf dem Server.

## 7 Was bewusst offen bleibt

- Ein Archiv-Layout für `venue_trades` (Posten B') ist ein eigenes Paket und braucht ein eigenes Go.
- Weitere Orderbuch-Quellen (C'): Bislang ist nur das Binance-Buch gemessen.
- Die Messung beruht auf einem Samstag. Die Planwerte nutzen deshalb Mittel über Wochen,
  Wochentage liegen höher.
