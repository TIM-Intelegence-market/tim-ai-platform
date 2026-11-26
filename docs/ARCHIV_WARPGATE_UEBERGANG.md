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
  **CONFLICT** und stoppt den Lauf. Das gilt auch für einen Link oder eine Sonderdatei unter
  diesem Namen.
- **Jeder Schreibvorgang bleibt im Store (Nachbesserung 25.11.).** Ordner werden Stück für Stück
  mit `O_NOFOLLOW` geöffnet. Jede Datei entsteht relativ zu diesem festgehaltenen Ordner mit
  `O_CREAT | O_EXCL | O_NOFOLLOW` unter einem zufälligen `.tmp-`-Namen, wird mit fsync
  geschrieben, zurückgelesen und per sha256 verglichen, auf 0444 gesetzt und dann per Hardlink
  angelegt. Der Hardlink ersetzt nie etwas. Ledger und Sperrdatei werden ebenfalls ohne
  Link-Folgen geöffnet. Pfade im Ledger müssen `batches/<Symbol>/<Name>` sein, sonst brechen
  `verify` und der Umzug ab.
- Das Manifest wird einmal gelesen, geprüft und genau so gespeichert. Die Datendatei wird gegen
  die sha256 aus dem Manifest kopiert. Ein Austausch zwischen Prüfung und Kopie fällt so auf.
- Das Symbol im Manifest muss zum angefragten passen, Dateinamen müssen schlicht sein. Eine
  FIFO im Eingang lässt den Lauf nicht hängen.
- `LEDGER.jsonl` wird nur ergänzt. Jede Datei steht darin mit sha256, Größe, `batch_id`,
  `content_sha256` und Bereich.
- Nach einem Absturz setzt ein neuer Lauf fort und meldet **RESUMED**, ohne Doppelte.
- `verify` hasht jede Datei neu. Es findet geänderte, fehlende, beschreibbare, verlinkte,
  mehrfach verlinkte (Hardlink) und unbekannte Dateien sowie liegengebliebene `.tmp-`-Dateien.
  Diese zählen auch zur Belegung.
- `migrate_store` kopiert nur in einen leeren Zielordner, prüft dort alles nach und schreibt
  `MIGRATION.json`. Die Quelle bleibt unverändert.
- **Nach der zweiten Gegenprüfung (25.11.):** Eine Kopie bricht ab, sobald die Quelle größer als
  angegeben wird. Ungültiges UTF-8 und nicht eindeutige Trade-IDs (`+1`, `01`) sind FILE_INVALID statt
  Absturz. Derselbe Batch unter zweitem Namen ist ein CONFLICT. Die Markierung muss eine UUID sein,
  eine leere Markierung zählt als falsches Volumen. Die Grenze darf höchstens 85 % des Volumens
  sein. Ein Store auf `/` wird abgelehnt. `init` legt nur den Store-Ordner selbst an. Ein
  abgerissener Ledger-Rest wird nicht mehr abgeschnitten, sondern abgeschlossen und protokolliert.
  Datei-Systemfehler wie ENOSPC oder EROFS kommen als sauberer Abbruch an. Der Umzug prüft das
  15-%-Tor am Ziel und lehnt ineinander liegende Ordner ab. `verify` nimmt eine geteilte Sperre
  (braucht kein Schreibrecht, läuft nicht neben einem Import). Ein Ledger-Eintrag, dem nur der
  Zeilenumbruch fehlte, zählt nach dem Abschluss genau einmal. Eine geänderte oder wachsende
  Quelle ist FILE_INVALID für dieses Paket.
- **Keine Löschfunktion:** Ein Test stellt sicher, dass das Modul nur seine eigene, gerade mit
  `O_EXCL` angelegte `.tmp-`-Datei entfernt und nichts umbenennt oder ersetzt.
- Kommandos: `cold-init`, `cold-ingest`, `cold-verify`, `cold-migrate`.

