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
sudo tim-mode status          # /usr/local/sbin liegt für normale Benutzer nicht im PATH
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
  unter `/srv/ci`. Unsichtbar sind `/opt/tim`, `/etc/tim` (tim.env, GitHub-App-Schlüssel, DB-Passwort), `/srv/tim`,
  `/var/lib/tim`, `/var/lib/tim-agent`, `/var/backups` sowie Daten, Konfiguration und Socket der Produktionsdatenbank
  (`/srv/postgresql`, `/var/lib/postgresql`, `/etc/postgresql`, `/run/postgresql`).
- `KillMode=control-group`: Beim Stoppen endet der ganze Prozessbaum eines Jobs, nicht nur `run.sh`. `tim-mode live`
  startet die Live-Dienste erst, wenn kein Prozess von `timrunner` mehr läuft (sonst `pkill -KILL`, und bleibt
  dann noch einer übrig, bricht es ab).
- Produktions-PostgreSQL 18 lauscht weiter auf 127.0.0.1:5432. `tim-mode ci` verweigert den Start, solange eine
  `pg_hba.conf` unter `/etc/postgresql` eine `trust`-Regel hat; ohne die braucht PR-Code ein Passwort, das er nicht hat.
- `tim-maintenance.timer` ist im CI-Modus angehalten: Er ruft nach einer Log-Bereinigung `timctl start` auf, das
  würde über `Conflicts=` den laufenden CI-Job beenden. `tim-mode live` startet ihn wieder.

Label: `tim-ci`, dasselbe wie beim Mac; `ci.yml` und `pr-gate.yml` laufen auf `[self-hosted, tim-ci]`.
Der Probelauf vom 25.10.2026 lief noch mit dem Zwischen-Label `tim-ci-linux` (Lauf 40192069659, grün). Beim
Runner von damals `tim-ci` ergänzen und `tim-ci-linux` entfernen: Settings → Actions → Runners → tim-core-01-ci → Labels.

## Issue-Worker für schwere Issues (neben dem Runner)

Auf tim-core-01 läuft zusätzlich der Qwen-Issue-Worker, in beiden Modi. Er nimmt nur Issues mit
`agent:qwen-hard` und rechnet mit dem lokalen `qwen3-coder:30b`; der Mac nimmt die einfachen
(`TIM_WORKER_LANE`, siehe `docs/mac-qwen-issue-worker.md`). Einrichten, aus einem Checkout:

```bash
sudo bash ops/linux/setup_issue_worker.sh
```

Das Skript bricht ab, solange der alte `tim-qwen-worker` läuft (erst `docs/TIM_CHECKUP.md`, Abschnitt
„Einschalten“, Schritt 1), und lädt nie ein Modell. Den Token von `tim-issue-worker-t330` tippst du selbst; er wird nicht
angezeigt und muss genau Push-Rechte haben, ohne Maintain/Admin. Es startet nichts und schaltet nichts ein.

- Benutzer `timworker` ohne sudo, ohne weitere Gruppen, ohne Login-Shell, Home `/srv/worker` (700): Checkout
  `/srv/worker/repo`, Zustand und Ledger `/srv/worker/state`, GitHub-Anmeldung `/srv/worker/.config/gh-tim-mac-worker`.
- `tim-issue-worker.timer` startet `tim-issue-worker.service` alle 5 Minuten. Vor jedem Lauf prüft der
  Sandbox-Selbsttest, dass Tests in bubblewrap weder Netz noch Zugangsdaten noch TIM-Daten sehen; sonst läuft nichts.
- Argumente in `/etc/tim-issue-worker.env` (root, 600). Nach der Einrichtung steht dort `--dry-run` (schreibt nichts).
  Pilot: `TIM_WORKER_ARGS=--pilot-issue <Nummer>` (nur PR, kein Merge), danach `--merge --self-update`. Dort steht
  auch `TIM_QWEN_HARD_URL`: Ollama auf 127.0.0.1, nach dem Checkup-Drop-in auf 127.0.0.2. Wandert Ollama später,
  die Zeile anpassen. Antwortet das Modell nicht, endet jeder Lauf mit Fehler im Journal statt still.
