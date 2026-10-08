# TIM-Checkup und Vorfall-Melder

Runbook für Uzi. Stand: PR-3, also Checkup, Melder, Qwen-Diagnose und die Außenwache vom Mac (Kapitel
[Außenwache vom Mac](#außenwache-vom-mac)). Die Qwen-Diagnose ist ausgeliefert, bleibt aber aus, bis die Messwerte vom Server in der Konfiguration
stehen (Kapitel [Qwen-Diagnose](#qwen-diagnose)).

## Was der Checkup tut

- `tim-checkup.timer` startet alle 15 Minuten `scripts/tim_checkup.py run` als Benutzer `tim`.
  Er prüft tim-core-01 mit fester Logik, ohne KI.
- **Quellen:** `data/operational/server_health.json` samt der Health-Historie der letzten 16 Minuten aus dem
  Journal, die Watchdog-Dateien, der Status von Backup, Restore-Test und Wartung, Unit-Zustände, Plattenplatz,
  Speicher und Last, Netzproben zu Binance und GitHub, der Commit aus `/opt/tim/.git` (gelesen, ohne `git`).
- **Melden:** Pro Ursache entsteht genau ein Issue in `TIM-Intelegence-market/tim-ai-platform`, geschrieben
  von der GitHub App „TIM Reporter“. Die Evidenz steht redigiert in einem Kommentar. Ist die Ursache weg,
  folgt ein Erholungskommentar, dann wird das Issue geschlossen.
- **Puffer:** Ist GitHub nicht erreichbar, bleiben die Meldungen in `/opt/tim/data/incidents/outbox/` und
  gehen später in der richtigen Reihenfolge raus, mit den ursprünglichen Zeitstempeln. Erledigte Einträge
  wandern nach `outbox/done/`, gelöscht wird nichts.
- **Nie:** Der Checkup repariert nichts, startet nichts neu, füllt keine Lücken und leert keine Queues.
  Neu starten darf weiterhin nur der Watchdog. Handeln tust du.

### Klassen

Nur RED öffnet einen Vorfall, AMBER und YELLOW nie. Einzelne Ausreißer öffnen nichts.

| Klasse | Bedeutet | öffnet |
|---|---|---|
| HEALTH_STALE | Health-Datei älter als 5 min oder unlesbar | sofort |
| DISK | Platte voll (Health RED oder ein Dateisystem ≥ 95 %) | sofort |
| DATABASE | Datenbank nicht erreichbar | 3 RED-Proben in 16 min |
| RUNTIME | `tim-runtime` RED oder gestoppt | 3 Proben oder 2 Läufe in Folge |
| NETWORK | Netz zu Binance gestört (Probe auf Port 9443/443 oder Netzmuster im Runtime-Journal) | 2 Läufe in Folge; Lücken unter 3 min nur in `minor.jsonl` |
| DATA_FLOW | Kerzen oder Lücken RED ohne Netzbefund | 3 Proben |
| WATCHDOG | `single_collector`, `postgres_listener` oder `queue_age` im Watchdog | 3 Proben |
| SAFETY | `observe_only` ist `False` oder es gibt Trading-Aktionen | sofort |
| BACKUP | Backup oder Restore-Test fehlgeschlagen | sofort |
| TIME_SYNC | Uhrzeit nicht synchron | 3 Proben |
| UNIT | ein Repo-Timer zwei Läufe in Folge nicht aktiv; mit `--diagnosis on` auch `tim-qwen-diagnose.timer` und `tim-checkup.path` | 2 Läufe |
| SELFTEST | Label `checkup:selftest` am Freigabe-Issue | sofort |

**Vorrang:** `HEALTH_STALE > DISK > DATABASE > RUNTIME > NETWORK > DATA_FLOW > WATCHDOG`. Nur die oberste aktive
Klasse dieser Kette bekommt ein Issue, die anderen stehen dort als Unterbefunde. SAFETY, BACKUP, TIME_SYNC und
UNIT bekommen je ein eigenes Issue. Über `priority:p0` entscheidest du, nie der Melder.

**Erholung:** nach 2 sauberen Läufen. Kommt derselbe Vorfall innerhalb von 2 h wieder, wird das alte Issue
wieder geöffnet, und die Schwelle verdoppelt sich (2, 4, 8 Läufe).

## Melde-Modi

Eingestellt mit `install_checkup.sh --configure --reporting …`, gespeichert als `TIM_CHECKUP_REPORTING` in
`/etc/tim/tim.env`.

| Modus | Was passiert |
|---|---|
| `off` (Standard) | Der Checkup prüft und führt seinen Zustand, spricht aber nicht mit GitHub. |
| `dry-run` | Nur Lesezugriffe. Preflight: Repo sichtbar, Freigabe-Issue gültig und von dir, Labels vorhanden. Jeder Schreibzugriff, der passiert wäre, steht in `/opt/tim/data/incidents/dryrun.jsonl`. |
| `on` | Issues, Labels und Kommentare werden geschrieben. Nur nach 24 h `dry-run` und deinem ausdrücklichen Ja. |

Vorfälle, die unter `off` oder `dry-run` begonnen haben und noch aktiv sind, meldet der erste Lauf mit `on`.

## Steuerung vom Handy: das Freigabe-Issue

Das Freigabe-Issue hast du selbst angelegt (siehe unten). Jeder Lauf liest es einmal. Die Wirkung kommt mit
dem nächsten Lauf, also nach höchstens 15 min, oder sofort mit `sudo systemctl start tim-checkup.service`.

| Am Freigabe-Issue | Wirkung |
|---|---|
| **schließen** | Not-Aus. Kein einziger Schreibzugriff mehr, auch kein Kommentar, kein Label, kein Schließen. Im Journal steht `"reporting": "revoked"`. Wieder öffnen hebt den Not-Aus auf. |
| Label `checkup:silence` | Stumm. Der Checkup prüft und puffert weiter, schreibt aber nichts. Nach dem Entfernen fasst ein Sammelkommentar im Freigabe-Issue zusammen, was inzwischen schon erledigt war. |
| Label `checkup:selftest` | Selbsttest. Genau ein Issue mit Label `selftest`, solange das Label steht. Nach dem Entfernen ein Erholungskommentar, dann wird es geschlossen. |
| Label `checkup:pause-qwen` | Qwen pausiert. Der Checkup schreibt `requests/PAUSE` für 30 min und erneuert es jeden Lauf, solange das Label steht. Es entstehen keine neuen Aufträge, der Agent startet keine Diagnose. Nach dem Entfernen läuft es beim nächsten Lauf wieder. Siehe [Qwen-Diagnose](#qwen-diagnose). |

## Einmalig auf GitHub

1. **App anlegen:** Organisation → Settings → Developer settings → GitHub Apps → New GitHub App.
   - Name „TIM Reporter“, Webhook aus („Active“ abwählen), „Only on this account“.
   - Repository permissions: **Issues: Read and write**, **Metadata: Read-only**. Sonst nichts.
   - Die **App ID** steht oben auf der Seite der App. Der Login des Melders ist `<slug>[bot]`, den Slug zeigt
     die URL `github.com/apps/<slug>`.
2. **Installieren:** „Install App“, nur das Repo `tim-ai-platform` auswählen. Die **Installations-ID** ist die
   Zahl am Ende der URL der Installation (`…/settings/installations/<ID>`).
3. **Private key** erzeugen („Generate a private key“, lädt eine `.pem` herunter). Er kommt per `--app-key` auf
   den Server (siehe Installation). Danach die `.pem` auf dem Mac löschen.
4. **Labels anlegen**, auf dem Mac:
   ```bash
   for l in incident source:tim-checkup priority:p1 incident:network incident:ops incident:code incident:unknown incident:safety selftest checkup:pause-qwen checkup:silence checkup:selftest governance; do gh label create "$l" -R TIM-Intelegence-market/tim-ai-platform --force; done
   ```
5. **Freigabe-Issue** mit deinem eigenen Konto anlegen, nie mit der App. Body ist genau der Text, den
   `install_checkup.sh` am Ende ausgibt, Label `governance`. Zum Beispiel auf dem Mac, nachdem du den Text in
   `body.txt` gelegt hast:
   ```bash
   gh issue create -R TIM-Intelegence-market/tim-ai-platform --title "TIM-Checkup: Freigabe und Steuerung" --label governance --body-file body.txt
   ```
   Die Nummer brauchst du für `--authority-issue`. Die Marker-Zeile im Body nicht von Hand ändern. Ein Issue, das
   jemand anderes oder die App eröffnet hat, zählt nicht.
6. **Benachrichtigungen:** Repo → Watch → Custom → Issues. In GitHub Mobile Push für „Participating“ und
   „Mentions“ einschalten. Jeder Vorfall-Body enthält `cc @uezeyiraydin-cell`.
7. Das **Außenwache-Issue** W (`--watch-issue`): mit deinem Konto eröffnen, Label `status:external-action`.
   Einrichten im Kapitel [Außenwache vom Mac](#außenwache-vom-mac).

### Label-Regeln

- Der Melder kann nur diese Labels setzen, fest im Code: `incident`, `source:tim-checkup`, `priority:p1`,
  `incident:network`, `incident:ops`, `incident:code`, `incident:unknown`, `incident:safety`, `selftest`.
- Nie setzt er `status:*`, `agent:*`, `priority:p0`, `governance` oder `checkup:*`.
- `checkup:*` gehört nur ans Freigabe-Issue, und nur du setzt es.
- An Vorfall-Issues kein `status:ready` und kein `agent:*` setzen, solange Weg 2 gesperrt ist (siehe
  Behebungswege). Sobald eines davon gesetzt ist, ändert der Melder den Body nicht mehr.

## Installation, in dieser Reihenfolge

**Voraussetzungen:** `ops/debian/bootstrap.sh` lief schon (Benutzer `tim`, `/etc/tim/tim.env`), und `/opt/tim`
gehört root (P3). Sonst bricht das Skript mit Exit 7 ab und nennt die erste Datei, die nicht passt. Der Grund:
Der Checkup hält den App-Schlüssel und führt dabei Code aus `/opt/tim` aus, den nur root ändern darf. Abhilfe,
außerhalb von `data/` und `artifacts/`:

```bash
sudo sh -c 'find /opt/tim -xdev \( -path /opt/tim/data -o -path /opt/tim/artifacts \) -prune -o -exec chown -h root:root {} + && find /opt/tim -xdev \( -path /opt/tim/data -o -path /opt/tim/artifacts \) -prune -o ! -type l -exec chmod go-w {} +'
```

**1. Code deployen** (per bundle, der Server braucht keine Zugangsdaten). Auf dem Mac:

```bash
cd ~/Documents/TIM/tim && git fetch -q origin platform-main && git bundle create /tmp/tim.bundle origin/platform-main && git rev-parse origin/platform-main && scp -q /tmp/tim.bundle tim-server:/tmp/tim.bundle
```

Auf dem Server prüfen (die SHA muss zur Ausgabe auf dem Mac passen), dann auschecken:

```bash
sudo sh -c 'cd /opt/tim && git fetch -q /tmp/tim.bundle refs/remotes/origin/platform-main && git rev-parse FETCH_HEAD && git diff --stat HEAD FETCH_HEAD -- main.py src scripts config requirements.txt | tail -3'
sudo sh -c 'install -d -m 0700 /root/attic && cd /opt/tim && git rev-parse HEAD > /root/attic/opt-tim.prev && git checkout -q --detach FETCH_HEAD && { git diff --quiet HEAD@{1} HEAD -- requirements.txt || .venv/bin/pip install -q -r requirements.txt; }'
```

Bei geändertem Runtime-Code danach `sudo systemctl restart tim-runtime`.

**2. Installieren.** Legt `/opt/tim/data/incidents` (tim:tim, 0700), den leeren Platzhalter
`/etc/tim/github-app.pem` (root:root, 0600), den Systembenutzer `tim-agent` und die Austauschordner unter
`/var/lib/tim-agent` an. Installiert die fünf Units (`tim-checkup.*`, `tim-qwen-diagnose.*`), schaltet nur
`tim-checkup.timer` ein und gibt den Text für das Freigabe-Issue aus. Melden und Diagnose bleiben aus. Ollama fasst
dieser Schritt nicht an: kein Drop-in, kein Neustart, Ollama bleibt auf `127.0.0.1:11434`. Das kommt erst mit
`--ollama-cpus` (Qwen, Schritt 3).

```bash
sudo bash /opt/tim/ops/debian/install_checkup.sh
```

**3. GitHub einrichten**, siehe oben.

**4. Schlüssel hinterlegen.** Auf dem Mac `pbcopy < ~/Downloads/<datei>.pem`, auf dem Server einfügen, Strg-D
auf einer leeren Zeile. Die Eingabe wird nicht angezeigt. Danach `pbcopy < /dev/null` und die `.pem` löschen.

```bash
sudo bash /opt/tim/ops/debian/install_checkup.sh --app-key
```

**5. Konfigurieren, dry-run.** Den Login mit `[bot]` in Anführungszeichen setzen, sonst liest die Shell ihn als Muster.

```bash
sudo bash /opt/tim/ops/debian/install_checkup.sh --configure --app-id <ID> --installation-id <ID> --authority-issue <N> --reporter-login '<slug>[bot]' --owner-login uezeyiraydin-cell --reporting dry-run --diagnosis off
```

Das Skript ersetzt nur die `TIM_CHECKUP_*`-Zeilen in `/etc/tim/tim.env`. Alle anderen Zeilen, Besitzer und Modus
bleiben.

**6. Ersten Lauf prüfen:**

```bash
sudo systemctl start tim-checkup.service; sudo journalctl _SYSTEMD_UNIT=tim-checkup.service -n 1 -o cat
```

Erwartet: `"reporting": "dry-run"`, `"preflight": "ok"`, `"journal_access": "ok"`.

**7. 24 h dry-run.** Danach ansehen, welche Issues entstanden wären:

```bash
sudo -u tim /opt/tim/.venv/bin/python /opt/tim/scripts/tim_checkup.py status --since 24h
```

Plausibel und ohne Rauschen? Dann weiter.

**8. Dein ausdrückliches Ja**, im Thread festgehalten. Erst dann dieselbe Zeile wie in Schritt 5 mit
`--reporting on`.

**9. Selbsttest:** Label `checkup:selftest` ans Freigabe-Issue, drei Läufe abwarten. Erwartet: genau 1 Issue,
Push am Handy. Prüfen auf dem Mac:

```bash
gh issue list -R TIM-Intelegence-market/tim-ai-platform -l selftest --state all
```

Label entfernen: genau 1 Erholungskommentar, danach ist das Issue geschlossen.

**10. Not-Aus-Test:** Freigabe-Issue schließen, `sudo systemctl start tim-checkup.service`, dann zeigt
`sudo journalctl _SYSTEMD_UNIT=tim-checkup.service -n 1 -o cat` die Zeile mit `"reporting": "revoked"`, und es gab
keinen Schreibzugriff. Danach wieder öffnen.

### Exit-Codes von `install_checkup.sh`

| Code | Bedeutung |
|---|---|
| 0 | erledigt |
| 1 | nicht als root gestartet, oder der Timer ließ sich beim Ausbauen nicht stoppen |
| 2 | Voraussetzung fehlt (Checkout, Benutzer `tim`, `tim.env`, Units, `scripts/tim_checkup.py`); `--ollama-cpus` bei laufendem alten Worker; `--diagnosis on`, solange etwas fehlt (nichts geändert) |
| 7 | `/opt/tim` gehört nicht root oder ist gruppen- oder weltbeschreibbar |
| 64 | falsche Option oder ungültiger Wert, nichts geändert |
| 65 | kein lesbarer privater Schlüssel eingefügt, nichts geändert |
| andere | ein Befehl im Skript ist fehlgeschlagen; die Ausgabe darüber nennt ihn. Erneut starten ist sicher. |

## Status ansehen

```bash
systemctl list-timers tim-checkup.timer --no-pager                     # nächster Lauf in höchstens 15 min
sudo journalctl _SYSTEMD_UNIT=tim-checkup.service -n 1 -o cat          # letzte Zeile "event": "checkup_end"
sudo -u tim /opt/tim/.venv/bin/python /opt/tim/scripts/tim_checkup.py status
sudo journalctl -u tim-checkup --since -48h -o cat | grep -c '"event": "checkup_end"'   # in 48 h mindestens 185
```

`status` liest nur Dateien und ändert nichts: offene Episoden, letzter Lauf, Puffer, kleine Lücken aus
`minor.jsonl` und die Schreibzugriffe, die der dry-run gemacht hätte. `--since` wählt das Fenster für die beiden
letzten (`90m`, `24h`, `7d`; Standard `24h`). `run` nie von Hand als root starten, das Skript lehnt das ab:
Dateien von root würden dem Benutzer `tim` den eigenen Zustand sperren. Für einen Lauf außer der Reihe gilt
`sudo systemctl start tim-checkup.service`.

Das Feld `reporting` in der `checkup_end`-Zeile:

| Wert | Bedeutet | Was tun |
|---|---|---|
| `off`, `dry-run`, `on` | Modus wie eingestellt, alles in Ordnung | – |
| `revoked` | Freigabe-Issue geschlossen | gewollt? Sonst wieder öffnen |
| `silenced` | Label `checkup:silence` steht | gewollt? Sonst entfernen |
| `authority_missing` | Freigabe-Issue fehlt, ist nicht von dir oder passt nicht zur Registry | Issue prüfen, Nummer in `--configure` prüfen |
| `key_missing` | `/etc/tim/github-app.pem` leer oder unlesbar | `--app-key` |
| `token_invalid` | GitHub lehnt die Anmeldung ab (401) | App-ID, Installations-ID und Schlüssel prüfen |
| `forbidden` | zweimal in Folge 403 | Rechte und Installation der App prüfen |
| `rate_limited` | GitHub bremst, 30 min Pause | abwarten |
| `network_down` | GitHub nicht erreichbar, alles bleibt im Puffer | abwarten; wird nachgereicht |

Exit-Code des Laufs: 0 normal (auch `revoked` und `silenced`), 3 Melden gestört (Schlüssel fehlt bei `on`, 401,
zweimal 403, ältester Puffereintrag über 60 min alt, kein Journal-Zugriff, `TIM_CHECKUP_*`-Werte ungültig oder
unvollständig), 1 interner Fehler. Bei 1 und 3 zeigt `systemctl status tim-checkup` die Unit als fehlgeschlagen.

Weitere Felder der Zeile: `settings` ist `ok` oder nennt die Variable, die nicht passt (nie ihren Wert; Melden ist
dann `off`). `notes` enthält Hinweise des Melders, etwa erreichte Grenzen oder den Befehl für confirm-not-created.
Bei 1 stehen in `error` und `stage` nur Typ und Schritt des Fehlers, nie der Fehlertext.

## Selten: confirm-not-created

Bricht das Netz genau während des Anlegens eines Issues ab, weiß der Melder nicht, ob GitHub es angelegt hat.
Dann legt er für diesen Vorfall nichts blind neu an, sondern prüft jeden Lauf, ob das Issue auftaucht, und
übernimmt es. Taucht es nach mehr als 1 h nicht auf, steht in der `checkup_end`-Zeile im Feld `notes` ein Hinweis
mit dem folgenden Befehl.

Vorher auf GitHub nachsehen, dass es wirklich kein Issue des Melders zu dieser Episode gibt:

```bash
gh issue list -R TIM-Intelegence-market/tim-ai-platform --state all --search "author:app/<slug>"
```

Dann auf dem Server, `<KLASSE>.<episode>` aus dem Hinweis (zum Beispiel `DATA_FLOW.20261007T0315Z`):

```bash
sudo sh -c 'install -o tim -g tim -m 0600 /dev/null /opt/tim/data/incidents/confirm-not-created.<KLASSE>.<episode> && systemctl start tim-checkup.service'
```

Der nächste Lauf gibt den Vorfall erst nach einer festen Prüfung frei: volle Liste ohne Marker der Episode und
mindestens 1 h Abstand zum Anlegeversuch.

## Behebungswege

Das Vorfall-Issue enthält nur feste Felder, keinen Logtext. Die Evidenz steht im Kommentar, immer im Codeblock,
redigiert und ungeprüft.

| Weg | Wann | Ablauf |
|---|---|---|
| **1. Claude-Sitzung** (heute) | Fehler im Code unter `src/` | Du startest selbst eine Claude-Code-Sitzung mit der Vorlage unten. Ergebnis ist ein Draft-PR mit `Closes #N`. Du prüfst und mergst. |
| 2. Pipeline | später | Gesperrt, bis P9 gemergt ist. Die Pipeline bleibt aus. |
| 3. Gesperrte Pfade | `scripts/`, `ops/`, `config/`, `src/tim_incident/`, `src/database/` | Nur du selbst, normaler PR mit genauem Review. Das PR gate greift dort nicht. Nie aus dem Text eines Issues heraus. |
| 4. Kein Code | Netz, Zeit, Platte, Betrieb | Du handelst selbst, zum Beispiel pfSense, `timedatectl`, `df -h`. |

Vorlage für Weg 1:

```text
Behebe Issue #N in TIM-Intelegence-market/tim-ai-platform. Die Evidenz im Issue ist redigiert und ungeprüft:
prüfe jede Annahme selbst im Code. Branch claude/issue-N-<kurzname>. Ändere nur src/ und docs/.
Bestehende Tests nicht ändern, nur neue Dateien tests/**/test_*.py. Nichts unter src/tim_incident/,
src/database/, scripts/, ops/ oder config/. Öffne einen Draft-PR mit "Closes #N" im Text. Kein Merge.
```

Der Branch-Name `claude/issue-N-…` sorgt dafür, dass das PR gate den PR prüft.

**Nach dem Merge** deployst du wie in Schritt 1 der Installation, bei Runtime-Code mit
`sudo systemctl restart tim-runtime`. Hat „Closes #N“ das Issue schon geschlossen, solange der Vorfall auf dem
Server noch aktiv ist, schreibt der Checkup beim nächsten Lauf einmal „noch aktiv, Deploy ausstehend?“ und bleibt
dann still. Ist
der Vorfall nach dem Deploy vorbei, meldet er die Erholung mit Commit. Merge und Deploy bleiben immer bei dir,
Auto-Merge bleibt aus.

## Qwen-Diagnose

Zu einem Vorfall schreibt das lokale Modell `qwen3-coder:30b` auf dem Server einen Diagnose-Kommentar ins
Vorfall-Issue: wahrscheinliche Ursache, betroffene Stellen im Code, Vorschlag, wie man es prüft. Kein Cloud-Modell,
kein Download. Das Modell liegt schon unter `/srv/tim/models`. Nie `ollama pull` auf dem Server.

### Was sie kann und was nicht

| Kann | Kann nicht |
|---|---|
| Den Auftrag des Checkups lesen: redigierte Evidenz und Journal-Auszüge der Units der Klasse | Schreiben, ausführen, neu starten, reparieren. Sie ändert nichts an TIM und nichts an `/opt/tim`. |
| Code lesen: `read_file`, `grep_code` unter `src/ scripts/ config/ ops/ tests/ docs/ main.py`, `requirements*.txt`, `.venv/lib/` | `data/`, `artifacts/`, `.git/`, `.env*` und Dateien mit secret, token, password, credential, `.pem` oder `.key` im Namen lesen. Symlinks folgt sie nicht. |
| Feste Diagnosebefehle: Status einer Unit aus der Liste in `config/tim_checkup.json`, Timer, fehlgeschlagene Units, Platz, Speicher, Zeit, Binance-Ping | Die Datenbank erreichen (127.0.0.1 ist bis auf Ollama auf 127.0.0.2 gesperrt), das Journal lesen, Geheimnisse sehen. Sie läuft als eigener Benutzer `tim-agent` ohne Gruppe `tim`. |
| Im Web suchen und Seiten lesen, eng begrenzt (unten) | Labels setzen, den Body ändern, `status:ready` oder `agent:*` setzen. Ihr Text wird nur Kommentar, immer im Codeblock. |
| `git_log`, erst wenn `agent.root_owned` in der Konfiguration `true` ist | `git_log` ohne diese Freigabe. Sie kommt per PR, nachdem P0/P3 gezeigt haben, dass `/opt/tim` root gehört. |

Alles, was das Modell liefert, gilt als nicht vertrauenswürdig. Der Checkup prüft das Ergebnis neu, bevor es auf
GitHub landet: Schema, Größe, Besitzer der Datei, jede genannte Stelle (Datei und Zeile müssen in `/opt/tim`
existieren), Quellen nur von abgerufenen Seiten der Domainliste, Redaktion und Schlussprüfung. Was nicht passt, fällt
weg oder wird als „verworfen“ gemeldet, nie mit Inhalt.

**Web, die Grenzen:**
- Suche höchstens 3-mal pro Diagnose, mindestens 5 s Abstand. Die Anfrage baut der Code nur aus Wörtern des festen
  Vokabulars in der Konfiguration, errno-Namen, systemd-Ergebniswörtern und Exception-Namen, die in der Evidenz
  stehen und in Python oder im Code definiert sind. Kein Logtext, keine IP, kein Hostname geht in eine Suche.
- Erst DuckDuckGo (HTML), bei Sperre die GitHub-Issue-Suche ohne Anmeldung.
- Abrufen nur über Link-IDs aus vorherigen Treffern, nur https auf der Domainliste: docs.python.org,
  peps.python.org, pypi.org, github.com, raw.githubusercontent.com, www.postgresql.org, magicstack.github.io,
  developers.binance.com, manpages.debian.org, www.freedesktop.org, stackoverflow.com. Treffer anderswo sieht das
  Modell nur als Titel und Ausschnitt. Höchstens 4 Abrufe, 1 MB, 15 s, 3 Weiterleitungen; jede Adresse muss eine
  öffentliche IP sein.
- Den Anbietern dieser Seiten und DuckDuckGo werden die Server-IP und der Zeitpunkt sichtbar.

**Lastschutz:** Eine Diagnose startet nur, wenn genug Speicher frei ist (26 GiB), `load1` unter 4 liegt, PSI unter
den Schwellen bleibt, kein Backup und kein Restore-Test läuft und das Tageslimit (6) nicht erreicht ist. Ollama hat
nur die Kerne aus `--ollama-cpus` (`AllowedCPUs`), höchstens 28 GB und kein Swap. Holt TIM gerade nach (Watchdog `queue_age`, `cursor_age`, `data_age`
nicht GREEN oder `gap_last_60m` RED), schreibt der Checkup `requests/HOLD` und Qwen wartet. Verschlechtert sich
TIM während einer Diagnose oder enden zwei Läufe in Folge ohne Erfolg, schreibt der Checkup `requests/PAUSE` für
24 h und kommentiert „Qwen pausiert: Verdacht auf Lastwirkung“.

### Einschalten, in dieser Reihenfolge

**1. Alten Qwen-Worker stilllegen** (Plan Abschnitt 6, F.1 bis F.6). Er läuft heute als User-Unit von
`tim-server` unter `/home/tim-server/tim-qwen-worker` und als System-Dienst. Erst die Prüfung F.1/F.2 aus dem Plan
machen; zeigt sie Patches, pytest-Läufe, eine `gh`-Anmeldung oder fremde SSH-Schlüssel, zuerst den
Entscheidungspunkt dort abarbeiten. Dann als `tim-server`, ohne sudo (die Schritte sind verkettet, scheitert einer,
wird nichts gelöscht):

```bash
systemctl --user disable --now tim-qwen-worker.service && tar czf ~/qwen-worker-$(date +%F).tgz -C ~ tim-qwen-worker .config/systemd/user/tim-qwen-worker.service && { git -C /srv/tim/repo diff > ~/srv-tim-repo-uncommitted-$(date +%F).patch || echo 'git diff fehlgeschlagen (nur Hinweis)'; } && rm ~/.config/systemd/user/tim-qwen-worker.service && systemctl --user daemon-reload
```

Den System-Dienst stilllegen und ins Archiv legen, nicht löschen:

```bash
sudo sh -c 'install -d -m 0700 /root/attic && systemctl disable --now tim-qwen-worker.service && mv /etc/systemd/system/tim-qwen-worker.service /etc/tim/qwen-worker.env /root/attic/ && systemctl daemon-reload'
```

Nachweis: `pgrep -af '[r]un_local_qwen|[t]im-qwen' || echo keiner` zeigt `keiner`. Nicht anfassen:
`/srv/tim/models`, die Market-Feeds und Linger von `tim-server`. Solange der alte Worker läuft, schaltet das
Installskript die Diagnose nicht ein und sagt das.

**2. Werte aus P0 holen**, nur lesen:
- Kerne für Ollama: `lscpu -e`. Zwei physische Kerne mit ihren HT-Geschwistern, zum Beispiel `2-3,6-7`, höchstens
  die Hälfte aller CPUs.
- DNS-Resolver: `resolvectl status` oder `cat /etc/resolv.conf`. Ist es ein öffentlicher Resolver, ist der Wert
  `public`. Ist es eine private oder eine Loopback-Adresse (etwa `127.0.0.53`), braucht der Agent sie zusätzlich
  in `IPAddressAllow` von `ops/systemd/tim-qwen-diagnose.service` (als `<ip>/32`) und als `agent.resolver` in der
  Konfiguration, beides im selben PR. Ohne erreichbaren Resolver scheitern nur die Web-Werkzeuge, sonst nichts.

**3. Installieren mit der Kernliste.** Erst nach Schritt 1: Läuft der alte Worker noch, bricht das Skript mit
Exit 2 ab und lässt Ollama unverändert. Legt das Ollama-Drop-in an (`tim-limits.conf` und `tim-cpus.conf` aus
`--ollama-cpus`, nie geraten) und startet Ollama einmal neu. Die vorige Ollama-Unit liegt danach unter
`/root/attic/ollama.service.before`.

```bash
sudo bash /opt/tim/ops/debian/install_checkup.sh --ollama-cpus 2-3,6-7
```

Ohne `--ollama-cpus` fasst das Skript Ollama nicht an (Ausnahme: ein erneuter Lauf mit `--diagnosis on` und
vorhandenem `tim-cpus.conf` hält `tim-limits.conf` aktuell). Ollama hört nach diesem Schritt nur noch auf `127.0.0.2:11434`; `ollama`-Befehle brauchen `OLLAMA_HOST=127.0.0.2:11434`. Prüfen:

```bash
systemctl show ollama -p AllowedCPUs,CPUQuotaPerSecUSec,MemoryMax,MemorySwapMax,Nice,IPAddressDeny; ss -ltn 'sport = :11434'
```

**4. Kalibrieren (P2).** Zu einer ruhigen Zeit, nicht zwischen 03:00 und 05:00 UTC, als `tim-server`. Der Befehl
misst gegen Ollama mit denselben Grenzen wie im Betrieb, schreibt nichts und gibt eine JSON-Zeile aus. Er dauert
einige Minuten, beim ersten Laden des Modells länger.

```bash
cd /opt/tim && .venv/bin/python scripts/tim_checkup.py calibrate --endpoint http://127.0.0.2:11434
```

`http://127.0.0.2:11434` ist der Standard. Gegen `http://127.0.0.1:11434` (Ollama ohne Drop-in, also ohne die
Grenzen des Betriebs) misst der Befehl nur mit Warnung, und die Werte gehören nicht in die Konfiguration. Andere
Adressen lehnt der Befehl ab. Jeder Lauf beginnt mit einer neuen Zufallsmarke im Prompt, damit auch eine
Wiederholung innerhalb von 10 min den ersten Aufruf ungecacht misst. Er ruft nur `/api/tags`, `/api/show` und `/api/chat` auf. Fehlt das Modell, bricht er mit einem
Hinweis ab und lädt nichts.

Danach als Inhaber nachweisen, dass TIM ungestört blieb. War vorher alles GREEN, ist das Ergebnis jeweils 0:

```bash
sudo journalctl -u tim-server-health --since -40min -o cat | grep -c '"status": "RED"'; sudo tail -n 80 /opt/tim/data/operational/watchdog.jsonl | grep -c '"status": "RED"'
```

In der Ausgabe stehen unter `paste.agent` die Werte für `config/tim_checkup.json` → `agent`: `model_digest`,
`model_config_sha256`, `measured` (`prompt_tok_s`, `gen_tok_s`, `cache_ok`) und bei Go `tool_mode`. Unter `hint`
stehen der Budget-Modus (`native`, `schema`, `einschuss` oder `no-go`), die Werkzeugrunden, ob `tool_calls`
funktionieren, und PSI vor und nach der Messung. Bei `no-go` die Diagnose nicht einschalten.

Die Werte kommen per PR in die Konfiguration, zusammen mit `ollama_allowed_cpus` (dieselbe Liste wie
`--ollama-cpus`) und `resolver` aus Schritt 2. Solange auch nur einer dieser sieben Werte `null` ist, endet jeder
Diagnose-Lauf sofort mit `"outcome": "not_calibrated"`, ohne Ollama zu fragen. Nach dem Merge deployen wie in
Schritt 1 der Installation.

**5. Einschalten.** Dieselbe Zeile wie in Schritt 5 der Installation, mit `--diagnosis on`:

```bash
sudo bash /opt/tim/ops/debian/install_checkup.sh --configure --app-id <ID> --installation-id <ID> --authority-issue <N> --reporter-login '<slug>[bot]' --owner-login uezeyiraydin-cell --reporting on --diagnosis on
```

Das schaltet `tim-qwen-diagnose.timer` (alle 5 min) und `tim-checkup.path` (holt ein Ergebnis sofort ab) ein, aber
nur, wenn alles da ist: Units, beide Drop-ins, `tim-agent`, die Ordner und kein alter Worker. Sonst nennt das
Skript, was fehlt, bricht mit Exit 2 ab und ändert `/etc/tim/tim.env` nicht. Ab jetzt beobachtet der Checkup die beiden Units in der Klasse UNIT.

**6. Selbsttest.** Label `checkup:selftest` ans Freigabe-Issue wie im Selbsttest des Melders. Der Auftrag dazu
nimmt das konstruierte Bündel `ops/selftest/qwen_selftest_bundle.json` (kein aufgezeichnetes Log; es beschreibt das
begrenzte Nachholen beim Start, `max_pages=100` in `src/data_ingestion/catchup.py`). Erwartet nach höchstens 30 min
ein Diagnose-Kommentar im Selbsttest-Issue mit einer geprüften Stelle in `src/data_ingestion/catchup.py` oder
`src/data_ingestion/durable.py`. Dazu:

```bash
sudo journalctl -u tim-qwen-diagnose -n 5 -o cat
systemd-analyze security tim-qwen-diagnose.service | tail -1
```

### Pausieren

| Wie | Wirkung |
|---|---|
| Label `checkup:pause-qwen` am Freigabe-Issue | Pause, solange das Label steht. Kein neuer Auftrag, keine Diagnose. Ohne sudo, vom Handy. Der erste Checkup-Lauf nach dem Entfernen hebt sie auf. Wirkt nur mit Melden `dry-run` oder `on`, denn nur dann liest der Checkup die Labels. Kann er sie in einem Lauf nicht lesen, bleibt die Pause stehen. |
| `--diagnosis off` | Timer und Path-Unit aus. Aufträge entstehen keine mehr. |
| Pause des Circuit Breakers aufheben | Erst die Ursache im Kommentar „Qwen pausiert“ prüfen. Dann `sudo rm /var/lib/tim-agent/requests/PAUSE`; der nächste Checkup-Lauf schreibt keine neue, solange nichts Neues passiert. |

### Eine Diagnose lesen

Der Kommentar hat zwei Teile:
- **Kopf, feste Felder vom Checkup:** Diagnose-Art (`code_src`, `code_locked`, `ops_manual`, `external_network`,
  `transient`, `unknown`), Sicherheit laut Modell, die geprüften Stellen als `datei:zeile` (Datei und Zeile
  bestätigt, Inhalt nie zitiert), die Zahl der entfernten, nicht bestätigten Stellen, ob ein Mensch nötig ist,
  Modus und Zahl der Werkzeugrunden.
- **Codeblock, Text des Modells:** Zusammenfassung, Ursache, Vorschlag, Prüfung, Begründung der Stellen und
  Quellen. Redigiert, ungeprüft, als Text dargestellt; Links und Bilder darin wirken nicht.

Im Body des Issues ändert sich nur der Abschnitt FIELDS (Diagnose-Art und geprüfte Stellen). Das Label
`incident:code` kommt nur bei `code_src` mit mindestens einer geprüften Stelle, alle unter `src/`, keine unter
`src/tim_incident/` oder `src/database/`. Steht schon `status:ready` oder `agent:*`, bleibt der Body unverändert.

Andere Kommentare zur selben Episode, je Auftrag höchstens einer (Tag `diagnosis-<auftrag>`):
- „Diagnose nicht möglich: <fester Grund>“, zum Beispiel „Modell weicht ab“: Digest oder Konfiguration des Modells
  passen nicht mehr zur Konfiguration. Dann nichts nachladen, sondern klären, wer das Modell geändert hat.
- „Diagnose verworfen: …“: Das Ergebnis hat die Prüfung des Checkups nicht bestanden; vom Inhalt wird nichts
  gezeigt.
- „Diagnose ausgefallen“: 60 min, nachdem der Auftrag startbereit war, kam kein Ergebnis, etwa wegen Last oder
  Tageslimit. Zeit unter HOLD oder Pause zählt nicht: Der Checkup datiert offene Aufträge dann neu. Sie wird nicht
  nachgeholt. Einen Auftrag, den der Agent nicht mehr vor dieser Grenze beenden könnte, beginnt er nicht; er
  meldet ihn als „Diagnose nicht möglich: Zeitlimit überschritten“ (`reason` `too_late`).

Eine Diagnose ist ein Hinweis für dich oder eine Claude-Sitzung (Weg 1), kein Befund. Jede Annahme selbst prüfen.

### Status der Diagnose

```bash
systemctl list-timers tim-qwen-diagnose.timer --no-pager
sudo journalctl -u tim-qwen-diagnose -n 1 -o cat            # letzte Zeile "event": "diagnose_end"
sudo journalctl _SYSTEMD_UNIT=tim-checkup.service -n 1 -o cat   # Feld "qwen" der checkup_end-Zeile
```

`outcome` in der `diagnose_end`-Zeile:

| Wert | Bedeutet |
|---|---|
| `not_calibrated` | Messwerte fehlen in der Konfiguration (`missing` nennt sie). Kein Kontakt zu Ollama. Exit 0. |
| `no_go` | Die Messwerte ergeben kein Budget. Exit 0. |
| `selfcheck_failed` | Die Sandbox stimmt nicht (falscher Benutzer, Gruppe `tim`, lesbares Geheimnis, beschreibbares `/opt/tim`, Token in der Umgebung, PostgreSQL erreichbar). `checks` nennt die Prüfung. Exit 2. Unit und Benutzer prüfen. |
| `paused`, `hold`, `idle` | Pause, TIM holt nach, oder kein Auftrag. Exit 0. |
| `gated` | Lastschutz, `checks` nennt den Grund. Der nächste Lauf versucht es wieder. |
| `ollama_unavailable` | Ollama antwortet nicht. Ein zweiter Versuch folgt. |
| `retry` | Abbruch wegen Last oder Ollama mitten im Lauf (`reason`). Kein Ergebnis, der nächste Lauf versucht es nach dem Gate noch einmal, solange `attempts` reicht. |
| `done`, `failed` | Ergebnis geschrieben (`failed` mit festem `reason`). |
| `write_failed`, `error` | Ergebnis nicht schreibbar oder interner Fehler. Exit 1. |

`diagnose` liest keine `TIM_CHECKUP_*`-Werte: Ob sie läuft, entscheidet allein das Ein- und Ausschalten des Timers.
Im Feld `qwen` der `checkup_end`-Zeile: `hold` (Gründe), `pause` (`label`, `breaker` oder `null`), `breaker`
(Gründe, falls er gerade ausgelöst hat), `ingest` (übernommen, fehlgeschlagen, verworfen), `requests` (neue
Aufträge), `missing` (ausgefallene), `notes` (etwa `no requests: not calibrated`, `diagnosis off` oder
`qwen runs failed without load symptom: exit-code (N)`). Der Breaker zählt für „zwei Läufe in Folge“ nur Läufe, die
systemd mit `timeout`, `oom-kill`, `signal` oder `core-dump` beendet hat (aus dem Journal von
`tim-qwen-diagnose`); `exit-code` (etwa `selfcheck_failed`) steht nur als Hinweis in `notes`.

### Rückweg der Diagnose

- Sofort und ohne sudo: Label `checkup:pause-qwen`.
- Aus: `--configure … --diagnosis off`.
- Ganz weg: `--uninstall` (siehe Rückweg unten). Danach `sudo systemctl cat ollama | diff - /root/attic/ollama.service.before`.
- Alter Worker zurück, erst nach `--uninstall`, denn er erwartet Ollama auf 127.0.0.1:
  `sudo sh -c 'mv /root/attic/tim-qwen-worker.service /etc/systemd/system/ && mv /root/attic/qwen-worker.env /etc/tim/ && systemctl daemon-reload'`,
  dann als `tim-server`: `tar xzf ~/qwen-worker-<DATUM>.tgz -C ~ && systemctl --user daemon-reload && systemctl --user enable --now tim-qwen-worker.service`.

## Außenwache vom Mac

Der Checkup läuft auf dem Server. Ist der Server aus, hängt er oder ist sein Netz weg, meldet er nichts. Diese
Lücke deckt die Außenwache ab: ein LaunchAgent auf deinem Mac, der alle 5 Minuten von außen nachsieht.

### Was sie tut

Ein Durchlauf (`scripts/tim_checkup.py watch`, Code in `src/tim_incident/watch.py`):

1. **Ist der Mac online?** Abfrage von `https://api.github.com/zen` mit 5 s Zeitlimit. Kommt keine Antwort, ist
   der Zustand `UNKNOWN`. Dann gibt es keinen Alarm, und es wird nichts gezählt.
2. **Eine ssh-Abfrage** mit festem Befehl und eigenem Schlüssel `~/.ssh/tim_watch_ed25519`. Der Server führt für
   diesen Schlüssel nur einen Befehl aus: `systemctl show` für `tim-checkup.service` und
   `tim-server-health.service`. Die Ausgabe wird ausgewertet und nie geloggt. Die Abfrage teilt nie eine
   ssh-Verbindung (`ControlMaster=no`, `ControlPath=none`), auch wenn `~/.ssh/config` Multiplexing einschaltet.
3. **Entscheidung:**

   | Zustand | Bedingung |
   |---|---|
   | SILENT | ssh scheitert (Server aus, Netz weg, sshd gestört, Zeitlimit) |
   | STALE | letztes Ende von tim-checkup älter als 35 min, oder von tim-server-health älter als 5 min |
   | IMPAIRED | 2 verschiedene Checkup-Läufe in Folge nicht sauber (`Result` ungleich `success` oder Exit ungleich 0). „In Folge“ heißt: der zweite Lauf startete höchstens 16 min nach dem Ende des ersten. Lagen ungesehene Läufe dazwischen (Mac schlief, ssh weg), zählt nur der neue. Exit 3 heißt „Melden gestört“, sonst „Checkup fehlgeschlagen (Status X)“. |
   | OK | sonst |

   Gezählt wird pro Checkup-Lauf: Derselbe fehlgeschlagene Lauf zählt nur einmal, auch wenn die Wache ihn
   mehrmals sieht.
4. **Alarm** erst bei 2 Abweichungen in Folge. IMPAIRED zählt schon als zwei, denn es braucht zwei Läufe.
   - Genau **1 Kommentar pro Episode** im Außenwache-Issue W, Kennung
     `TIM_OUTSIDE_WATCH:<episode>:<art>`. Wechselt die Art während der Episode (etwa SILENT, dann STALE), kommt
     kein zweiter Kommentar.
   - Bei Erholung (2 Durchläufe mit OK in Folge) **1 Entwarnung** mit der Dauer bis zum ersten OK. Ein einzelnes
     OK zwischen zwei Ausfällen beendet die Episode nicht, so gibt flatterndes ssh keine Kommentarflut.
   - Höchstens 6 Episoden in 24 h bekommen Kommentar und Mitteilung. Der sechste Alarm sagt das dazu, weitere
     Episoden stehen bis zum genannten Zeitpunkt nur im Log (`alarm:<art>:muted`).
   - Dazu jedes Mal eine **macOS-Mitteilung** mit festem Text.
   - Kann ein Kommentar nicht raus, kommt immer eine Mitteilung, und der Durchlauf endet mit Exit 3:
     - Lehnt GitHub den Schlüssel ab (HTTP 401) oder fehlt er im Schlüsselbund: Die offenen Kommentare werden
       verworfen.
     - W geschlossen, gesperrt oder ohne Label, Schlüsselbund gesperrt, Signatur mit `openssl` gescheitert oder
       Token verweigert (falsche App-ID, Installation oder Repo): Die Kommentare bleiben liegen (höchstens 20) und
       gehen raus, sobald es wieder geht. Die Mitteilung kommt einmal, nicht bei jedem Durchlauf.
     - HTTP 403 drei Durchläufe in Folge: Der vorderste Kommentar wird verworfen.
   - Bei einer Netzstörung bleiben die Kommentare still liegen und gehen beim nächsten Durchlauf raus, ohne
     doppelten Kommentar. Erreicht die Wache GitHub 2 Stunden lang nicht (24 Durchläufe im Wachzustand), kommt
     einmal eine Mitteilung: Netz, Proxy oder die Zertifikate der Python-Umgebung prüfen.
5. **Ablage:** Zustand in `~/Library/Application Support/TIM Outside Watch/state.json` (nur für dich lesbar).
   Schlüssel 2 der App liegt im Schlüsselbund. Für die Signatur steht er kurz in einer Datei mit Rechten 0600 im
   selben Ordner. Sie wird gelöscht, sobald `openssl` fertig ist, also bevor die Token-Anfrage rausgeht. Wird ein
   Durchlauf mittendrin beendet (Abmelden, `launchctl bootout`), räumt der nächste Durchlauf übrig gebliebene
   Ordner `tim-watch-*` weg.

Die Wache schreibt nur in W. Der Schreibschutz des Melders lässt für sie genau eine Ausnahme zu: Kommentare mit
der Außenwache-Kennung im konfigurierten Issue W, und nur wenn W offen und nicht gesperrt ist, von einem
Menschen eröffnet wurde (GitHub-Kontotyp „User“, kein Bot und keine App) und das Label `status:external-action`
trägt. Alles andere lehnt der Code ab, bevor etwas gesendet wird. Der
Checkup auf dem Server schreibt nie in W.

Logs: `~/Library/Logs/tim-outside-watch.log`, eine JSON-Zeile pro Durchlauf (`"event": "watch_end"`) mit
Zustand, Alter in Sekunden und Aktionen. Fehler stehen in `tim-outside-watch.err.log`.

### Was sie nicht abdeckt

- **Mac schläft oder ist aus:** Dann gibt es keine Wache. launchd holt einen verpassten Durchlauf nach dem
  Aufwachen nach, aber nicht die Zeit dazwischen.
- **Mac im selben LAN wie der Server:** Fällt das Internet am Standort aus, ist der Mac selbst offline
  (`UNKNOWN`) und schlägt keinen Alarm. Diese Zeit deckt nachträglich der Puffer des Melders auf dem Server ab.
- Die Uhren von Mac und Server werden verglichen. Weichen sie um Minuten ab, stimmen die Altersgrenzen nicht
  mehr. Beide sollten per NTP laufen.
- Die Wache startet nichts neu und repariert nichts. Sie sagt nur Bescheid.

### Einmalig einrichten (P7, ohne sudo)

Vorher müssen auf GitHub die App „TIM Reporter“ und das **Außenwache-Issue W** existieren (Kapitel
[Einmalig auf GitHub](#einmalig-auf-github)). W eröffnest du mit deinem eigenen Konto und gibst ihm das Label
`status:external-action`, damit es nie in die Pipeline gerät:

```bash
gh issue create -R TIM-Intelegence-market/tim-ai-platform --title "TIM-Außenwache vom Mac" --label status:external-action --body "Kommentare der Außenwache vom Mac. Nicht schließen."
```

Die Nummer brauchst du unten als `TIM_WATCH_ISSUE` und auf dem Server für `--watch-issue`, damit der Checkup W
nie anfasst.

1. **ssh-Schlüssel nur für die Wache** erzeugen:
   ```bash
   ssh-keygen -t ed25519 -N '' -C tim-outside-watch -f ~/.ssh/tim_watch_ed25519
   ```
2. **Auf dem Server eintragen**, erst nach einem sauberen Ergebnis der Prüfung F.1. Der Eintrag erlaubt diesem
   Schlüssel genau einen Befehl, ohne Terminal, ohne Weiterleitung:
   ```bash
   printf 'restrict,command="systemctl show --timestamp=unix --property=Id,ActiveState,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp tim-checkup.service tim-server-health.service" %s\n' "$(cat ~/.ssh/tim_watch_ed25519.pub)" | ssh tim-server 'cat >> ~/.ssh/authorized_keys'
   ```
   Der Host-Alias `tim-server` muss in `~/.ssh/config` stehen, und der Host-Schlüssel muss schon in
   `~/.ssh/known_hosts` sein (die Wache läuft mit `BatchMode=yes` und fragt nie nach).
   Probe: `ssh -T -i ~/.ssh/tim_watch_ed25519 -o IdentitiesOnly=yes -o ControlMaster=no -o ControlPath=none tim-server` gibt die Unit-Werte aus. Eine
   Shell bekommst du damit nicht.
3. **Private key 2 der App** erzeugen (GitHub → App → Private keys → Generate) und in den Schlüsselbund legen:
   ```bash
   security add-generic-password -U -s tim-outside-watch -a tim-reporter -w "$(base64 -i <pfad>.pem | tr -d '\n')" && rm <pfad>.pem
   ```
   Für Millisekunden steht der Wert dabei in der Prozessliste. Auf einem Mac, den nur du benutzt, ist das
   vertretbar (Restrisiko R12).
4. **LaunchAgent einrichten:** plist kopieren, die vier Platzhalter `EINTRAGEN` ersetzen, laden.
   ```bash
   cp ops/launchd/com.tim.outside-watch.plist ~/Library/LaunchAgents/
   P=~/Library/LaunchAgents/com.tim.outside-watch.plist
   plutil -replace EnvironmentVariables.TIM_WATCH_ISSUE -string <W> "$P"
   plutil -replace EnvironmentVariables.TIM_WATCH_APP_ID -string <App-ID> "$P"
   plutil -replace EnvironmentVariables.TIM_WATCH_INSTALLATION_ID -string <Installations-ID> "$P"
   plutil -replace EnvironmentVariables.TIM_WATCH_REPORTER_LOGIN -string '<slug>[bot]' "$P"
   launchctl bootstrap gui/$(id -u) "$P"
   ```
   In der plist stehen nur `HOME` und diese vier Werte, keine Geheimnisse. Solange ein Platzhalter drinsteht,
   endet jeder Durchlauf mit Exit 2 und „nicht eingerichtet“, ohne Netzzugriff.

### Testen

Im Repo-Ordner auf dem Mac, mit den Werten aus der plist in der Umgebung:

```bash
cd ~/Documents/TIM/tim
export TIM_WATCH_ISSUE=<W> TIM_WATCH_APP_ID=<App-ID> TIM_WATCH_INSTALLATION_ID=<Installations-ID> TIM_WATCH_REPORTER_LOGIN='<slug>[bot]'
.venv/bin/python scripts/tim_checkup.py watch --once --host tim-server-unreachable.invalid
.venv/bin/python scripts/tim_checkup.py watch --once --host tim-server-unreachable.invalid
.venv/bin/python scripts/tim_checkup.py watch --once
.venv/bin/python scripts/tim_checkup.py watch --once
```

Erwartet:
- Lauf 1: `"state": "SILENT"`, noch kein Kommentar.
- Lauf 2: `"actions": ["alarm:silent"]`, genau 1 Kommentar in W und eine Mitteilung.
- Lauf 3: `"state": "OK"`, `"actions": []`. Ein OK allein beendet die Episode noch nicht.
- Lauf 4: `"actions": ["recovered"]`, genau 1 Entwarnung mit der Dauer.

Der Test nutzt denselben Zustand wie der LaunchAgent. Läuft der Agent schon, die vier Zeilen zügig hintereinander
ausführen oder ihn vorher anhalten: `launchctl bootout gui/$(id -u)/com.tim.outside-watch`. `--once` ist der
Normalfall, ein Durchlauf und Ende; launchd wiederholt ihn alle 300 s.

Exit-Codes: 0 normal (auch bei Alarm), 2 nicht eingerichtet oder ungültiger `--host`, 3 ein Kommentar kann
nicht raus (Schlüssel abgelehnt oder fehlt, Token verweigert, Schlüsselbund oder `openssl` gestört, W nicht
nutzbar, dreimal HTTP 403; jeweils mit Mitteilung), 1 interner Fehler.

### Rückweg der Außenwache

- Anhalten: `launchctl bootout gui/$(id -u)/com.tim.outside-watch`, dann
  `rm ~/Library/LaunchAgents/com.tim.outside-watch.plist`.
- Schlüssel 2 widerrufen: GitHub → App → Private keys, den zweiten löschen; dann
  `security delete-generic-password -s tim-outside-watch -a tim-reporter`.
- ssh-Zugang entziehen: auf dem Server die Zeile mit `tim-outside-watch` aus `~/.ssh/authorized_keys` löschen.

## Rückweg

| Was | Wie |
|---|---|
| Melden sofort stoppen, ohne sudo | Freigabe-Issue schließen oder Label `checkup:silence` |
| Melden aus, Checkup läuft weiter | `--configure` wie in Schritt 5 mit `--reporting off` |
| Qwen-Diagnose aus, Checkup läuft weiter | `--configure` wie in Schritt 5 mit `--diagnosis off`: `tim-qwen-diagnose.timer` und `tim-checkup.path` werden sofort abgeschaltet. Kurzfristig ohne sudo: Label `checkup:pause-qwen`. |
| Checkup ausbauen | `sudo bash /opt/tim/ops/debian/install_checkup.sh --uninstall`: Timer und Path-Unit aus, Units und die TIM-Drop-ins von Ollama weg, `daemon-reload`, `try-restart ollama`. Es bleiben `/opt/tim/data/incidents`, der Schlüssel, die `TIM_CHECKUP_*`-Zeilen, der Benutzer `tim-agent` und `/var/lib/tim-agent` als Beleg. |
| Ollama wie vorher | ergibt sich aus `--uninstall`. Vergleich: `sudo systemctl cat ollama \| diff - /root/attic/ollama.service.before` |
| Schlüssel widerrufen | GitHub → App → Private keys löschen oder die Installation aussetzen; danach `sudo rm /etc/tim/github-app.pem`. Ohne die Datei startet die Unit nicht mehr: vorher ausbauen oder das Installskript neu laufen lassen (legt den leeren Platzhalter an). |
| Code-Stand zurück | `sudo sh -c 'cd /opt/tim && git checkout -q --detach "$(cat /root/attic/opt-tim.prev)" && systemctl restart tim-runtime'` |
| Gate-Sperre aufheben | menschlicher PR, der `src/tim_incident/` aus `deny_prefixes` in `.github/pr-gate-policy.json` nimmt |

## Grenzen

- Nur OBSERVE, kein echtes Geld. Der Checkup ändert nichts an TIM.
- Fällt der Server oder sein Netz ganz aus, kommt kein Issue. Das fängt die Außenwache vom Mac ab, solange der
  Mac wach ist und nicht im selben ausgefallenen Netz hängt.
- Gehen `state.json` und `state.json.prev` verloren, übernimmt der nächste Lauf mit `on` die offenen
  Vorfall-Issues des Melders (Feld `adopted`) und meldet ihre Erholung wie gewohnt. Ein Vorfall, der in den 2 h
  nach dem Verlust neu beginnt, bekommt kein eigenes Issue; er steht nur in `status`.
- Die Redaktion ist feste Logik: Regex, Schwärzung bekannter Geheimnisse und eine unabhängige Schlussprüfung.
  Einen Beweis, dass nie etwas durchrutscht, gibt es nicht.
- `Issues: write` erlaubt GitHub-seitig auch, fremde Issues zu labeln oder zu schließen. Das verhindert nur der
  Code (Schreibschutz, Label-Allowlist).
- Die Schlüsseldatei liest nur root. Während eines Laufs liegt der Schlüssel als Credential vor. Ob andere
  Prozesse derselben UID `tim` ihn dann lesen können, wird bei der Inbetriebnahme geprüft.
- Pushes je Vorfall typisch: Anlegen, Evidenz, Erholung. Höchstens 3 Änderungs-Kommentare pro Episode und 4
  Kommentare pro Vorfall und Tag. Ein Dauerzustand ist stumm, nur die Statuszeile im Body wird höchstens alle
  24 h aktualisiert. Ist die Tagesgrenze erreicht, bleibt ein erholter Vorfall offen (Statuszeile) und wird erst
  nach einem ruhigen Tag geschlossen, damit ein flatternder Vorfall nicht ständig schließt und wieder öffnet.
- Kein Telegram, keine Mail. Push nur über GitHub Mobile.
- Die Qwen-Diagnose ist ein Ratschlag eines lokalen Modells: ungeprüft, möglicherweise falsch, nie eine Aktion.
  Ihre Grenzen stehen im Kapitel [Qwen-Diagnose](#qwen-diagnose).
