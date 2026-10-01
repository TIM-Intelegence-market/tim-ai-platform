# Umzug auf tim-core-01: `/srv/tim` → `/opt/tim`

Stand 2026-10-01. Entwurf, am Server wird erst nach Uzis Go etwas geändert.
Gehört zu Schritt 1 aus [`DEBIAN_SERVER_SETUP_TASK_PACKAGE.md`](DEBIAN_SERVER_SETUP_TASK_PACKAGE.md).

## Ausgangslage (gelesen am 2026-10-01, nichts verändert)

| Teil | Alt (`/srv/tim`, User-Units von `tim-server`) | Neu (`/opt/tim`, System-Units) |
|---|---|---|
| Runtime | `runtime/code`, Branch `opencode/runtime-clean-reconstruction` (6ce74a9, 26.09.), nicht auf GitHub | PR #135 (Branch `claude/project-thread-0jjxoq`), installiert, Units deaktiviert |
| Market-Feeds | `market-feeds/code`, Branch `agent/broncx-orderflow` (9bcede7), schreibt `venue_trades`, nicht auf GitHub | fehlt |
| Watchdog, Liveness, Backup | User-Units | System-Units vorhanden |
| Qwen-Worker | User-Unit **und** System-Dienst auf `/srv/tim/repo` (läuft doppelt) | bewusst nicht portiert |
| Datenbank | `127.0.0.1:5432/tim`, Rolle `tim` | dieselbe; `/etc/tim/database-password` = Wert aus `/srv/tim/runtime/secrets/` |

Befund: Seit 30.09. 16:35 UTC entstehen keine Kerzen. Ursache war ein Netzausfall Richtung
Binance (`Errno 113` zu Port 9443, 09:27–17:56 UTC). Seitdem hängt die alte Runtime beim
Nachholen fest (`bounded catch-up page limit 100 reached`, später `durable outbox capacity 50000
reached`) und geht nie zurück in den Live-Betrieb. Der Watchdog startet nicht neu, weil
`venue_trades` noch fließt. Dieselbe Nachhol-Logik steckt auch in `/opt/tim`
(`src/data_ingestion/catchup.py`). Ein Start ohne vorher geschlossene Lücke liefe in dieselbe
Schleife.

## Ziel und Erfolgskriterium

`tim-runtime` aus `/opt/tim` schreibt geschlossene 1m-Kerzen live (Frische ≤ 180 s nach
Close). `tim-server-health` ist GRÜN, Backup und Restore-Test PASS. `venue_trades` fließt
weiter. Die alte Runtime ist gestoppt und deaktiviert, ein Rückweg ist dokumentiert.

## Nicht-Ziele

- Market-Feeds umziehen: Der Code liegt nur auf dem Server. Er bleibt vorerst als User-Unit
  unter `/srv/tim` und kommt später per eigenem PR ins Repo.
- Qwen-Worker, `timec`, `tim-dns-stats`, `tim-healthcheck` anfassen.
- `/srv/tim` löschen oder das Schema `tim_v2_test` ändern.
- Trading in irgendeiner Form. Es bleibt bei OBSERVE, `trading_actions = 0`.

## Schritte

Jeder Schritt hat einen Prüfbefehl. Schlägt einer fehl: anhalten und an Uzi melden.

**M0 Sicherung.** Ein frischer `pg_dump` über `tim-backup.service` (einmalig gestartet, Timer
bleibt aus).
Prüfen: `data/operational/backup_last_run.json` zeigt `PASS`.

**M1 Alte Runtime anhalten.** `systemctl --user disable --now tim-runtime tim-watchdog
tim-rolling-liveness.timer tim-db-backup.timer` als `tim-server`. Die Unit-Dateien bleiben
liegen. `tim-market-feeds` läuft weiter.
Prüfen: `ss -H -ltn 'sport = :8765'` ist leer, `venue_trades` wächst weiter.

**M2 Lücke schließen.** Als Benutzer `tim` mit `/etc/tim/tim.env` läuft
`scripts/tim_catchup.py --max-gaps 100 --max-pages 10000` über die öffentliche Binance-REST-API,
wiederholt bis `status: PASS` oder bis nur noch Lücken übrig sind, die Binance nicht mehr
liefert. Diese werden dann einzeln mit Grund dokumentiert.
Prüfen: `open_gaps` für BTCUSDT ist 0 oder vollständig erklärt. `agg_trades` reicht bis an
die Gegenwart.

**M3 Neue Runtime starten.** `systemctl enable --now tim-runtime`, danach die Timer und zum
Schluss `tim-watchdog`, in derselben Reihenfolge wie `bootstrap.sh --start`.
Prüfen: `systemctl is-active tim-runtime`, `timctl status` meldet `service_manager: systemd`,
nach 5 min ist die neueste geschlossene 1m-Kerze höchstens 180 s alt.

**M4 Abnahme-Kurztests.** `systemctl kill -s KILL tim-runtime`, nach ≤ 30 s wieder `active`.
`tim-server-health` GRÜN. `tim-restore-test.service` einmal von Hand: PASS. `chronyc
tracking` synchron.

**M5 Aufräumen.** `/etc/sudoers.d/90-tim-bootstrap` löschen, prüfen, dass `sudo -n true`
fehlschlägt. Danach 72 h Beobachtung. Erst dann wird das Messfenster deklariert (P7).

## Rückweg

Neu aus, alt an:

```bash
# nur die Units aus /opt/tim/ops/systemd; kein Glob, sonst träfe es tim-dns-stats und tim-healthcheck
sudo systemctl disable --now tim-watchdog tim-runtime tim-candle-finalizer.timer tim-rolling-liveness.timer \
  tim-maintenance.timer tim-coverage-worker.timer tim-backup.timer tim-restore-test.timer tim-server-health.timer
systemctl --user enable --now tim-runtime tim-watchdog tim-rolling-liveness.timer tim-db-backup.timer
```

Das DB-Passwort ist für beide gleich, ein Rückweg ändert daran nichts.

## Risiken

- **Schema.** Alt und neu starten beide mit `--init-schema`. Weicht die neue Schema-Logik von
  der Rekonstruktion ab, könnte das Tabellen von Market-Feeds berühren. Gegenmittel: M0-Dump
  und vor M3 `--init-schema` gegen eine Restore-Kopie testen (`tim_restore_test`).
- **Nachholdauer und Rate-Limit.** Rund 20 h BTCUSDT-aggTrades sind einige tausend
  REST-Seiten. Das Skript drosselt (`--minimum-interval 0.05`). Bei HTTP 429/418 anhalten.
- **629 alte Lücken** (bis 7 Tage). Nicht jede muss für den Live-Betrieb zu sein. Maßgeblich
  ist, ob `recover_before` für den Live-Anschluss durchkommt.
- **Netz.** Der Ausfall am 30.09. lag am Weg über `enp1s0`/pfSense. Kommt er wieder, bleibt
  auch die neue Runtime stehen. Gegenmittel: `tim-server-health` meldet RED, die Ursache
  im Netz bleibt ein eigener Punkt für Uzi.