Tests: `tests/test_archive_cold_store.py` mit 81 Fällen, ohne Datenbank: Negativtests, ein
Schnappschuss-Test, dass außerhalb von Store und Umzugsziel nichts geschrieben wird, und 25
Zufallsläufe mit festen Startwerten für Budget und Unversehrtheit. Echtdatenprobe am Mac
mit den drei Batches vom 22.11. (Stand 18f70e5e):

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
| Restore-Bereich (`tim-restore-scratch`) | Er liegt auf derselben Platte und braucht sonntags rund 208,7 GB. Mit 32 GiB bleiben dabei 20,9 % frei, siehe §10 |
| Journal-Archiv | 8 MB pro Tag, unkritisch |
| PostgreSQL | Liegt auf der Systemplatte und ist nicht betroffen. Der Store ist eine reine Dateiablage |
| Platten-Last | Ein Spot-Tag ist 14 MB und in unter 1 s gespeichert. Ein volles `verify` liest den ganzen Store, deshalb wöchentlich und nicht nächtlich |
| CPU/RAM | Gemessen am Mac 0,7 s pro Tag. Auf dem Server liegt ein Lauf außerhalb der Dump-Zeit (03:15 bis 04:45) |

Offen für Chris:

- Welcher RAID-Level gilt für diese Platte? Gibt es eine Sicherung der Platte selbst?
- Soll `tim-offload` mit 45 GB dort bleiben?
- Passt der Platz für den Restore-Bereich?

## 9 Freigaben vor der produktiven Nutzung

Stand 25.11. Uzi ist für dieses Volumen berechtigt, Chris bekommt es zur Kenntnis.

1. **Einrichtung (32 GiB, Grenze 26 GiB):** am 24.11. von Uzi genehmigt, aber nur unter
   Bedingungen. Codex-PASS für #389, #390, #392, #393 und #394. Keine offenen
   Sicherheitsbefunde. Speicherprüfung direkt vorher. Mindestens 15 % frei auch während des
   Restore-Tests. Warpgate und alle Dienste unbeeinträchtigt. Bei FAIL oder INCONCLUSIVE:
   Stopp.
2. **Erster Archivlauf von Hand:** eigene Freigabe.
3. **Zeitplan oder automatische Archivierung:** eigene Freigabe, wie S4.

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
| Werkzeuge | `fallocate`, `mkfs.ext4` 1.47.2, `losetup` 2.41.5, `chattr`, `findmnt`, Loop-Modul (`blkid` am 24.11. nicht eigens geprüft, Schritt 0 bricht ohne ab). Ein Benutzer `tim-archive` existiert noch nicht |
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

**Entscheidung (Uzi, 24.11.): 32 GiB, Grenze 26 GiB, unter den Bedingungen in §9.** 100 GiB gingen nur, wenn der Restore-Test vorher von
dieser Platte wegzieht. Das zweite braucht eine eigene Freigabe und eine Abstimmung mit Chris.

## 11 Einrichtungsplan (erst nach Uzis ausdrücklichem GO, nichts davon ist ausgeführt)

Grundsätze:

- Nur eine **neue** Datei wird formatiert, kein bestehender Datenträger.
- Kein Neustart von Warpgate, keine Löschung.
- Jeder Schritt bricht ab, wenn das Ziel schon existiert.

