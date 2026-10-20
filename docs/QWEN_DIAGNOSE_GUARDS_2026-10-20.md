# Guards vor Aktivierung der kleinen Qwen-Diagnose

Bezug: #334, #335, Parent #332. Die Änderung aktiviert keine Diagnose und
ändert weder Modell-, CPU-, Zeit- noch Ressourcenbudgets.

## Einmaldiagnose (#334)

Im Modus `einschuss` läuft kein Werkzeug zum Lesen des Codes. Selbst eine
existierende Datei mit einer gültigen Zeilennummer ist daher keine geprüfte
Fundstelle. Der Ergebnisaufbau entfernt alle strukturierten Code-Fundstellen,
zählt sie als ungeprüft und setzt `needs_human=true`. `code_src` und
`code_locked` werden als `ops_manual` eingestuft. Text bleibt ein Ratschlag,
kein geprüfter Reparaturplan. Andere Diagnosemodi behalten ihren Vertrag.

## Warmhalten (#335)

Vor dem leeren Warmhalte-Aufruf wird `/api/ps` gelesen. Ist irgendein Modell
resident, erfolgt kein `/api/generate`-Aufruf. So fordert der Leerlauf-Tick
nicht erneut 65.536 Kontext-Tokens an und verdrängt keinen anderen Runner.
Der Status unterscheidet `WARM` für das Zielmodell und `RESIDENT_OTHER` für
andere Modelle. Unlesbare oder ungültige Residency führt zu `UNAVAILABLE`
und begrenztem Backoff, ohne blinden Ladeversuch.

Nur bei explizit leerer Residency lädt der Tick das konfigurierte Modell wie
bisher. Echte Worker-Aufträge dürfen weiterhin ihre benötigten Optionen
anfordern. Zwischen Residency-Abfrage und Laden bleibt ein Zeitfenster; diese
Änderung ist kein Scheduler und kein Beweis kollisionsfreier echter Aufträge.

## Noch erforderliche Betriebsabnahme

1. Menschliches Review/Merge, danach kontrollierter Mac-Worker-Rollout.
2. Ein bereits residenter kleiner Diagnosekontext bleibt über mindestens
   einen Warmhalte-Tick erhalten; keine Generate-Anfrage durch den Tick.
3. Kleines Profil mit den belegten Modell-/Config-Hashes aus #332 erneut
   prüfen. `root_owned` erst nach echtem Rechte-Nachweis setzen.
4. Owner deployt den aktuellen Checkup einschließlich Konfiguration und
   prüft die bestehende GitHub-App-/Authority-Konfiguration geheimnisfrei.
   Reporting bleibt bis zu eigener Freigabe aus.
5. Begrenzter Selbsttest und eine geprüfte End-to-End-Diagnose; Health und
   Watchdog bleiben grün. Erst danach über Aktivierung entscheiden.

Ein Code-Merge ersetzt diese Schritte nicht. #332 und die Server-Epics bleiben
offen, bis ihre vollständigen Nachweise vorliegen.
