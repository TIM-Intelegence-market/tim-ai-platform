# TIM live auf dem Mac mini (V2-Qualifizierung)

Seit 20.10.2026 (Entscheid Uzi) läuft TIM für die V2-Qualifizierung auf dem Mac mini statt auf dem
Server. Dieses Blatt beschreibt den sauberen Live-Checkout und den Umzug der Runtime. Nur OBSERVE,
kein Handel, kein Echtgeld.

## Grundsätze

- Eigener Klon `~/TIM-live`, fest auf dem eingefrorenen Commit (detached HEAD), ohne lokale
  Änderungen. Uzis Arbeitsordner `~/Documents/TIM/tim` bleibt unberührt.
- Gleiche Datenbank wie bisher (PostgreSQL auf dem Mac, Port aus `TIM_DATABASE_PORT`, sonst 5432).
  Das Passwort liegt weiter nur in `~/Library/Application Support/TIM/database-password`.
- launchd-Agenten kommen aus `ops/launchd/` und werden mit `scripts/mac_live_install.py` für
  `~/TIM-live` gerendert. Von Hand geänderte Plists zählen beim Start-Gate als Drift.
- Live-Agenten: `com.tim.runtime`, `com.tim.watchdog` (startet die Runtime bei wiederholtem Rot
  über `scripts/timctl` neu), `com.tim.server-health` (jede Minute, schreibt
  `data/operational/server_health.json`), `com.tim.history-recovery` (alle 30 s, holt offene
  aggTrade-Lücken per REST nach, wie `tim-history-recovery.timer` auf dem Server),
  `com.tim.qualification-daily` (stündlich, schreibt nur abgeschlossene UTC-Tage).

## Start-Gates auf macOS

`scripts/v2_start_gates_check.py` erkennt macOS selbst. Unterschiede zum Server:

| Gate | Server (systemd) | Mac (launchd) |
|---|---|---|
| postgresql_security | `ss -ltnH`, nur Loopback | `listen_addresses` nur Loopback und TCP-Verbindung auf jede Nicht-Loopback-Adresse des Macs wird abgewiesen (PostgreSQL läuft als anderer Benutzer, seine Sockets sind nicht auflistbar) |
| watchdog | `tim-watchdog.service` aktiv | `com.tim.watchdog` im Zustand running |
| log_rotation | `logrotate.timer` | TIM rotiert seine JSONL-Logs selbst: ein Archiv `*.gz` jünger als 26 h, kein JSONL über 20 MB, kein launchd-Log über 512 MB |
| configuration_and_commit_frozen | Units in `/etc/systemd/system` = Repo | die fünf Plists in `~/Library/LaunchAgents` = gerenderte Vorlagen |

Alle anderen Gates sind gleich. `time_sync` in `server_health.json` steht auf dem Mac auf AMBER,
weil der Sync-Zustand ohne Admin-Rechte nicht lesbar ist; das ist kein Start-Gate.

## Umzug (einmalig)

```sh
FROZEN=<commit auf platform-main>
git clone https://github.com/uezeyiraydin-cell/tim-ai-platform.git ~/TIM-live
cd ~/TIM-live && git checkout --detach "$FROZEN"
/opt/homebrew/bin/python3.13 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
# timctl und die Prüfskripte lesen das DB-Passwort nur über diese zwei Variablen (wie die Plists)
export TIM_DATABASE_SECRET_PROVIDER=file
export TIM_DATABASE_SECRET_FILE="$HOME/Library/Application Support/TIM/database-password"
mkdir -p data/runtime && cp ~/Library/LaunchAgents/com.tim.runtime.plist data/runtime/com.tim.runtime.plist.before-live
.venv/bin/python scripts/mac_live_install.py          # schreibt die fünf Plists, lädt nichts
.venv/bin/python scripts/timctl safe-stop             # stoppt die alte Runtime sauber
.venv/bin/python scripts/timctl start                 # startet die Runtime aus ~/TIM-live
for l in watchdog server-health history-recovery qualification-daily; do
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tim.$l.plist
done
.venv/bin/python scripts/mac_live_install.py --check  # erwartet "drift": []
```

Rücknahme: Agenten `watchdog`, `server-health`, `history-recovery`, `qualification-daily` mit `launchctl bootout`
entladen, `timctl safe-stop`, gesicherte Plist zurückkopieren, `launchctl bootstrap` für
`com.tim.runtime`.

## Kampagne starten

Wenn mindestens ein Rotationsarchiv da ist (bei laufender Runtime meist nach 20 bis 30 Minuten) und
die volle Suite auf `FROZEN` grün ist:

```sh
cd ~/TIM-live
.venv/bin/python scripts/v2_start_gates_check.py --frozen-commit "$FROZEN" --suite-commit "$FROZEN" \
    --suite-run <URL des Suite-Laufs> --output data/qualification/start_gates_candidate.json
.venv/bin/python scripts/v2_qualification_start.py --start-gates data/qualification/start_gates_candidate.json \
    --approved-by Uzi --decision-ref <Entscheid> --approved-at <UTC-Zeit mit Z>
```