```
set -euo pipefail
umask 077
IMG_DIR=/var/lib/warpgate/tim-archive-img; IMG=$IMG_DIR/archive.img; MNT=/srv/tim-archive-tmp
# Der Wächter läuft als root aus /opt/tim. Darum muss dort alles root gehören und darf für niemand
# anderen beschreibbar sein, sonst liefe fremder Code als root:
test -z "$(find /opt/tim \( ! -user root -o -perm /022 \) -print -quit)"
command -v findmnt blkid >/dev/null
cd /opt/tim; GUARD="/opt/tim/.venv/bin/python -m src.archive_sync.mount_guard"   # nur lesend
WG_UUID_FILE=/etc/tim/warpgate-fs.uuid; ARCH_UUID_FILE=/etc/tim/archive-volume.uuid

# -1 Erwartete Kennung der Warpgate-Platte (ext4-UUID) von Hand aus dem autorisierten, nur lesenden
#    Inventar (Einrichtungsnotiz am Server) eintragen, NICHT aus findmnt/blkid dieses Laufs abschreiben:
#    install -d -m 0700 -o root -g root /etc/tim
#    install -m 0600 -o root -g root /dev/null "$WG_UUID_FILE"; editor "$WG_UUID_FILE"
#    Die UUID wird nirgends ausgegeben und nicht auf GitHub geschrieben.

# 0  Vorbedingungen, alle vor jedem Seiteneffekt, jede bricht ab (Exit ≠ 0):
#    Identität der Warpgate-Platte (genau dieser Einhängepunkt, ext4, rw, erwartete UUID per blkid -p),
#    Reserve (15 % frei nach 32 GiB und während des Restore-Tests), Ziele noch nicht vorhanden.
$GUARD parent --target /var/lib/warpgate --expected-uuid-file "$WG_UUID_FILE" --fstype ext4
$GUARD reserve --parent /var/lib/warpgate
test "$(df -B1 --output=avail /var/lib/warpgate | tail -1)" -ge 300000000000
test ! -e "$IMG_DIR" -a ! -L "$IMG_DIR"
test ! -e "$MNT" -a ! -L "$MNT"
test ! -e "$ARCH_UUID_FILE" -a ! -L "$ARCH_UUID_FILE"

# 1  Dienstkonto ohne Login-Shell und ohne sudo (der Import-Login aus E4 wird ihm zugeordnet)
adduser --system --group --no-create-home --shell /usr/sbin/nologin tim-archive

# 2  Image fest belegt (nicht dünn), danach Belegung nachprüfen
install -d -m 0711 -o root -g root "$IMG_DIR"
fallocate -l 32GiB "$IMG"; chmod 0600 "$IMG"
test "$(( $(stat -c %b "$IMG") * $(stat -c %B "$IMG") ))" -ge "$(stat -c %s "$IMG")"

# 3  Eigenes ext4 nur in der Image-Datei, ohne Discard und ohne Reserve.
#    Die Kennung wird VORHER festgelegt und geschützt abgelegt, dann mit -U gesetzt und geprüft;
#    so wird nichts aus dem Ergebnis selbst abgeschrieben.
$GUARD parent --target /var/lib/warpgate --expected-uuid-file "$WG_UUID_FILE" --fstype ext4
cat /proc/sys/kernel/random/uuid > "$ARCH_UUID_FILE"; chmod 0600 "$ARCH_UUID_FILE"
mkfs.ext4 -q -L tim-archive -m 0 -E nodiscard -U "$(cat "$ARCH_UUID_FILE")" "$IMG"
$GUARD image --image "$IMG" --expected-uuid-file "$ARCH_UUID_FILE"   # Größe, volle Belegung, UUID

# 4  Einhängepunkt, der ohne Einhängung nicht beschreibbar ist (leer, 0000, unveränderlich)
install -d -m 0000 -o root -g root "$MNT"; chattr +i "$MNT"

# 5  fstab: Loop, nicht trimmen, kein exec/dev/suid, abhängig von der Warpgate-Platte
echo "$IMG $MNT ext4 loop,nofail,noatime,nodev,nosuid,noexec,X-fstrim.notrim,x-systemd.requires-mounts-for=/var/lib/warpgate 0 2" >> /etc/fstab
systemctl daemon-reload
$GUARD parent --target /var/lib/warpgate --expected-uuid-file "$WG_UUID_FILE" --fstype ext4
mount "$MNT"
# Nach dem Einhängen: genau dieser Einhängepunkt, Loop auf genau diesem Image, ext4, rw,nodev,nosuid,
# noexec, erwartete UUID. Schlägt das fehl: sofort aushängen (umount "$MNT"), nichts weiter.
# Jede der drei Prüfungen, die fehlschlägt, hängt sofort wieder aus.
if ! { $GUARD archive --target "$MNT" --image "$IMG" --expected-uuid-file "$ARCH_UUID_FILE" \
       && $GUARD parent --target /var/lib/warpgate --expected-uuid-file "$WG_UUID_FILE" --fstype ext4 \
       && $GUARD reserve --parent /var/lib/warpgate --image-allocated; }; then umount "$MNT"; exit 1; fi

# 6  Bereiche und Rechte im eingehängten Dateisystem
chown tim-archive:tim-archive "$MNT"; chmod 0750 "$MNT"   # Wurzel des eingehängten Archivs, nicht der Einhängepunkt darunter
install -d -m 0750 -o tim-archive -g tim-archive "$MNT/inbox" "$MNT/store-root"

# 7  Store anlegen und binden (als tim-archive, einmal von Hand)
sudo -u tim-archive /opt/tim/.venv/bin/python -m src.archive_sync cold-init \
  --root "$MNT/store-root/store" --volume "$MNT" --parent /var/lib/warpgate --limit-gib 26

# 8  Wächter vor jedem Lauf (als root, z. B. ExecStartPre=+ der späteren Import-Unit).
#    Läuft nur, wenn beide Platten die erwartete Identität haben, das Image voll belegt ist und die
#    Reserve hält; sonst läuft nichts. Die erwarteten UUIDs kommen aus den Dateien von Schritt -1 und 3.
cat > /usr/local/sbin/tim-archive-guard <<'GUARD'
#!/bin/bash
set -euo pipefail
test -z "$(find /opt/tim \( ! -user root -o -perm /022 \) -print -quit)"
cd /opt/tim
G="/opt/tim/.venv/bin/python -m src.archive_sync.mount_guard"
IMG=/var/lib/warpgate/tim-archive-img/archive.img; MNT=/srv/tim-archive-tmp
$G parent  --target /var/lib/warpgate --expected-uuid-file /etc/tim/warpgate-fs.uuid --fstype ext4
$G image   --image "$IMG" --expected-uuid-file /etc/tim/archive-volume.uuid
$G archive --target "$MNT" --image "$IMG" --expected-uuid-file /etc/tim/archive-volume.uuid
$G reserve --parent /var/lib/warpgate --image-allocated
GUARD
chmod 0755 /usr/local/sbin/tim-archive-guard
/usr/local/sbin/tim-archive-guard   # einmal sofort, muss Exit 0 liefern
```

