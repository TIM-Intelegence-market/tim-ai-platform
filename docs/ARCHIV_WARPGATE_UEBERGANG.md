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
von Chris. Eine Grenze nur im Code reicht deshalb nicht. Die Grenze muss **auf Ebene des
Dateisystems** hart begrenzt sein.

## 3 Getrennter Bereich mit harter Grenze

**Gewählt ist Variante A: eine Image-Datei fester Größe mit eigenem Dateisystem.** Sie wird per
Loop eingehängt. Warpgate muss dafür weder angehalten noch neu gestartet werden, und es wird
nichts ausgehängt. Verworfen sind die ext4-Projektquota, weil das Dateisystem dafür ausgehängt
werden müsste und Warpgate so lange ausfiele, und ein normaler Ordner, weil er keine harte Grenze
hat.

**Größe: 32 GiB statt 100 GiB.** Die Gründe und die Rechnung stehen in Abschnitt 10. Kurz: Der
wöchentliche Restore-Test braucht auf dieser Platte 208,7 GB. Mit 100 GiB bliebe während des Tests
kein 15-%-Rest. Die genauen Einrichtungsbefehle stehen in Abschnitt 11.

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

**Was 100 GiB fassen würden** (zum Vergleich, eingerichtet werden 32 GiB, siehe Abschnitt 10; Byte pro Trade wie gemessen, die drei weiteren Börsen geschätzt):

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
| Warpgate | Die Image-Datei begrenzt die Belegung hart auf 32 GiB, rund 290 GB bleiben frei. Es gibt keine Unterbrechung und keine Konfigurationsänderung. Weil Warpgate auf die ganze Platte schreiben darf, gilt das auch für die Image-Datei. Das ist dasselbe wie heute bei `tim-offload` |
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

## 10 Vorprüfung INFRA-09 (nur lesend, 24.11.2026 ca. 23:45)

Einheiten: GB = 10^9 Byte, GiB = 1024^3 Byte. Alle Werte sind in Byte gemessen.

| Prüfpunkt | Befund |
|---|---|
| Gerät | Partition 1 der zweiten Platte → LUKS2 (`aes-xts-plain64`, 512-Bit-Schlüssel, argon2id), Schlüssel aus einer Schlüsseldatei des Systems |
| Mapper / Dateisystem | `warpgate_crypt` → ext4, Label `warpgate`, eingehängt unter `/var/lib/warpgate` (`rw,relatime`, `nofail`) |
| Kennungen | Die UUIDs von LUKS und Dateisystem sind erfasst. Sie stehen in der Einrichtungsnotiz am Server und nicht auf GitHub |
| Größe | 391.999.193.088 B (365,1 GiB), Blockgröße 4096 |
| Belegt | 46.992.683.008 B (43,8 GiB) |
| Frei für Nicht-root | **325.019.078.656 B (302,7 GiB)** |
| Für root reserviert | 19.970.654.208 B (18,6 GiB), zählt nicht als frei |
| Zustand | `clean`, letzter fsck am 01.11., 24,4 Mio. Inodes frei |
| Warpgate | rund 0,2 GB, läuft seit 01.11. ohne Neustart, `ReadWritePaths=/var/lib/warpgate` |
| `tim-offload` (root, 0700) | 46,78 GB, wächst um 8,1 MB pro Tag (Journal-Archiv, 365 Tage Aufbewahrung, also etwa 3 GB im Jahr) |
| Restore-Bereich | `tim-restore-scratch` (postgres, 0700) ist jetzt leer. Der Restore-Test läuft sonntags um 05:30 als Tablespace für eine Voll-Wiederherstellung |
| **Restore-Bedarf** | Letzter Lauf am 22.11.: PASS. Gebraucht wurden **208.662.998.398 B**, nämlich das Doppelte der 100,0 GB Datenbank plus 8 GiB Reserve |
| Notzugang ohne Warpgate | `sshd` auf Port 22 (nur Schlüssel, kein root, 2 Konten mit Schlüsseln), Tailscale online, Fernwartungs-Controller des Servers vorhanden (`/dev/ipmi0`). Chris sollte bestätigen, dass er die Konsole erreicht |
| Werkzeuge | `fallocate`, `mkfs.ext4` 1.47.2, `losetup` 2.41.5, `chattr`, `findmnt`, Loop-Modul. Ein Benutzer `tim-archive` existiert noch nicht |
| **Trim** | `fstrim.timer` ist aktiv. Er würde ein Loop-Dateisystem trimmen und damit Löcher in die Image-Datei stanzen, sie also dünn machen. Gegenmittel: Option `X-fstrim.notrim` in fstab, `mkfs -E nodiscard`, und der Store prüft vor jedem Schreiben, ob das Image noch voll belegt ist |

