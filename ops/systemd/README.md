# TIM auf Debian: systemd-Units

Gegenstück zu `ops/launchd/` für den Debian-Server aus
[`docs/autonomous_trader/DEBIAN_SERVER_SETUP_TASK_PACKAGE.md`](../../docs/autonomous_trader/DEBIAN_SERVER_SETUP_TASK_PACKAGE.md)
(Paket P3). Nur OBSERVE-Betrieb, keine Exchange-Keys, kein Trading.

## Was hier liegt

| Datei | Ersetzt (launchd) | Art |
|---|---|---|
| `tim-runtime.service` | `com.tim.runtime` | Dauerdienst, `Restart=always` |
| `tim-watchdog.service` | `com.tim.watchdog` | Dauerdienst, startet über `scripts/timctl` neu |
| `tim-candle-finalizer.{service,timer}` | `com.tim.closed-candle-finalizer` | alle 15 s |
| `tim-rolling-liveness.{service,timer}` | `com.tim.rolling-liveness` | alle 60 s |
| `tim-maintenance.{service,timer}` | `com.tim.maintenance` | alle 60 s |
| `tim-coverage-worker.{service,timer}` | `com.tim.coverage-worker` | alle 900 s, `CPUQuota=20%` statt `cpulimit` |
| `tim-backup.{service,timer}` | – | täglich 03:15 UTC, `pg_dump` nach `/var/backups/tim`, 14 Tage (P5) |
| `tim-restore-test.{service,timer}` | – | sonntags 04:30 UTC, Restore in `tim_restore_test` und Zeilenvergleich (P5) |
| `tim-server-health.{service,timer}` | – | alle 60 s, Health- und Lückenprüfung (P6) |
| `tim-qualification-daily.{service,timer}` | – | täglich 00:30 UTC, ein unveränderliches V2-Qualifizierungsmanifest je vollem UTC-Tag nach `data/qualification/daily/`; tut nichts, solange keine Kampagne gestartet ist |
| `tim-checkup.{service,timer}` | – | alle 900 s, Checkup und Vorfall-Melder; nur über `ops/debian/install_checkup.sh` (siehe unten) |
| `tim-checkup.path` | – | startet den Checkup, sobald ein Qwen-Ergebnis in `/var/lib/tim-agent/results` liegt; nur mit `TIM_CHECKUP_DIAGNOSIS=on` |
| `tim-qwen-diagnose.{service,timer}` | – | alle 300 s, Qwen-Diagnose als `tim-agent` (nur lesen, keine Geheimnisse, kein Journal); nur mit `TIM_CHECKUP_DIAGNOSIS=on` |
| `ollama.service.d/tim-limits.conf` | – | Drop-in für das vorhandene `ollama.service`: Grenzen, nur `127.0.0.2:11434`, kein Internet; `AllowedCPUs` schreibt nur das Installskript |
| `50-tim-runtime.rules` | – | polkit: Benutzer `tim` darf nur `tim-runtime.service` starten/stoppen |
| `tim.env.example` | `EnvironmentVariables` der Plists | Vorlage für `/etc/tim/tim.env`, ohne Secrets |

Bewusst nicht portiert: `awake` und `power-state-telemetry` (nur Mac),
`local-qwen-worker`, `broncx-discord-feed` (bleiben auf dem Mac),
`continuous-coverage*` (gehören zur Mac-Kampagne vom 2026-09-24; der Server
bekommt eine eigene Deklaration, Paket P7).

Ollama läuft seit dem 28.09.2026 auf tim-core-01 (`ollama.service`, Modell
`qwen3-coder:30b`, Modelle unter `/srv/tim/models`), nicht auf dem Mac. Die
Unit selbst gehört nicht zu diesem Repo. Das Repo liefert nur das Drop-in
`ollama.service.d/tim-limits.conf`, und das installiert nur
`ops/debian/install_checkup.sh`. Es lädt nie ein Modell herunter (`ollama pull`
gibt es hier nicht).

## Annahmen

- Checkout unter `/opt/tim`, venv unter `/opt/tim/.venv` (Python 3.13).
- Dienstbenutzer `tim` ohne Login-Shell.
- PostgreSQL lokal auf `127.0.0.1:5432`, Passwortdatei
  `/etc/tim/database-password` (Besitzer `tim`, Modus `0600`).
- Schreibrechte der Dienste nur auf `/opt/tim/data` und `/opt/tim/artifacts`.