- Grenzen: `Nice=15`, `IOSchedulingClass=idle`, `CPUQuota=100%`, `MemoryMax=4G`, kein Swap. Das Modell selbst rechnet
  in `ollama.service` mit dessen Grenzen. Läuft gerade ein CI-Job (`Runner.Worker`), beginnt der Worker keine neue
  Aufgabe.
- Abschottung wie beim Runner (`ProtectSystem=strict`, `ProtectHome=yes`, `InaccessiblePaths` für TIM-Daten,
  `/srv/ci` und die Produktionsdatenbank), schreiben nur unter `/srv/worker`. Kein Codex- und kein Claude-Fallback.
- Tests in bubblewrap sehen auch `/run` nicht (D-Bus, Journal, Socket der Datenbank).
- Doppelbearbeitung verhindern die Lanes nur, wenn beide Seiten den neuen Code fahren: Erst den Mac auf
  `TIM_WORKER_LANE=easy` umstellen, dann den Timer hier einschalten.
- Anders als bisher liegt damit eine GitHub-Anmeldung auf dem Server: die des Workers, ohne Admin-Rechte, nur für
  `timworker` lesbar.

Ein: `sudo systemctl enable --now tim-issue-worker.timer`. Aus: `sudo systemctl disable --now tim-issue-worker.timer`.
Log: `journalctl -u tim-issue-worker -n 50`.

## Vorfall 25.10.2026

Der erste `tim-mode live` lief noch mit `KillMode=process`. systemd beendete nur `run.sh`; `Runner.Listener` lief
außerhalb der Unit weiter, blieb bei GitHub online und nahm um 16:44, kurz nachdem das Label `tim-ci` gesetzt war,
einen Job an, während TIM live lief und die Test-DB aus war (Lauf 40208120108, Tests ohne Datenbank rot). Seitdem:
`KillMode=control-group`, `tim-mode ci` und `tim-mode live` beenden übrig gebliebene `timrunner`-Prozesse, und
`tim-mode status` warnt im Live-Modus, wenn welche laufen.

## Offen

- `/opt/tim` ist für alle Benutzer lesbar, also auch für `timrunner` (Warnung der Einrichtung am 25.10.2026).
  Die Runner-Unit sperrt den Pfad (`InaccessiblePaths`); die Rechte von `/opt/tim` selbst sind noch zu prüfen.
- Übergangsweise (bis DSL) bekommt tim-core-01 Internet über die Windows-Internetfreigabe des Laptops an `eno1`
  und DNS über `8.8.8.8`. Rückweg: `/var/tmp/tim-resolv-vorher.conf` nach `/etc/resolv.conf` kopieren und die
  alte Standardroute aus `/var/tmp/tim-route-vorher.txt` wiederherstellen.

- Die Runner-Programme unter `/srv/ci/actions-runner` sind für `timrunner` und damit für PR-Code beschreibbar
  (nötig für die Selbst-Aktualisierung des Runners). Ein präparierter Testlauf könnte so einen späteren
  `PR gate`-Lauf und dessen kurzlebiges Token beeinflussen, das Commit-Status setzen darf. Auf dem Mac gilt
  dasselbe. Begrenzt, weil nur Mitwirkende und der Worker PRs öffnen. Später: Programme root gehören lassen
  (nur `_work` und `_diag` schreibbar) oder ephemere Runner.
- Im CI-Modus sammelt tim-runtime nicht, und der Watchdog überwacht nicht. Ein CI-Fenster heißt bis zu 6 Stunden
  ohne Datensammlung auf dem Server; das ist nur vertretbar, solange TIM hauptsächlich auf dem Mac läuft. Timer wie `tim-checkup` oder
  `tim-server-health` laufen weiter und können das als Ausfall melden; beim ersten CI-Modus beobachten.

## Entfernen

```bash
sudo tim-mode live
cd /srv/ci/actions-runner && sudo -u timrunner ./config.sh remove --token <Token von Settings → Runners>
sudo rm /etc/systemd/system/tim-ci-runner.service /etc/systemd/system/tim-ci-postgres.service /usr/local/sbin/tim-mode
sudo systemctl daemon-reload && sudo userdel -r timrunner
```

Issue-Worker:

```bash
sudo systemctl disable --now tim-issue-worker.timer
sudo rm /etc/systemd/system/tim-issue-worker.service /etc/systemd/system/tim-issue-worker.timer /etc/tim-issue-worker.env
sudo systemctl daemon-reload && sudo userdel -r timworker
```