### Kapazität und Restore-Budget

Vorgabe: Das übergeordnete Dateisystem behält **auch während des Restore-Tests** mindestens 15 %
frei, das sind 58.799.878.963 B.

| Image | frei danach | frei während des Restore-Tests | Anteil | Ergebnis |
|---|---|---|---|---|
| 100 GiB (107,37 GB) | 217,64 GB | 8,98 GB | 2,3 % | **zu groß, verletzt die 15-%-Reserve** |
| 53,6 GiB (57,56 GB) | 267,46 GB | 58,80 GB | 15,0 % | rechnerische Obergrenze, ohne jeden Puffer |
| **32 GiB (34,36 GB)** | **290,66 GB** | **82,00 GB** | **20,9 %** | **Empfehlung.** Puffer 23,2 GB für Wachstum von Datenbank und Journal |

Wachstum: Ohne Server-Sammler wächst die Datenbank kaum. Das Journal kommt auf etwa 3 GB im Jahr.
Wächst die Datenbank um mehr als rund 11 GB, verlangt der Restore-Test entsprechend mehr. Dann muss
das Image wachsen oder der Restore-Test woanders laufen. Beides kommt erst mit den neuen Platten.

Was 32 GiB fassen: Das Image hat nach ext4-Verwaltung etwa 31,5 GiB nutzbar. Das Platztor des
Stores verlangt 15 % frei, daraus ergibt sich als Grenze im Store **`--limit-gib 26`**. Das reicht
für rund 3,8 Jahre Binance Spot (20 MB pro Tag) oder für etwa 200 bis 280 Tage aller vier
Trade-Ströme (geschätzt).

**Entscheidung für Uzi:** 32 GiB jetzt, oder 100 GiB nur dann, wenn der Restore-Test vorher von
dieser Platte wegzieht. Das zweite braucht eine eigene Freigabe und eine Abstimmung mit Chris.

## 11 Einrichtungsplan (erst nach Uzis ausdrücklichem GO, nichts davon ist ausgeführt)

Grundsätze:

- Nur eine **neue** Datei wird formatiert, kein bestehender Datenträger.
- Kein Neustart von Warpgate, keine Löschung.
- Jeder Schritt bricht ab, wenn das Ziel schon existiert.