Das Konto `tim-archive` darf den Warpgate-Ordner (0700) nicht durchsuchen, und das bleibt so.
Deshalb prüft der Store selbst Einhängung, Markierungsdatei, Gerät und die 15-%-Reserve des
übergeordneten Dateisystems. Die Identität beider Platten, die Belegung des Images und die Reserve
prüft der root-Wächter (`src/archive_sync/mount_guard.py`) vor jedem Seiteneffekt, nach dem
Einhängen und vor jedem Lauf.

**Warum (Befund 26.11.):** Der frühere Schritt 0 (`findmnt -no TARGET /var/lib/warpgate`) bewies
nur, dass dort irgendetwas eingehängt ist, nicht welche Platte. Der frühere Wächter verglich die
Archiv-UUID mit einer Datei, die aus genau dieser Einhängung abgeschrieben wurde, also mit sich
selbst. Jetzt gilt: Die Warpgate-Kennung kommt aus dem unabhängigen Inventar, die Archiv-Kennung
wird vor `mkfs` festgelegt. Der Wächter liest die Kennung per `blkid -p` direkt vom Gerät (kein
Cache), verlangt den Einhängepunkt exakt (`findmnt --mountpoint`, keine Übernahme eines
übergeordneten Ordners), lehnt gestapelte Einhängungen, falsche Typen, fehlendes `rw` und fremde
Loop-Images ab und gibt keine UUID aus. Jeder unklare Zustand ist FAIL (Exit ≠ 0). Kein Schalter
schwächt eine Prüfung ab; nur die Testsuite darf per Umgebungsvariable eine UUID-Datei ohne root als
Eigentümer verwenden.

