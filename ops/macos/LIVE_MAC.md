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