## Installation (als root, erst nach Freigabe)

Am einfachsten mit `ops/debian/bootstrap.sh`: das Skript erledigt Pakete,
Benutzer, PostgreSQL, Passwortdatei, venv und die Units unten. Ohne `--start`
startet es nichts. Von Hand:

```bash
install -d -o root -g tim -m 0750 /etc/tim
install -o root -g tim -m 0640 /opt/tim/ops/systemd/tim.env.example /etc/tim/tim.env
# Passwortdatei separat anlegen: tim:tim, 0600. Nie ins Repo.
install -d -o tim -g tim -m 0750 /opt/tim/data /opt/tim/artifacts /var/backups/tim

install -o root -g root -m 0644 /opt/tim/ops/systemd/tim-*.service /opt/tim/ops/systemd/tim-*.timer /etc/systemd/system/
install -o root -g root -m 0644 /opt/tim/ops/systemd/50-tim-runtime.rules /etc/polkit-1/rules.d/
systemd-analyze verify /etc/systemd/system/tim-*.service /etc/systemd/system/tim-*.timer
systemctl daemon-reload
systemctl enable --now tim-runtime.service
systemctl enable --now tim-candle-finalizer.timer tim-rolling-liveness.timer tim-maintenance.timer tim-coverage-worker.timer \
  tim-backup.timer tim-restore-test.timer tim-server-health.timer
systemctl enable --now tim-watchdog.service
```

`bootstrap.sh` und das `install` oben kopieren per Glob auch `tim-checkup.*`
und `tim-qwen-diagnose.*`, schalten sie aber nicht ein. `tim-checkup.path` und
das Ollama-Drop-in kopieren sie gar nicht. Das alles macht nur `install_checkup.sh`.

## Checkup und Vorfall-Melder

`tim-checkup.timer` startet alle 15 min `scripts/tim_checkup.py run` als `tim`.
Der Checkup liest Health- und Statusdateien und meldet je Ursache ein GitHub-Issue.
Er repariert nichts, startet nichts neu, füllt keine Lücken und leert keine Queues.

- Installiert und eingeschaltet wird er nur mit `ops/debian/install_checkup.sh`
  (als root, nach dem Deploy des Codes). Das Skript legt `/opt/tim/data/incidents`
  (tim:tim, 0700) und einen leeren Platzhalter `/etc/tim/github-app.pem`
  (root:root, 0600) an.
- Melden ist ab Werk aus. `--configure` schreibt die `TIM_CHECKUP_*`-Zeilen in
  `/etc/tim/tim.env`, erst `dry-run`, nach 24 h und ausdrücklichem Ja `on`.
- Der Schlüssel der GitHub App erreicht den Dienst nur über `LoadCredential=`.
- Ausbauen: `install_checkup.sh --uninstall`. Daten unter
  `/opt/tim/data/incidents` und der Schlüssel bleiben als Beleg.

## Qwen-Diagnose (ab PR-2)

`tim-qwen-diagnose.timer` startet alle 5 min `scripts/tim_checkup.py diagnose`
als Systembenutzer `tim-agent`. Das lokale `qwen3-coder:30b` liest Aufträge des
Checkups, Code unter `/opt/tim` und gefilterte Webseiten und schreibt einen
Vorschlag. Es schreibt nichts ins Repo, führt nichts aus und startet nichts neu.
Das Ergebnis gilt als nicht vertrauenswürdig: Der Checkup prüft es neu, redigiert
es und stellt es nur als Codeblock in einen Kommentar.

- **Benutzer und Austausch** (legt `install_checkup.sh` an):

  | Pfad | Besitzer | Modus |
  |---|---|---|
  | `/var/lib/tim-agent` | root:root | 0755 |
  | `requests/` (Aufträge, HOLD, PAUSE, Quittungen) | tim:tim-agent | 2750 (setgid) |
  | `results/` (Ergebnisse) | tim-agent:tim | 2750 (setgid) |
  | `log/` | tim-agent:tim-agent | 0700 |

  `tim-agent` ist nur in der eigenen Gruppe, nie in `tim`, `systemd-journal`
  oder `adm`. Das Skript prüft das und bricht sonst ab.
- **Sandbox:** kein `EnvironmentFile`, keine Credentials, `/etc/tim`,
  `/opt/tim/data`, Backups, PostgreSQL und `/var/log` unsichtbar. Loopback und
  private Netze sind gesperrt, erlaubt ist nur `127.0.0.2/32` (Ollama). Ist der
  DNS-Resolver nach P0 privat oder lokal, kommt seine Adresse per PR mit `/32`
  in `IPAddressAllow`.