```
set -euo pipefail
IMG_DIR=/var/lib/warpgate/tim-archive-img; IMG=$IMG_DIR/archive.img; MNT=/srv/tim-archive-tmp

# 0  Vorbedingungen: Warpgate-Platte eingehängt, genug frei, Ziele noch nicht vorhanden
findmnt -no TARGET /var/lib/warpgate >/dev/null
test "$(df -B1 --output=avail /var/lib/warpgate | tail -1)" -ge 300000000000
test ! -e "$IMG_DIR"
test ! -e "$MNT"

# 1  Dienstkonto ohne Login-Shell und ohne sudo (der Import-Login aus E4 wird ihm zugeordnet)
adduser --system --group --no-create-home --shell /usr/sbin/nologin tim-archive

# 2  Image fest belegt (nicht dünn), danach Belegung nachprüfen
install -d -m 0711 -o root -g root "$IMG_DIR"
fallocate -l 32GiB "$IMG"; chmod 0600 "$IMG"
test "$(( $(stat -c %b "$IMG") * $(stat -c %B "$IMG") ))" -ge "$(stat -c %s "$IMG")"

# 3  Eigenes ext4 nur in der Image-Datei, ohne Discard und ohne Reserve
mkfs.ext4 -q -L tim-archive -m 0 -E nodiscard "$IMG"

# 4  Einhängepunkt, der ohne Einhängung nicht beschreibbar ist (leer, 0000, unveränderlich)
install -d -m 0000 -o root -g root "$MNT"; chattr +i "$MNT"

# 5  fstab: Loop, nicht trimmen, kein exec/dev/suid, abhängig von der Warpgate-Platte
echo "$IMG $MNT ext4 loop,nofail,noatime,nodev,nosuid,noexec,X-fstrim.notrim,x-systemd.requires-mounts-for=/var/lib/warpgate 0 2" >> /etc/fstab
systemctl daemon-reload
mount "$MNT"
findmnt -no SOURCE,FSTYPE,OPTIONS "$MNT"

# 6  Bereiche und Rechte im eingehängten Dateisystem
chown tim-archive:tim-archive "$MNT"; chmod 0750 "$MNT"   # Wurzel des eingehängten Archivs, nicht der Einhängepunkt darunter
install -d -m 0750 -o tim-archive -g tim-archive "$MNT/inbox" "$MNT/store-root"

# 7  Store anlegen und binden (als tim-archive, einmal von Hand)
sudo -u tim-archive /opt/tim/.venv/bin/python -m src.archive_sync cold-init \
  --root "$MNT/store-root/store" --volume "$MNT" --parent /var/lib/warpgate --limit-gib 26

# 8  Wächter vor jedem Lauf (als root, z. B. ExecStartPre=+ der späteren Import-Unit):
#    Einhängung, Dateisystem-UUID und volle Belegung des Images; sonst läuft nichts
cat > /usr/local/sbin/tim-archive-guard <<'GUARD'
#!/bin/bash
set -euo pipefail
IMG=/var/lib/warpgate/tim-archive-img/archive.img; MNT=/srv/tim-archive-tmp
EXPECTED_UUID="$(cat /etc/tim/archive-volume.uuid)"
test "$(findmnt -no UUID --mountpoint "$MNT")" = "$EXPECTED_UUID"
test "$(( $(stat -c %b "$IMG") * $(stat -c %B "$IMG") ))" -ge "$(stat -c %s "$IMG")"
GUARD
chmod 0755 /usr/local/sbin/tim-archive-guard
findmnt -no UUID --mountpoint "$MNT" > /etc/tim/archive-volume.uuid   # einmal nach Schritt 5
```

Das Konto `tim-archive` darf den Warpgate-Ordner (0700) nicht durchsuchen, und das bleibt so.
Deshalb prüft der Store selbst Einhängung, Markierungsdatei, Gerät und die 15-%-Reserve des
übergeordneten Dateisystems. Die Belegung des Images und die UUID prüft der root-Wächter in
Schritt 8. Die Option `--image` des Stores ist für Aufbauten gedacht, in denen das Konto das Image
erreichen kann.

Die Rechte in Schritt 6 gelten für das **eingehängte** Wurzelverzeichnis. Dort legt `cold-init`
die Markierungsdatei an. Der Einhängepunkt darunter bleibt leer, 0000 und unveränderlich.

Nachprüfung nach der Einrichtung, nur lesend:

- `findmnt` zeigt Loop und ext4 mit den Optionen oben.
- Die Image-Datei ist voll belegt.
- `cold-verify` meldet OK.
- Warpgate ist weiter `active`, der Zeitstempel seines Starts ist unverändert, eine Anmeldung
  klappt.
- Auf der Warpgate-Platte sind danach rund 290 GB frei.

Sicher aushängen und Rückweg:

```
sync; fuser -vm /srv/tim-archive-tmp      # darf nichts zeigen
umount /srv/tim-archive-tmp
losetup -j /var/lib/warpgate/tim-archive-img/archive.img   # darf nichts mehr zeigen
# Die Image-Datei und alle Daten bleiben. Dauerhaft aus: fstab-Zeile auskommentieren (nicht löschen).
```

Nach einem Aushängen ist der Einhängepunkt leer und unveränderlich. Ein Lauf findet dann keine
`STORE.json` und bricht ab, geschrieben wird nichts.
