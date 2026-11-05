# Restore-Speicher auf tim-core-01

## Befund

Der Restore vom 18.10.2026 scheiterte beim Aufbau von
`venue_trades_time_idx`: PostgreSQL konnte eine Indexdatei nicht erweitern und
meldete `Check free disk space`. Der Produktionscluster liegt laut
`pg_lsclusters` unter `/srv/postgresql/18/main`. Am 20.10. waren auf `/srv`
etwa 30 GiB verfügbar, die Datenbank `tim` laut Owner-Abfrage etwa 38 GiB groß.
Auf `/var` liegen die komprimierten Dumps; dortiger freier Platz belegt keinen
Platz für die expandierte Datenbank auf `/srv`.

Der fehlgeschlagene Scratch-Restore ist laut Owner-Inventar bereits entfernt:
vorhanden waren nur `tim`, `postgres`, `template0` und `template1`. Das tägliche
Backup vom 19.10. war PASS. Ein aktueller erfolgreicher Restore ist damit nicht
belegt.

## Codeänderung

`restore-test` verlangt einen expliziten lokalen PostgreSQL-Speicherpfad.
Vor Checksum-Lesen, `dropdb`, `createdb` oder `pg_restore` wird die expandierte
Quelldatenbankgröße mit einer lesenden `psql`-Abfrage ermittelt. Der freie Platz
auf dem angegebenen Dateisystem muss mindestens zweimal die Datenbankgröße
plus 8 GiB Reserve betragen. Bei fehlenden Angaben oder Platzmangel bleibt der
Lauf FAIL, ohne eine Testdatenbank anzulegen; der Bericht enthält die Rechnung.
Die mitgelieferte Server-Unit verwendet für tim-core-01 `--restore-storage-path /srv`.
Auch die Health-Unit prüft über `--disk-path /srv` das PostgreSQL-Dateisystem
statt des separaten Dateisystems unter `/opt/tim`. Backup-Alter und Prüfsumme
werden weiterhin über `/var/backups/tim` geprüft.

Die Rechnung ist eine konservative Kapazitätsschätzung, keine harte Garantie
gegen gleichzeitiges Wachstum oder abweichende Dumps. Sie ersetzt weder die
Prüfsumme noch den vollständigen Restore, Tabellenvergleich und Scratch-Cleanup.
Sie setzt einen lokalen Cluster mit Daten, Index- und temporären Dateien auf
dem bestätigten Dateisystem voraus. Bei externen Tablespaces, getrenntem WAL,
Remote-DB oder Tunnel muss der Betreiber zuerst die Speicherplanung anpassen.

## Owner-Ablauf

1. Vorhandene September-/01.10.-Altbackups unter `/srv/tim/backups` inventarisieren.
   Aktuelle Backups unter `/var/backups/tim` erhalten. Keine Backups ersatzlos löschen.
2. Verifizierte Umlagerung auf die vorhandenen `/`- und `/var`-Dateisysteme,
   mit mindestens 8 GiB bzw. 16 GiB verbleibender Reserve. SHA256 jeder Quelle
   und jeder Kopie prüfen, bevor die alte Quelldatei entfernt wird. Ein solches
   Umlegen ist weiterhin kein Offsite-Backup.
3. Nur nach Owner-Entscheidung vorhandene LVM-Reserve zur Online-Vergrößerung
   von `/srv` verwenden. Die unformatierte zusätzliche SSD bleibt unberührt.
4. Erst nach menschlichem Review/Merge dieses PRs das Skript und beide Units als
   zusammengehöriges Paket ausrollen. Vorher aktuelle Dateien mit Hash sichern,
   lokale Serveränderungen abgleichen und bei unerwartetem Stand stoppen.
5. Owner: `systemctl daemon-reload`, danach
   `systemctl start --no-block tim-restore-test.service`. Keine Runtime-Neustarts.
6. Abschluss erst mit einem frischen Bericht `restore_test.json`: PASS,
   neue Dump-Prüfsumme, nichtleerer Tabellenvergleich, `scratch_database_dropped=true`.
   Anschließend Health, Datenfrische und fehlgeschlagene Units erneut prüfen.

Rückweg für den Code: gesicherte Skript- und Unit-Fassung zusammen zurückspielen,
`daemon-reload`; bei Platzmangel keinen alten ungeprüften Restore starten.
Altbackups lassen sich anhand des Umlagerungsmanifests zurückkopieren, wenn
ausreichend Platz besteht. Eine LV-Vergrößerung wird nicht automatisch verkleinert.

Weder Speicherreparatur noch Restore-PASS erteilt eine V2-, Qualifikations- oder
Handelsfreigabe.

## Nachtrag 05.11.2026: Scratch-Tablespace auf sda

Bis Anfang November war die Datenbank auf etwa 54 GiB gewachsen (davon etwa
27 GiB `ingestion_outbox`). Der Restore-Test hätte damit etwa 105 GiB frei auf
`/srv` gebraucht, verfügbar waren etwa 66 GiB. Er schlug deshalb am 25.10. und
am 01.11. mit `not enough restore space` fehl, ohne eine Testdatenbank anzulegen.

Auf Owner-Freigabe läuft der Restore jetzt in einem eigenen Tablespace auf der
zweiten SSD (`sda`, LUKS, eingehängt unter `/var/lib/warpgate`):

- Verzeichnis `/var/lib/warpgate/tim-restore-scratch`, per Bind-Mount (`nofail`)
  unter `/var/lib/tim-restore-scratch`, Eigentümer `postgres`, Modus 700.
- `CREATE TABLESPACE tim_restore_scratch LOCATION '/var/lib/tim-restore-scratch'`,
  `GRANT CREATE ON TABLESPACE tim_restore_scratch TO tim`.
- Neue Option `--restore-tablespace`: `createdb --tablespace` legt die
  Scratch-Datenbank dort an, `pg_restore` folgt dem Datenbank-Default.
  `--restore-storage-path` zeigt dann auf das Tablespace-Dateisystem, die
  Platzrechnung bleibt unverändert.
- Drop-in `ops/systemd/tim-restore-test.service.d/scratch-tablespace.conf`.

WAL und Katalog der Scratch-Datenbank bleiben auf `/srv`; bei `max_wal_size`
8 GiB ist das durch die Reserve gedeckt. Erster Lauf am 05.11.2026: PASS,
Dump `tim_20261105T031509Z.dump`, agg_trades 86 412 753 Zeilen identisch,
Scratch-Datenbank gelöscht.

Rückweg: Drop-in entfernen, `daemon-reload`, `DROP TABLESPACE tim_restore_scratch`
(nur leer möglich), Bind-Zeile aus `/etc/fstab` entfernen.
