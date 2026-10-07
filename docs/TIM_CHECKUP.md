# TIM-Checkup und Vorfall-Melder

Runbook für Uzi. Stand: PR-1, also Checkup und Melder. Die Qwen-Diagnose (PR-2) und die Außenwache vom
Mac (PR-3) gibt es noch nicht.

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
| UNIT | ein Repo-Timer zwei Läufe in Folge nicht aktiv | 2 Läufe |
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
| Label `checkup:pause-qwen` | Reserviert für die Qwen-Diagnose (PR-2). Wirkt heute nicht. |

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
7. Das **Außenwache-Issue** (`--watch-issue`) braucht erst PR-3. Jetzt weglassen.

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

**2. Installieren.** Legt `/opt/tim/data/incidents` (tim:tim, 0700) und den leeren Platzhalter
`/etc/tim/github-app.pem` (root:root, 0600) an, installiert die beiden Units, schaltet den Timer ein und gibt den
Text für das Freigabe-Issue aus. Melden bleibt aus.

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
| 2 | Voraussetzung fehlt (Checkout, Benutzer `tim`, `tim.env`, Units, `scripts/tim_checkup.py`) |
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

## Rückweg

| Was | Wie |
|---|---|
| Melden sofort stoppen, ohne sudo | Freigabe-Issue schließen oder Label `checkup:silence` |
| Melden aus, Checkup läuft weiter | `--configure` wie in Schritt 5 mit `--reporting off` |
| Checkup ausbauen | `sudo bash /opt/tim/ops/debian/install_checkup.sh --uninstall`: Timer aus, Units weg, `daemon-reload`. Es bleiben `/opt/tim/data/incidents`, der Schlüssel und die `TIM_CHECKUP_*`-Zeilen als Beleg. |
| Schlüssel widerrufen | GitHub → App → Private keys löschen oder die Installation aussetzen; danach `sudo rm /etc/tim/github-app.pem`. Ohne die Datei startet die Unit nicht mehr: vorher ausbauen oder das Installskript neu laufen lassen (legt den leeren Platzhalter an). |
| Code-Stand zurück | `sudo sh -c 'cd /opt/tim && git checkout -q --detach "$(cat /root/attic/opt-tim.prev)" && systemctl restart tim-runtime'` |
| Gate-Sperre aufheben | menschlicher PR, der `src/tim_incident/` aus `deny_prefixes` in `.github/pr-gate-policy.json` nimmt |

## Grenzen

- Nur OBSERVE, kein echtes Geld. Der Checkup ändert nichts an TIM.
- Fällt der Server oder sein Netz ganz aus, kommt kein Issue. Das fängt erst die Außenwache vom Mac (PR-3).
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
- Die Qwen-Diagnose fehlt noch (PR-2). `--diagnosis on` wirkt heute nicht.
