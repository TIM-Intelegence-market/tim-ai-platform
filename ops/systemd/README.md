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
| `tim-checkup.{service,timer}` | – | alle 900 s, Checkup und Vorfall-Melder; nur über `ops/debian/install_checkup.sh` (siehe unten) |
| `50-tim-runtime.rules` | – | polkit: Benutzer `tim` darf nur `tim-runtime.service` starten/stoppen |
| `tim.env.example` | `EnvironmentVariables` der Plists | Vorlage für `/etc/tim/tim.env`, ohne Secrets |

Bewusst nicht portiert: `awake` und `power-state-telemetry` (nur Mac),
`local-qwen-worker`, `broncx-discord-feed` (bleiben auf dem Mac),
`continuous-coverage*` (gehören zur Mac-Kampagne vom 2026-09-24; der Server
bekommt eine eigene Deklaration, Paket P7).

Ollama läuft seit dem 28.09.2026 auf tim-core-01 (`ollama.service`, Modell
`qwen3-coder:30b`, Modelle unter `/srv/tim/models`). Es gehört nicht zu diesen
Units und wird von ihnen weder installiert noch gestartet.

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

`bootstrap.sh` und das `install` oben kopieren per Glob auch `tim-checkup.*`,
schalten den Checkup aber nicht ein. Das macht nur `install_checkup.sh`.

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

Ablauf, Steuerung vom Handy und Rückweg: [`docs/TIM_CHECKUP.md`](../../docs/TIM_CHECKUP.md).

## Prüfen

```bash
systemctl is-active tim-runtime                       # active
systemctl list-timers 'tim-*'
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
