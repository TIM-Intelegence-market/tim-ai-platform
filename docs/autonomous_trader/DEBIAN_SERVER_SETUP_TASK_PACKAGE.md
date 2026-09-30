# Task-Paket Schritt 1: Debian-Server für den bestehenden Collector

**Stand:** 2026-10-01
**Status:** Vorschlag, wartet auf Go. Dieses Dokument autorisiert keine
Umsetzung, keine Secret-Nutzung, keine privaten Exchange-Aufrufe und kein
Trading. Nur OBSERVE-Betrieb des bestehenden Collectors.
**Bezug:** [DEBIAN_MAC_OPERATING_PLAN.md](DEBIAN_MAC_OPERATING_PLAN.md),
Abschnitt 4 Schritt 1 und Abschnitt 6.

## 1. Ziel und Erfolgskriterium

**Ziel:** Der bestehende Collector (`main.py`, `src/data_ingestion/`) läuft
auf einem Debian-Server als Dienst, mit lokaler PostgreSQL, täglichem Backup
mit Restore-Test, Zeitsynchronisation und Gap-/Health-Monitoring.

**Erfolgskriterium (Abnahme Schritt 1):**

1. `tim-runtime.service` läuft 72 h ohne manuellen Eingriff; ein erzwungener
   Absturz (`systemctl kill -s KILL tim-runtime`) wird innerhalb von 30 s
   selbst behoben.
2. Nach einem Neustart des Servers laufen alle TIM-Units wieder ohne Login.
3. Ein Backup der letzten 24 h existiert und wurde in eine Wegwerf-DB
   zurückgespielt; Zeilenzahlen von `candles` stimmen überein.
4. `chronyc tracking` meldet synchronisiert, Offset unter 50 ms.
5. Der Health-Check meldet eine künstliche Lücke (Collector 5 min gestoppt)
   als ROT, mit Zeitstempel im Journal.
6. Das prospektive Messfenster für Schritt 2 ist vor seinem Start
   festgeschrieben (Datei im Repo, Hash in der Abnahme).

Das Coverage-Ziel von 99,5 % ist **nicht** Teil von Schritt 1, sondern von
Schritt 2. Schritt 1 liefert die Umgebung, in der es messbar wird.

## 2. Nicht-Ziele

- Keine Änderung an Core-1.0-Logik (Aggregator, Hashes, Outbox, Schema).
- Kein Paper-, Shadow- oder Live-Trading, keine Exchange-API-Keys.
- Keine neuen Datenquellen (Funding, OI, Orderbook sind Schritt 3).
- Ollama/Qwen, Broncx-Bot und Research bleiben auf dem Mac.
- Der Mac-Collector wird in Schritt 1 **nicht** abgeschaltet (Parallelbetrieb,
  siehe Risiko R4).

## 3. Befund aus dem Repo (Grundlage der Pakete)

| Befund | Quelle | Folge |
|---|---|---|
| Betrieb ist heute komplett launchd (13 Plists, Pfade `/Users/tim/...`) | `ops/launchd/` | systemd-Gegenstücke nötig |
| `timctl` steuert den Runtime-Dienst nur über `launchctl` und liest eine Plist | `scripts/timctl:70-105` | auf Linux schlägt `status`/`restart` fehl |
| Watchdog fragt `timctl status` ab und startet über `timctl restart` neu | `src/operational/watchdog.py:180`, `scripts/tim_watchdog.py:79` | Watchdog ohne Anpassung auf Debian dauerhaft ROT, Neustart BLOCKED |
| DB-Secret-Provider `keychain`, `pgpass`, `file`, `url-env`; Standard `keychain` | `config/secrets.py:100-107` | auf Debian `file` setzen |
| Schema legt TimescaleDB nur an, wenn verfügbar | `src/database/schema.sql:3,71` | reines PostgreSQL reicht, TimescaleDB optional |
| Mac-only-Dienste: `awake` (caffeinate), `power-state-telemetry` | `ops/launchd/` | entfallen auf dem Server |
| Volle Suite braucht Python 3.13 | Projektgedächtnis | Debian 13 (trixie) liefert 3.13; auf Debian 12 per `uv` |

## 4. Standardannahmen für die offenen Fragen

Die Fragen aus Abschnitt 7 des Betriebsplans sind offen. Bis Uzi anders
entscheidet, gilt:

| Frage | Standard | Warum |
|---|---|---|
| Hardware, Standort | eigener Rechner zu Hause, Debian 13, kabelgebunden, USV empfohlen | Stromausfall wäre sonst eine neue Gap-Ursache; USV-Status wird in der Abnahme notiert |
| Primärquelle | Binance Spot aggTrade bleibt | Core 1.0 ist darauf gebaut; Bybit gehört zu Schritt 3 |
| Messfenster Schritt 2 | 14 Tage, Start frühestens 48 h nach Abnahme von Schritt 1, Beginn und Ende in UTC-Minuten vorab festgeschrieben | kurz genug für einen ersten Nachweis, lang genug für Wochenend- und Reconnect-Fälle |
| Alert-Kanal | zuerst nur Journal und Statusdatei; Telegram erst nach Uzis Go | ein Bot-Token ist ein Secret und gehört nur auf den Server |