## Was die 34 Tage gefährdet

- Neustarts und macOS-Updates zählen als Ausfall gegen die 95 %. Automatische Updates während des
  Fensters aus, Mac schläft nie (`com.tim.awake`, `com.tim.caffeinate`).
- CI-Runner und Issue-Worker teilen sich den Mac. Bei Speicherdruck zuerst den Worker pausieren.
- Jede Code-Änderung in `~/TIM-live` beendet die Kampagne (neuer Commit, neue Gates).

## TIM Core vor CI (Prioritäten, seit 24.10.)

TIM Core und der CI-Runner teilen sich den Mac mini (8 Kerne: 4 Leistung, 4 Effizienz, 16 GB). launchd
ordnet sie so:

| Dienst | ProcessType | Nice | Wirkung |
|---|---|---|---|
| `com.tim.runtime` | Interactive | 0 | nie gedrosselt, Vorrang auf den Leistungskernen |
| `com.tim.watchdog`, `com.tim.history-recovery` | Standard | 0 | normale Priorität |
| `com.tim.ci-runner`, `com.tim.ci-postgres` | Standard | 10 | volle Kerne, solange TIM sie nicht braucht, sonst weicht CI aus |
| übrige TIM-Agenten (Backup, Worker, Refresh) | Background | – | wie bisher |

Vorher liefen Runtime, Watchdog und CI alle im gedrosselten Band (`ProcessType Background`, Priorität 4).
Sie waren gleichrangig, und Apps wie Browser oder Musik hatten Vorrang vor beiden. `Background` allein für
CI machte den Testschritt 45 bis 50 Minuten lang (20. bis 22.10.). `Standard` mit `Nice 10` hält CI schnell,
solange TIM nichts braucht.

Die Datenbanken bleiben getrennt: TIM nutzt PostgreSQL 18 auf 5432, die CI nutzt PostgreSQL 16 auf 5434
(Benutzer `timrunner`). Die Testdatenbank in `~/Library/Application Support/TIM/test-postgres` ist ebenfalls
eigenständig.

Prüfen (ohne sudo): `ps -axo user,nice,pri,command | grep -E "TIM-live/main.py|Runner.Listener|pytest"`.
Die Runtime darf nicht mehr Priorität 4 (gedrosselt) zeigen, CI-Prozesse zeigen Nice 10.

## Dashboards automatisch aktuell (`com.tim.dashboard-refresh`)

Seit 23.10.2026 hält `scripts/dashboard_refresh.py` die Dashboards auf dem Mac aktuell. Der Agent läuft
alle 10 Minuten aus `~/TIM-live` (eigener LaunchAgent, nicht in `LIVE_AGENTS`, damit die Start-Gates
keinen Drift sehen). Regeln: `ops/dashboard_refresh/policy.json`.

- **Control Center (8765):** neuer Stand von `platform-main` geht nur live, wenn der CI-Job `test` grün ist,
  der Stand ein Nachfolger des laufenden ist, kein Backup läuft, keine Qualifizierungskampagne aktiv ist und
  der letzte Neustart lange genug her ist (20 Minuten, wenn nur Anzeige-Pfade geändert wurden, sonst 60).
  Dann: Checkout, `record_deployment.py` mit CI-Ergebnis und Testzahlen, `timctl restart`, Prüfung auf
  neuen Prozess und `/api/health`. Scheitert etwas, rollt der Agent auf den alten Commit zurück und versucht
  diesen Stand nicht noch einmal.
- **Welcher CI-Lauf zählt (seit 24.10.):** der Lauf auf dem Commit selbst oder auf einem Commit mit
  identischem Baum, also dem PR-Head einer Merge- oder Squash-Zusammenführung (das Ruleset verlangt einen
  aktuellen Branch, deshalb ist der Baum gleich). Der Agent wartet damit nicht mehr auf den zweiten Lauf nach
  dem Merge. Stimmt der Baum nicht überein, zählt nur ein Lauf auf dem Commit selbst.
