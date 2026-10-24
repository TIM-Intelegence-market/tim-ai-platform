# CI auf tim-core-01 (Live- oder CI-Modus)

tim-core-01 übernimmt CI-Läufe neben dem Mac mini, aber **nie gleichzeitig mit dem Live-Betrieb**.

| Modus | läuft | aus |
|---|---|---|
| Live (Standard, auch nach Neustart) | tim-runtime, tim-watchdog, timec | tim-ci-runner, tim-ci-postgres |
| CI | tim-ci-runner, tim-ci-postgres | tim-runtime, tim-watchdog, timec |

Ollama, caddy und PostgreSQL 18 laufen in beiden Modi. Im Live-Modus ist der Runner bei GitHub offline,
alle Jobs gehen an den Mac. `test` kann deshalb nie nur auf diesem Server laufen.

## Bedienen

```bash
tim-mode status
sudo tim-mode ci              # zurück auf Live automatisch nach 6 h; --hours N ändert das, 0 = nie
sudo tim-mode live            # verweigert, solange ein Job läuft; --wait wartet, --force bricht ihn ab
```

Die Garantie „nie beides“ hängt nicht am Skript: `tim-ci-runner.service` hat `Conflicts=` auf die drei
Live-Units. Startet jemand `tim-runtime` von Hand, stoppt systemd den Runner, und umgekehrt.

## Einrichten (einmalig)

```bash
sudo bash ops/linux/setup_ci_runner.sh
```

Aus einem Checkout dieses Repos auf tim-core-01. Das Skript fragt nach dem Registrierungs-Token
(Repo → Settings → Actions → Runners → New self-hosted runner → Linux, Wert hinter `--token`), zeigt und
speichert ihn nicht. Es startet nichts; der Server bleibt im Live-Modus.

- Benutzer `timrunner` ohne sudo, ohne weitere Gruppen, ohne Login-Shell, Home `/srv/ci` (700).
- Test-Datenbank: PostgreSQL 16, Cluster `/srv/ci/pg16`, nur `127.0.0.1:5434`, Rolle `tim`, Passwort
  `tim_ci_only` (öffentliches CI-Passwort aus `ci.yml`), Datenbank `tim_test`, Locale `C.UTF-8`.
- Runner `tim-core-01-ci` unter `/srv/ci/actions-runner`, Prüfsumme aus den Release-Notizen, Python
  `/usr/bin/python3.13`.
- Grenzen der Runner-Unit: `Nice=10`, `CPUQuota=600%` (6 von 8 Kernen), `MemoryMax=16G`; Test-DB `MemoryMax=4G`.
- Abschottung: `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, `NoNewPrivileges=yes`, schreiben nur
  unter `/srv/ci`, `/opt/tim` und `/var/backups` sind unsichtbar.

Labels: zuerst nur `tim-ci-linux` für den Probelauf (`.github/workflows/ci-linux-probe.yml`). Wenn `ci.yml`
auf `[self-hosted, tim-ci]` umgestellt ist, das Label `tim-ci` ergänzen (Settings → Actions → Runners →
tim-core-01-ci → Labels).

## Offen

- Im CI-Modus sammelt tim-runtime nicht, und der Watchdog überwacht nicht. Timer wie `tim-checkup` oder
  `tim-server-health` laufen weiter und können das als Ausfall melden; beim ersten CI-Modus beobachten.

## Entfernen

```bash
sudo tim-mode live
cd /srv/ci/actions-runner && sudo -u timrunner ./config.sh remove --token <Token von Settings → Runners>
sudo rm /etc/systemd/system/tim-ci-runner.service /etc/systemd/system/tim-ci-postgres.service /usr/local/sbin/tim-mode
sudo systemctl daemon-reload && sudo userdel -r timrunner
```
