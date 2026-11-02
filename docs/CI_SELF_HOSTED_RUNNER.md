# CI auf den eigenen Runnern (Mac mini und tim-core-01)

Stand 2026-11-01. Dieses Repo ist öffentlich, und alle Workflows laufen auf GitHub-gehosteten Runnern (`ubuntu-latest`); `ci.yml` sagt das selbst im Kopfkommentar. Die Runner `mac-mini-tim` und `tim-core-01-ci` bekommen von diesem Repo keine Jobs mehr. Der Rest dieser Datei beschreibt den Aufbau vom 13. bis 25.10.2026, als die Workflows kurzzeitig auf `[self-hosted, tim-ci]` liefen (Grund: das Actions-Kontingent der Organisation war erschöpft, Läufe brachen nach etwa 3 Sekunden ab). Er gilt nur, wenn jemand die Workflows wieder auf eigene Runner umstellt.

**Empfehlung:** Runner, die keine Jobs mehr bekommen, bei GitHub abmelden (Settings → Actions → Runners → Runner entfernen). Sonst bleibt an einem öffentlichen Repo ein Self-hosted-Runner registriert, auf dem später ein umgestellter Workflow Code aus fremden PRs ausführen könnte. Das Abmelden macht ein Maintainer von Hand; diese Datei meldet nichts ab.

Seit 2026-10-25 gibt es zwei Runner mit dem Label `tim-ci`:
- `mac-mini-tim` auf dem Mac mini, immer verfügbar.
- `tim-core-01-ci` auf dem Server `tim-core-01`, nur im CI-Modus. Der Server läuft entweder live (TIM-Dienste) oder als
  CI-Runner, nie beides; umgeschaltet wird mit `sudo tim-mode ci|live`. Im Live-Modus ist der Runner bei GitHub offline
  und alle Jobs gehen an den Mac. Einrichtung, Isolation und Bedienung: `ops/linux/README.md`.

## Was wo läuft (Stand 13. bis 25.10.2026, heute nicht mehr gültig)

| Workflow | Job | Runner | Wann |
|---|---|---|---|
| `ci.yml` | `test` (Pflicht-Check) | `[self-hosted, tim-ci]` (Mac oder tim-core-01) | jeder PR, Push auf `platform-main`, manuell |
| `ci.yml` | `codeql` | `[self-hosted, macOS, tim-ci]` | täglich 02:30 UTC auf `platform-main` und manuell |
| `pr-gate.yml` | `PR gate` (Pflicht-Check) | `[self-hosted, tim-ci]` (Mac oder tim-core-01) | jeder PR gegen `platform-main` |
| `tim-priority-board.yml` | `prioritize` | `[self-hosted, macOS, tim-ci]` | täglich 07:00 UTC |
| `tim-full-suite.yml` | `TIM full suite` | GitHub (`ubuntu-latest`) | nur manuell |
| `auto-merge-controller.yml` | Controller | GitHub (`ubuntu-latest`) | nur manuell, inaktiv |

Was früher doppelt lief:
- Pushes auf `codex/**`, `opencode/**` und `main` starteten `ci.yml` zusätzlich zum Lauf im PR. Diese Push-Läufe gibt es nicht mehr.
- `TIM full suite` führte dieselbe Testsuite ein zweites Mal aus, nur mit TimescaleDB in Docker. Sie ist jetzt nur noch manuell zu starten.
- Bei einem neuen Push in denselben PR ersetzt der neue Lauf den wartenden.
- `codeql` lief nach jedem Merge über 20 Minuten und hielt auf dem einzigen Runner alle PRs dahinter auf. Es läuft jetzt nachts.

Tempo des Testjobs (seit 2026-10-23): Die Suite lief seriell mit dem Standard-Tracer von Coverage, auf dem Mac
rund 35 Minuten. Jetzt läuft sie in zwei Schritten:
- Schritt 1 mit 4 parallelen Prozessen (`pytest-xdist`, `--dist loadgroup`). Alle Testmodule, die die gemeinsame
  PostgreSQL-Testdatenbank nutzen, laufen zusammen auf einem Prozess (Gruppe `postgres-test-db`).
- Schritt 2 seriell: Tests mit der Markierung `serial` (`tests/tim_manager/`, `tests/graph_mcp/` und Module, die das
  echte Repository scannen). Sie scheitern, wenn parallel andere Prozesse Dateien schreiben.
- `COVERAGE_CORE=sysmon` nutzt die Monitoring-Schnittstelle von Python 3.12+; gleiche Coverage, halbe Laufzeit.
Beide Markierungen setzt `tests/conftest.py` automatisch. Ein neues Testmodul mit der Datenbank braucht nichts
extra, solange es `TIM_DURABLE_TEST_DATABASE_URL` liest. Lokal ändert sich nichts: ohne `-n` laufen alle Tests wie bisher.

Pflicht-Checks im Ruleset „platform-main merge conditions“ seit 2026-10-13: `test` und `pr-gate/head`. `TIM full suite` ist kein Pflicht-Check mehr. Das Ruleset hat keine Bypass-Akteure, auch Admins können einen roten oder fehlenden Pflicht-Check nicht übergehen.

Offen für die Auto-Merge-Pipeline: `.github/auto-merge-policy.json` verlangt noch `TIM full suite` als Check im PR. Bevor der Controller eingeschaltet wird, muss entweder dieser Eintrag weg oder `TIM full suite` wieder im PR laufen. Solange der Controller aus ist (`enabled: false`), hat das keine Wirkung.

## Einrichtung (einmalig, auf dem Mac mini)