## 5. Arbeitspakete

Jedes Paket ist einzeln prüfbar. Pakete mit **(Repo)** sind Code/Dateien im
Repo und laufen über PR und CI. Pakete mit **(Server)** führt Uzi oder eine
Remote-Control-Sitzung auf dem Server aus, nach den Befehlen im Repo.

### P1 (Server) Grundsystem und Zeit

- Debian 13 minimal, Benutzer `tim` ohne Login-Shell für Dienste, SSH nur mit
  Schlüssel, `ufw` nur SSH offen, `unattended-upgrades` für Sicherheitsupdates.
- `chrony` mit mindestens zwei NTP-Pools.
- Checkout unter `/opt/tim` (Branch `platform-main`), venv mit Python 3.13.

**Prüfbefehle:**

```bash
timedatectl show -p NTPSynchronized --value     # yes
chronyc tracking | grep -E 'Leap status|System time'
/opt/tim/.venv/bin/python --version              # Python 3.13.x
sudo ufw status verbose
```

### P2 (Server) PostgreSQL und Secret

- PostgreSQL aus Debian, Datenbank und Rolle `tim`, nur `127.0.0.1`.
- TimescaleDB optional (Schema funktioniert ohne).
- Passwortdatei `/etc/tim/database-password`, Besitzer `tim`, Modus `0600`.
- `/etc/tim/tim.env` (Modus `0640`, keine Secrets darin):
  `TIM_DATABASE_SECRET_PROVIDER=file`,
  `TIM_DATABASE_SECRET_FILE=/etc/tim/database-password`,
  `TIM_ENABLE_OLLAMA=false`.
- Zusätzlich Rolle `tim_readonly` (nur `SELECT`) für die Mac-Kopie.

**Prüfbefehle:**

```bash
stat -c '%U %a' /etc/tim/database-password       # tim 600
sudo -u tim env $(cat /etc/tim/tim.env | xargs) \
  /opt/tim/.venv/bin/python -c "from config.secrets import DatabaseSecretResolver; from config.settings import settings; print(DatabaseSecretResolver().status(settings.database_endpoint))"
# erwartet: provider file, status AVAILABLE, kein Passwort in der Ausgabe
```

### P3 (Repo) systemd-Units

Neuer Ordner `ops/systemd/`, Gegenstücke zu den launchd-Diensten:

| Unit | Ersetzt | Art |
|---|---|---|
| `tim-runtime.service` | `com.tim.runtime` | Dauerdienst, `Restart=always`, `RestartSec=10`, `TimeoutStopSec=45`, `EnvironmentFile=/etc/tim/tim.env` |
| `tim-candle-finalizer.timer` + `.service` | `com.tim.closed-candle-finalizer` | alle 15 s |
| `tim-rolling-liveness.timer` + `.service` | `com.tim.rolling-liveness` | alle 60 s |
| `tim-maintenance.timer` + `.service` | `com.tim.maintenance` | alle 60 s |
| `tim-coverage-worker.timer` + `.service` | `com.tim.coverage-worker` | alle 900 s |
| `tim-watchdog.service` | `com.tim.watchdog` | erst nach P4 aktivieren |

Nicht portiert: `awake`, `power-state-telemetry` (Mac-only), `ollama`,
`local-qwen-worker`, `broncx-discord-feed` (Mac-Rolle), die beiden
`continuous-coverage*`-Dienste (hängen an der Kampagne vom 2026-09-24 auf dem
Mac; für den Server kommt in P7 eine eigene Deklaration).

Alle Units mit `User=tim`, `WorkingDirectory=/opt/tim`, Härtung
(`NoNewPrivileges=yes`, `ProtectSystem=strict`, `ReadWritePaths=/opt/tim/data /opt/tim/artifacts`, `PrivateTmp=yes`).
Dazu ein Test, der jede Unit parst und prüft, dass `ExecStart` auf ein
existierendes Skript im Repo zeigt und kein Secret-Wert in den Units steht.

**Prüfbefehle:**

```bash
python -m pytest tests/test_systemd_units.py -q                # im Repo, CI
systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer   # auf dem Server
systemctl is-active tim-runtime                               # active
systemctl list-timers 'tim-*'
```

### P4 (Repo) `timctl` mit systemd-Backend

`timctl` erkennt die Plattform: auf Linux `systemctl status|start|stop|restart
tim-runtime` statt `launchctl`, auf macOS unverändert. JSON-Ausgabe und
Exit-Codes bleiben gleich, damit Watchdog und `src/agents/monitoring.py`
nichts merken. Testbar über den vorhandenen `TIMCTL_TEST_MODE` mit einem
Fake-`systemctl`.

Das ist Betriebscode, nicht Core-1.0-Logik. Falls Uzi das anders sieht:
Alternative ist, den Watchdog auf dem Server wegzulassen und sich nur auf
`Restart=always` plus P6 zu verlassen.

**Prüfbefehle:**

```bash
python -m pytest tests/ -q -k "timctl or watchdog"
sudo -u tim /opt/tim/.venv/bin/python scripts/timctl status    # status PASS, pid gesetzt
```