- **Deploy-Fenster (Entscheid Uzi 25.10.2026, PR #410):** Der Agent wartet nicht auf Studienenden; jeder
  eingespielte Stand ist ein Neustart von 1–2 Minuten Datenlücke. Die Lücken bleiben bewusst begrenzt durch
  den Mindestabstand oben (20/60 Minuten) und die Sammelwirkung des Dashboard-Agenten (mehrere Merges in
  einem Fenster = ein Neustart). Das ist die dokumentierte Ausnahme zur 95-%-Regel (Grün-Plan M2).
- **CI-Testjob (`Runner.Worker`):** schiebt den Neustart nur auf, höchstens 20 Minuten ab dem Moment, in dem
  der Stand einspielbar wäre (`max_defer_minutes`). Der Job nutzt eine eigene PostgreSQL auf 5434; ein
  Neustart von 20 Sekunden stört ihn nicht. Ein Backup (`pg_dump`) sperrt weiterhin hart.
- **Laufende Studie (S-K ab 23.10. 15:55):** nur Anzeige-Änderungen (`display_safe` in der Policy:
  `src/dashboard/`, Doku, Tests, Worker-Dashboard, Agent selbst) gehen live, bis
  `artifacts/v2_completion/sk_end_record.json` existiert. Enthält der neueste Stand eine geschützte Datei,
  geht der neueste freigegebene Vorgänger auf der Hauptlinie live (Anzeige-Fixes vor dem gemischten Commit
  warten nicht mehr). Der Haltegrund steht mit Dateinamen im Control Center („Hält zurück: main.py“) und
  in `dashboard_refresh.json` unter `held_back`.
- **Worker-Dashboard (8767):** wird nur neu gebaut, wenn sich `tools/mac-worker-dashboard` geändert hat
  (`cargo build --locked`, Ziel außerhalb des Checkouts). Nur die Binärdatei wird getauscht, die Plist (mit
  `--allow-host` für das Tailnet) bleibt unverändert.
- **Prüfung:** jede Runde fragt Control Center, Chart, Worker-Dashboard, Qwen-Chat (8770) und Demo-Dashboard
  (8768) ab. Ergebnis: `data/operational/dashboard_refresh.json`, im Control Center unter „Latest evidence →
  Dashboard-Agent“. Verlauf: `~/Library/Application Support/TIM/dashboard-refresh/history.jsonl`.

```sh
cd ~/TIM-live
.venv/bin/python scripts/dashboard_refresh.py --dry-run    # nur entscheiden und prüfen
.venv/bin/python scripts/dashboard_refresh.py --install    # LaunchAgent schreiben und laden
touch "$HOME/Library/Application Support/TIM/dashboard-refresh/PAUSE"   # anhalten (löschen = weiter)
```

## Zweite Kopie der Datenbank-Dumps auf externer SSD (`com.tim.db-backup-mirror`)

Uzis Entscheid vom 26.10.2026 (Grün-Plan B1): zweites Backup-Ziel ist eine externe SSD am Mac mini, kein
zweiter Rechner. Der tägliche Dump (`com.tim.db-backup`, 03:15, `~/Library/Application Support/TIM/backups/live`)
bleibt unverändert; ein zweiter LaunchAgent kopiert um 05:15 den neuesten geprüften Dump samt Prüfsumme auf die SSD.

- **Voraussetzung (Uzi, einmalig):** SSD per Festplattendienstprogramm als APFS (verschlüsselt, Passwort im
  Schlüsselbund, „Beim Starten automatisch aktivieren“) mit dem Namen `TIM-Backup` formatieren. Sie wird dann unter
  `/Volumes/TIM-Backup` eingehängt; der Agent legt dort `live/` an. Platz: mindestens das Fünffache eines Dumps
  (Stand 26.10.: 7,8 GB je Dump, 14 Stände = rund 110 GB).
- **Was der Agent tut:** `scripts/tim_db_backup.py mirror` prüft zuerst, dass das Ziel ein eigenes, externes Volume
  ist (Mount-Punkt nicht die Systemplatte und nicht das Volume der Quelle; `diskutil info` muss ein externes Gerät
  melden). Ohne eingehängte SSD endet der Lauf mit `FAIL` und schreibt nichts. Dann wird der neueste Dump mit
  passender Prüfsumme in eine temporäre Datei kopiert, die Kopie gegen die Prüfsumme geprüft und erst dann
  umbenannt; alte Kopien werden nach `--keep-count 14` beziehungsweise 14 Tagen entfernt, die neueste nie. Kein
  Datenbankzugriff, kein Passwort, `Nice 5` und `LowPriorityIO`.
- **Nachweis:** `data/operational/backup_mirror.json` im Live-Checkout (Status, Quelle, Kopie, Prüfsumme, Volume),
  Log `data/operational/db_backup_mirror_launchd.log`.
- **Grenze:** Die SSD hängt am selben Rechner. Gegen Diebstahl oder Brand schützt sie nur, wenn sie regelmäßig
  getauscht oder außer Haus gebracht wird; das bleibt Handarbeit und steht so im Restrisiko von T02.

Einrichten (nach Merge und Aktualisierung von `~/TIM-live`; die Vorlage zeigt auf `/Users/tim/Documents/TIM/tim`
und wird auf den Live-Checkout umgeschrieben):

```sh
cd ~/TIM-live
sed "s|/Users/tim/Documents/TIM/tim|$HOME/TIM-live|g" ops/launchd/com.tim.db-backup-mirror.plist > ~/Library/LaunchAgents/com.tim.db-backup-mirror.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tim.db-backup-mirror.plist
launchctl kickstart -k gui/$(id -u)/com.tim.db-backup-mirror
sleep 60; cat data/operational/backup_mirror.json
```

Erwartet: `"status": "PASS"`, `"copied": true`, `"external": true`. Rücknahme: `launchctl bootout
gui/$(id -u)/com.tim.db-backup-mirror` und die Plist löschen; die Kopien auf der SSD bleiben.