Reserve im Wächter: Er rechnet strenger als §10, mit 5 % Wachstum auf den Restore-Bedarf vom 22.11.
Am 26.11. ergibt das 71,5 GB frei während des Restore-Tests (18,2 %, Vorgabe 15 %). Läuft der Wächter
während des Restore-Tests selbst (sonntags ab 05:30), ist der Platz schon belegt und er meldet FAIL.
Das ist gewollt (fail-closed): Archivläufe gehören nicht in dieses Fenster.

Abbruch mitten in der Einrichtung: Nichts wird gelöscht. Ist das Archiv eingehängt, wird es
ausgehängt; eine schon geschriebene fstab-Zeile wird auskommentiert. Image-Ordner und UUID-Datei
bleiben stehen, deshalb bricht ein zweiter Versuch an den `test ! -e`-Zeilen von Schritt 0 ab. Ein
neuer Versuch braucht eine eigene Entscheidung von Uzi, was mit den Resten geschieht. Die Option `--image` des Stores ist für Aufbauten gedacht, in denen das Konto das Image
erreichen kann.

Die Rechte in Schritt 6 gelten für das **eingehängte** Wurzelverzeichnis. Dort legt `cold-init`
die Markierungsdatei an. Der Einhängepunkt darunter bleibt leer, 0000 und unveränderlich.

Nachprüfung nach der Einrichtung, nur lesend:

- `/usr/local/sbin/tim-archive-guard` liefert Exit 0 (alle vier Prüfungen PASS).
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

## 12 Wiederherstellung

Das Übergangsarchiv ist eine **Kopie**. Das Original bleibt bis zur Entscheidung über neue
Platten die Mac-Datenbank und deren Batch-Exporte. Die Stufen:

1. **Prüfen:** `cold-verify` hasht jede Datei neu. Sinnvoll ist ein Lauf pro Woche außerhalb des
   Restore-Tests, er braucht eine eigene Freigabe wie jeder Zeitplan.
2. **Zweite Kopie:** `cold-migrate --to <Ziel>` kopiert den ganzen Store in einen leeren Ordner
   auf einem anderen Datenträger, prüft dort nach und lässt die Quelle unverändert. Getestet:
   zwei Umzüge hintereinander (Sicherung, dann Rückspielen) ergeben bitgleiche Dateien.
