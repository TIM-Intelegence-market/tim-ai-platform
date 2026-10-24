# Gemeinsamer Backup-Standardpfad auf dem Mac

Backup-CLI und Health-Prüfung verwenden auf macOS standardmäßig
`~/Library/Application Support/TIM/backups/live`. Das entspricht dem expliziten
Ziel des vorhandenen Mac-Backup-Agenten. Auf anderen Plattformen bleibt
`/var/backups/tim` der Standard. `--dir` beziehungsweise `--backup-dir` haben
weiterhin Vorrang; vorhandene Backups werden nicht verschoben oder übernommen.

Der bisherige Health-Standard zeigte auch auf dem Mac auf den Serverpfad und
konnte dort mit `PermissionError` rot melden, obwohl der Backup-Agent einen
anderen Pfad verwendete. Der gemeinsame Standard beseitigt diese Abweichung.
Ein leerer, unlesbarer oder zu alter Backup-Bestand bleibt nach den bisherigen
Regeln rot. Die Änderung erzeugt keinen Dump und ersetzt keinen Restore-Test.

Die Regressionstests führen beide CLI-Einstiege mit isolierten, ersetzten
Collector-/Backup-Funktionen aus: macOS und Linux, Standard und explizites
Ziel, einschließlich eines Benutzerpfades mit Leerzeichen. Dabei wird keine
Datenbank und kein Secret-Provider kontaktiert.

Für den Rollout gelten die Freeze-Regeln der Qualifizierung: Der laufende
Live-Checkout wird durch diesen PR nicht aktualisiert. Eine Installation
geänderten Codes während des eingefrorenen Fensters erfordert eine explizite
Entscheidung über Ende und erneute Registrierung der Kampagne. Ein Merge
allein ist kein Rollout und keine Freigabe eines Backups oder der V2.