- **Ollama-Drop-in:** `Nice=15`, `CPUQuota=300%`, `MemoryMax=28G`,
  `MemorySwapMax=0`, `IPAddressDeny=any`, Listener `127.0.0.2:11434`.
  `AllowedCPUs` steht nicht im Repo: Das Skript schreibt es nur aus
  `--ollama-cpus LISTE` (zwei physische Kerne samt HT-Geschwistern aus
  `lscpu -e`, höchstens die Hälfte aller CPUs) nach `tim-cpus.conf`. Ohne diese
  Angabe fasst das Skript Ollama gar nicht an (kein Drop-in, kein Neustart, Ollama
  bleibt auf `127.0.0.1`), außer bei einem erneuten Lauf mit `--diagnosis on` und
  vorhandenem `tim-cpus.conf`. Läuft der alte `tim-qwen-worker` noch, bleibt Ollama
  ebenfalls unverändert. Den Zustand vorher sichert das Skript einmalig
  in `/root/attic/ollama.service.before`. Ollama wird nur neu gestartet
  (`try-restart`), wenn sich ein Drop-in geändert hat.
- **Einschalten:** nur mit `TIM_CHECKUP_DIAGNOSIS=on` (`--configure ... --diagnosis on`)
  und nur, wenn der alte `tim-qwen-worker` gestoppt ist. Sonst bleiben Timer und
  Path-Unit installiert, aber aus, und `--configure --diagnosis on` bricht ab, ohne
  `tim.env` zu ändern. Eingeschaltet überwacht der Checkup beide in
  der Klasse UNIT.
- **Path-Unit:** höchstens 12 Starts pro Stunde (`TriggerLimitBurst`, systemd ≥ 250).
  Schreibt `tim-agent` öfter nach `results/`, geht die Path-Unit auf „failed“, und
  der Checkup meldet das als UNIT-Vorfall; der 15-min-Timer läuft weiter.
- **Kalibrieren:** `scripts/tim_checkup.py calibrate` als `tim-server` misst
  wie in Plan Abschnitt 7 und gibt die Werte für die Konfiguration aus; es
  schreibt nichts.
- **Kalibrierung:** Solange Digest, Konfigurations-Hash, Messwerte, `AllowedCPUs`
  und Resolver in `config/tim_checkup.json` fehlen (`null`), endet jeder Lauf
  sofort mit „not calibrated“ und ruft Ollama nicht auf.
- **Ollama-Befehle** brauchen danach `OLLAMA_HOST=127.0.0.2:11434`.
- **Ausbauen:** `install_checkup.sh --uninstall` entfernt auch die Qwen-Units,
  die Path-Unit und die Drop-ins und startet Ollama mit dem alten Stand neu.
  `tim-agent` und `/var/lib/tim-agent` bleiben als Beleg.

Ablauf, Steuerung vom Handy und Rückweg: [`docs/TIM_CHECKUP.md`](../../docs/TIM_CHECKUP.md).

## Prüfen

```bash
systemctl is-active tim-runtime                       # active
systemctl list-timers 'tim-*'
systemctl show ollama -p AllowedCPUs,MemoryMax,MemorySwapMax,Nice,IPAddressDeny; ss -ltn 'sport = :11434'   # 127.0.0.2
systemd-analyze security tim-qwen-diagnose.service | tail -1
sudo -u tim /opt/tim/.venv/bin/python /opt/tim/scripts/timctl status   # service_manager: systemd, pid gesetzt
journalctl -u tim-runtime -n 50
# Selbstheilung: Absturz erzwingen, innerhalb von 30 s wieder active
systemctl kill -s KILL tim-runtime; sleep 20; systemctl is-active tim-runtime
```

## `timctl` auf Linux

`scripts/timctl` erkennt Linux und nutzt dann `systemctl` und `ss` statt
`launchctl` und `netstat`. Es prüft vor jedem Start und Stopp dieselben Gates
wie auf dem Mac (OBSERVE-Manifest, Secret, Datenbank nur auf Loopback,
durable Ingestion). Die Unit unter `/etc/systemd/system/tim-runtime.service`
muss `main.py` aus dem Checkout starten, `WorkingDirectory=/opt/tim` haben und
darf für Gruppe und andere nicht beschreibbar sein.