1. Ein Registrierungs-Token holen: Repo → Settings → Actions → Runners → **New self-hosted runner** → macOS. Den Wert hinter `--token` kopieren. Er gilt eine Stunde.
2. Im Terminal aus einem Checkout dieses Repos ausführen:
   ```bash
   sudo bash ops/macos/setup_ci_runner.sh
   ```
   Das Skript fragt nach dem Token und zeigt ihn nicht an. Es speichert ihn auch nirgends.
3. Danach steht der Runner `mac-mini-tim` unter Settings → Actions → Runners als **Idle**.

Das Skript lässt jeden Schritt aus, der schon erledigt ist. Ein zweiter Lauf ist deshalb harmlos. Es macht Folgendes:
- Es installiert `postgresql@16`, `gh` und `python@3.13` mit Homebrew. Python 3.13 ist das `python3` für das PR-Gate.
- Es legt den versteckten Standardbenutzer `timrunner` an. Der hat keine Admin-Rechte und ein Zufallspasswort, das niemand kennt.
- Es startet eine eigene PostgreSQL-16-Instanz für Tests auf `127.0.0.1:5434` mit der Datenbank `tim_test` und der Rolle `tim`. Das Passwort ist `tim_ci_only`, wie zuvor in `ci.yml`.
- Es lädt den Actions-Runner, prüft die SHA-256-Summe aus den Release-Notizen, registriert ihn mit dem Label `tim-ci` und startet ihn.
- Runner und Datenbank laufen als LaunchDaemons (`com.tim.ci-runner`, `com.tim.ci-postgres`) unter `timrunner`. Sie starten nach einem Neustart auch ohne Anmeldung.

## Sicherheit

- Der Runner führt Code aus PR-Branches aus, und zwar als `timrunner`. Dieser Benutzer kommt nicht an die Daten des Admin-Kontos, also an Schlüssel, SSH-Zugang zu `tim-server`, den Ollama-Worker oder die Checkouts unter `Documents`. Das Skript warnt, wenn das Home-Verzeichnis des Admins für andere lesbar ist.
- Auf dem Runner liegen keine Secrets. `pr-gate.yml` bekommt nur das kurzlebige `github.token` des Laufs und führt keinen PR-Code aus.
- Der Runner ist nur für dieses Repo registriert, nicht für die ganze Organisation. Das Repo ist öffentlich: Läufe aus Forks sind nur mit Freigabe möglich und ein Self-hosted-Runner sollte daran nicht registriert bleiben (siehe Empfehlung oben).
- `tim-core-01` war bis 2026-10-25 bewusst kein Runner, weil dort der Live-Betrieb läuft. Jetzt ist er Runner, aber nur,
  solange der Live-Betrieb gestoppt ist: `tim-ci-runner.service` hat `Conflicts=` auf `tim-runtime`, `tim-watchdog` und
  `timec`, startet nie beim Booten und kehrt nach 6 Stunden automatisch zu Live zurück. Er läuft als `timrunner` ohne
  sudo und ohne Gruppen, mit `ProtectSystem=strict`, `ProtectHome` und gesperrten Pfaden für TIM-Daten, Secrets
  (`/etc/tim`) und die Produktionsdatenbank (Liste in `ops/linux/README.md`); ein Stopp beendet den ganzen Job-Prozessbaum.
  Die Produktionsdatenbank (PostgreSQL 18, Port 5432) läuft weiter; `timrunner` hat dafür keine Zugangsdaten, `tim-mode ci`
  verweigert den Start bei einer `trust`-Regel in deren `pg_hba.conf`, und
  `tests/conftest.py` lässt nur die Testdatenbank zu. Börsen-Keys oder Echtgeld-Zugänge gibt es auf dem Runner nicht.

## Betrieb

- Status: `sudo launchctl print system/com.tim.ci-runner | grep state` und `sudo tail -n 30 /Users/timrunner/Library/Logs/ci-runner.log`
- Neustart: `sudo launchctl kickstart -k system/com.tim.ci-runner`
- Mac: Status und Neustart wie oben. tim-core-01: `sudo tim-mode status`, Log mit `journalctl -u tim-ci-runner -n 50`.
- Ist tim-core-01 im Live-Modus, gibt es nur einen Runner. Jobs warten deshalb aufeinander. Ist der Mac aus, bleiben Läufe in der Warteschlange und starten, sobald er wieder läuft. Nach 24 Stunden bricht GitHub sie ab.

Probelauf auf tim-core-01 (2026-10-25, Lauf 40192069659): gleiche Befehle wie `test`, 5946 passed und 18 skipped
im parallelen Schritt, 243 passed im seriellen, Job rund 4 Minuten. Der Mac braucht ähnlich lange (rund 3 Minuten
am 25.10.); der Gewinn ist ein zweiter Runner, wenn mehrere PRs gleichzeitig warten, nicht ein schnellerer Lauf.

## Zurück zu GitHub-Runnern

Bei `runs-on` wieder `ubuntu-latest` eintragen. In `ci.yml` kommt außerdem der Service-Container `postgres:16` auf Port 5432 zurück, Stand vor diesem Umbau: `git show 0c34171:.github/workflows/ci.yml`.

## Runner entfernen

```bash
sudo launchctl bootout system /Library/LaunchDaemons/com.tim.ci-runner.plist
sudo launchctl bootout system /Library/LaunchDaemons/com.tim.ci-postgres.plist
cd /Users/timrunner/actions-runner && sudo -u timrunner ./config.sh remove --token <Token von Settings → Runners>
sudo rm /Library/LaunchDaemons/com.tim.ci-runner.plist /Library/LaunchDaemons/com.tim.ci-postgres.plist
sudo sysadminctl -deleteUser timrunner
```