### P5 (Repo + Server) Backup und Restore-Test

- `tim-backup.timer` täglich 03:15 UTC: `pg_dump -Fc` nach
  `/var/backups/tim/`, 14 Tage aufbewahren, Prüfsumme daneben.
- `tim-restore-test.timer` wöchentlich: letzten Dump in `tim_restore_test`
  einspielen, Zeilenzahlen von `candles` und `agg_trades` mit der
  Quelle zum Dump-Zeitpunkt vergleichen, Ergebnis als JSON in
  `data/operational/restore_test.json`, danach DB löschen.
- Kopie außer Haus: der **Mac zieht** per `rsync` über SSH (Server braucht
  keine Mac-Zugangsdaten). Das ist zugleich die Read-only-Kopie für Backtests.

**Prüfbefehle:**

```bash
ls -la /var/backups/tim/ | tail -3
sudo systemctl start tim-restore-test.service && cat /opt/tim/data/operational/restore_test.json
# erwartet: "status": "PASS", gleiche Zeilenzahlen
```

### P6 (Repo) Health- und Gap-Check

Skript `scripts/tim_server_health.py` (neu, nur lesend) plus Timer alle 60 s.
Prüft: `tim-runtime` aktiv, Alter der letzten geschlossenen 1m-Kerze unter
180 s, keine fehlende 1m-Minute in den letzten 60 min, Datenträger unter
85 %, `chrony` synchronisiert, letztes Backup jünger als 26 h. Ausgabe als
JSON (`GREEN`/`AMBER`/`RED` je Prüfung) ins Journal und nach
`data/operational/server_health.json`. Alert-Versand (Telegram oder Mail)
nur als abgeschaltete Option, bis Uzi den Kanal freigibt.

Der Monitoring-Agent (`src/agents/monitoring.py`) verlangt Ollama und Qwen
als Pflicht-Tools und wäre auf dem Server ROT. Er läuft in Schritt 1 nicht
auf dem Server.

**Prüfbefehle:**

```bash
python -m pytest tests/test_tim_server_health.py -q
sudo systemctl stop tim-runtime; sleep 300; cat /opt/tim/data/operational/server_health.json; sudo systemctl start tim-runtime
# erwartet: candle_freshness RED, gap_last_60m RED
```

### P7 (Repo) Messfenster festschreiben

Deklaration `artifacts/continuous_coverage/debian_campaign_<start>.json` mit
Start/Ende (UTC-Minute), Symbol, Timeframe `1m`, Ziel 99,5 %, Host-Kennung
und dem Commit von `platform-main`. Wird vor dem Start committet; der Hash
steht in der Abnahme. Grundlage: vorhandenes
`scripts/v2_qualification_preregister.py`, falls es passt, sonst eine
schlanke eigene Deklaration.

**Prüfbefehl:**

```bash
git log -1 --format=%cI -- artifacts/continuous_coverage/debian_campaign_*.json   # liegt vor dem Startzeitpunkt
sha256sum artifacts/continuous_coverage/debian_campaign_*.json
```

## 6. Reihenfolge und Abhängigkeiten

```
P3, P4, P6 (Repo, parallel möglich, je ein PR)  ─┐
P1 → P2 (Server)                                 ├→ Units installieren → P5 → 72-h-Lauf → Abnahme → P7
                                                 ┘
```

P1/P2 hängen nur an der Hardware. P3, P4 und P6 kann ich sofort nach Go
im Repo bauen, ohne Server.

## 7. Risiken

| Nr | Risiko | Gegenmaßnahme |
|---|---|---|
| R1 | Stromausfall oder Router-Neustart erzeugt neue Lücken | USV, Catch-up nach Reconnect (`src/data_ingestion/catchup.py`) im 72-h-Lauf einmal bewusst auslösen und prüfen |
| R2 | Binance sperrt oder drosselt die Server-IP | Health-Check meldet es; kein Workaround über fremde Proxys |
| R3 | `timctl`-Umbau bricht den Mac-Betrieb | macOS-Pfad unverändert, Tests für beide Backends, Mac-Tests laufen weiter |
| R4 | Zwei Collector schreiben in zwei DBs, Evidenz wird vermischt | Server-DB ist allein maßgeblich für Schritt 2; Mac-Collector erst nach Abnahme von Schritt 2 abschalten |
| R5 | Secret landet in Unit, Log oder Repo | Provider `file`, Test in P3 prüft Units, `redact_database_url` bleibt im Einsatz |
| R6 | Plattensatz voll durch Dumps oder Logs | Aufbewahrung 14 Tage, `tim-maintenance` rotiert Logs, Health-Check AMBER ab 85 % |

## 8. Was ich nach Go als Erstes baue

Einen PR gegen `platform-main` mit P3 (`ops/systemd/` plus Unit-Test) und P4
(`timctl` systemd-Backend plus Tests), Prüfung mit
`python -m pytest tests/ -q -m "not local_env"` unter Python 3.13. P6 folgt
als zweiter PR. Die Server-Pakete P1, P2 und P5 laufen danach auf dem
Debian-Rechner, sobald er bereitsteht.