3. **Zurück in PostgreSQL:** Der vorhandene Importer liest dieselben Dateien. Er legt neue
   Archive mit Layout v2 an (#393) und prüft vorher Manifest, sha256 und ID-Menge.
4. **Verlust der Warpgate-Platte:** Der Store ist dann weg, das Original nicht. Die
   Wiederherstellung ist ein neuer Export vom Mac plus `cold-ingest`. Solange der RAID-Level der
   Platte unbekannt ist (Frage an Chris), gilt das Übergangsarchiv nicht als Sicherung.
5. **Unterbrochener Schreibvorgang:** Ein abgerissener Ledger-Rest wird beim nächsten Lauf
   abgeschlossen und protokolliert, nichts wird abgeschnitten. Eine liegengebliebene `.tmp-`-Datei meldet `verify` und
   zählt zur Belegung. `verify` meldet dann FAIL, und der Umzug wartet. Entfernt wird sie nur von
   Hand nach Prüfung: Ist die gleichnamige gespeicherte Datei laut Ledger vollständig, ist die
   `.tmp-`-Datei ein zweiter Name derselben Daten. Sonst ist sie ein abgebrochener Rest.

## 13 Speicherinventar aller TIM-Geräte (nur lesend, 25.11. ca. 00:45)

| Gerät | Datenträger | frei | Rolle für das Archiv |
|---|---|---|---|
| Mac | 1 TB intern (APFS) | 498 GB | Original der Daten, Export der Batches |
| Server, Warpgate-Platte | 399 GB (LUKS/ext4) | 325 GB | Übergangsarchiv 32 GiB, Restore-Test, `tim-offload` |
| Server, Systemplatte | 299 GB, LVM | `/` 35 GB, `/srv` 22 GB (86 % belegt), `/var` 7,4 GB (88 % belegt) | ungeeignet, liegt unter dem 15-%-Tor |
| PS5 | 120 GB | 99 GB | nur Rechnen, kein Archiv |
| PS4 | 269 GB (Loop) | 222 GB | nur Rechnen, kein Archiv |

Beide Server-Platten sind drehende Platten. Für 1, 3 und 5 Jahre reicht nichts davon, siehe
`docs/ARCHIV_SPEICHERPLAN.md`. Die neuen Platten bleiben die eigentliche Lösung.

## 14 Umzug auf neue Platten (vorbereitet)

1. Chris richtet die neuen Platten ein, mit eigenem Dateisystem und eigener Einhängung.
2. Dort entsteht ein neuer gebundener Store: `cold-migrate --root <alt> --to <neu>/store
   --volume <neu> --parent <neu>`. Das Ziel muss leer sein. Die Quelle wird gesperrt, damit
   währenddessen nichts dazukommt.
3. `MIGRATION.json` und ein `cold-verify` am Ziel belegen gleiche Dateizahl und gleiche Bytes.
4. Der alte Store bleibt stehen, bis Uzi ausdrücklich über ihn entscheidet. Erst dann darf die
   Image-Datei weg.
5. Ein Ziel **ohne** `MIGRATION.json` ist ein abgebrochener Umzug und gilt nicht als Kopie, auch
   wenn sein `verify` OK meldet. Ein neuer Versuch geht in einen neuen, leeren Ordner.

Grenzen, bewusst so gelassen:

- **Pfade mit Links:** Der Store lehnt jeden symbolischen Link irgendwo im Pfad ab, auch in den
  übergeordneten Ordnern. Auf dem Server sind `/srv` und `/var/lib/warpgate` echte Ordner. Am
  Mac sind `/tmp` und `/var` Links, dort braucht es aufgelöste Pfade (`/private/...`).
- **Überlappende Bereiche** unterschiedlicher Batches erkennt der Store nicht. Das prüft der
  Importer beim Rückweg in PostgreSQL.
- **Belegung** zählt die Dateigrößen. Blockrundung und Verwaltungsdaten deckt der Abstand von
  26 GiB Grenze zu rund 31,5 GiB nutzbarem Platz ab.


## 15 Offene Fragen an Chris (zur Kenntnis, keine Freigabe nötig)

1. Welchen RAID-Level beziehungsweise welche Redundanz hat die Warpgate-Platte?
2. Ist die Fernwartungskonsole erreichbar, falls SSH und Warpgate ausfallen?
3. Bleibt `tim-offload` (46,8 GB) dauerhaft auf dieser Platte?
4. Wann und wie groß kommen die neuen Platten, und mit welchem Dateisystem?
5. Soll der sonntägliche Restore-Test langfristig auf dieser Platte bleiben?

## 16 Forschungsbereitschaft nach INFRA-09

Das Übergangsarchiv ändert an Forschungsdaten nichts. Studien lesen weiter die Mac-Datenbank.
Für die Forschung bringt es einen geprüften, unveränderlichen Stand der Rohdaten mit sha256 je
Tag. Damit lässt sich später belegen, auf welchen Daten eine Studie lief. Vorbereitet sind:

- Die Liste der archivierten Batches mit `batch_id` und `content_sha256` aus dem Ledger als
  Herkunftsnachweis für Studien.
- Der Rückweg in PostgreSQL (§12, Stufe 3) für eine unabhängige Nachrechnung.

Holdout 2025 bleibt unberührt. Der erste Archivlauf braucht Uzis eigene Freigabe.

