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

## Dashboards automatisch aktuell (`com.tim.dashboard-refresh`)

Seit 23.10.2026 hält `scripts/dashboard_refresh.py` die Dashboards auf dem Mac aktuell. Der Agent läuft
alle 10 Minuten aus `~/TIM-live` (eigener LaunchAgent, nicht in `LIVE_AGENTS`, damit die Start-Gates
keinen Drift sehen). Regeln: `ops/dashboard_refresh/policy.json`.

- **Control Center (8765):** neuer Stand von `platform-main` geht nur live, wenn der CI-Job `test` auf genau
  diesem Commit grün ist, der Stand ein Nachfolger des laufenden ist, kein CI-Testjob (`Runner.Worker`) und
  kein Backup läuft, keine Qualifizierungskampagne aktiv ist und der letzte Neustart mindestens 60 Minuten her
  ist. Dann: Checkout, `record_deployment.py` mit CI-Ergebnis und Testzahlen, `timctl restart`, Prüfung auf
  neuen Prozess und `/api/health`. Scheitert etwas, rollt der Agent auf den alten Commit zurück und versucht
  diesen Stand nicht noch einmal.
- **Laufende Studie (S-K ab 23.10. 15:55):** nur Anzeige-Änderungen (`src/dashboard/`, Doku, Tests,
  Worker-Dashboard) gehen live. Ändert ein Stand Detektoren, Datenpfad, Konfiguration oder Skripte, hält der
  Agent an, bis `artifacts/v2_completion/sk_end_record.json` existiert.
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
