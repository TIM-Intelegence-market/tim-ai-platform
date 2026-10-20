# Übergabe: Projekt-Thread „24/7-Checkup, Qwen und Server-Zustand“

Datum: 2026-10-17
Projekt: `TIM-Intelegence-market/tim-ai-platform`, Server `tim-core-01` (192.168.10.121, Zugang `ssh tim-server`)
Zweck: Damit ChatGPT/Codex an diesem Claude-Projekt-Thread weiterarbeiten kann. Alle Betriebsangaben sind mit Datum versehen und gelten nur für diesen Zeitpunkt; vor jeder Entscheidung frisch prüfen.

## Wo es anfing

Am 06.10. bat Uzi um drei Dinge: das größte verfügbare Qwen-Modell finden, einen 24/7-Checkup alle 15 Minuten starten, Fehlermeldungen des Health-Systems über Pipelines in Issues und Lösungen überführen, und Qwen mit Internet- und Werkzeugzugriff ausstatten. Vorgaben: erst reine Bestandsaufnahme, keine Geheimnisse ausgeben, `tim-runtime` und `/opt/tim` während des Deploys von #159 nicht anfassen. Der Code-Teil wurde als PR gebaut, die Server-Einrichtung als eigener Schritt.

## Entschieden und gebaut

- **Bestandsaufnahme (06.10.)**
  - Mac: Ollama 0.32.0, Modell `qwen3.5:9b` (6,6 GB).
  - Server: Ollama 0.34.1 (`ollama.service`, `OLLAMA_MODELS=/srv/tim/models`), einziges Modell `qwen3-coder:30b` (18 GB). Xeon E3-1270 v6, 4 Kerne/8 Threads, 62 GB RAM, **keine GPU** – Inferenz nur auf der CPU.
  - Platten: `/` 41 GB, `/srv` 137 GB, `/var` 60 GB; zweite Platte `sda` (372 GB) ohne Partition.
  - Internet vom Server: ollama.com, api.github.com und DuckDuckGo erreichbar.
- **Größeres Qwen-Modell:** lokal existiert keins. Der einzige größere Kandidat ist `qwen3-coder:480b-cloud` (Ollama Cloud). Er läuft bei ollama.com, braucht `ollama signin`, und Code und Logs würden dann das Haus verlassen. **Noch nicht entschieden**, siehe „Offen“. `/srv/tim/models/qwen` ist ohne sudo nicht lesbar.
- **Alter Qwen-Worker:**
  - Es gibt zwei Units mit dem Namen `tim-qwen-worker.service`. Die gehärtete System-Unit (`/etc/systemd/system`, Code `/srv/tim/repo`) ist aus. Aktiv ist die User-Unit von `tim-server` (Code `/home/tim-server/tim-qwen-worker`, kein eigenes Git-Repo).
  - Beide nutzen `qwen3-coder:30b` über das lokale Ollama `127.0.0.1:11434`.
  - Ein GitHub-Token wird nur aus den Umgebungsvariablen `GITHUB_TOKEN`/`GH_TOKEN` gelesen, und keine Unit setzt sie.
- **#164 (gemergt 08.10.):** 24/7-Checkup mit Vorfall-Issues, lokaler Qwen-Diagnose (Werkzeuge, gefilterter Webzugang) und Außenwache vom Mac. Anleitung: [TIM_CHECKUP.md](TIM_CHECKUP.md). Installer: `ops/debian/install_checkup.sh`. Er braucht eine GitHub App und einmal sudo.
- **Danach (Auswahl, alle gemergt):**
  - Backup behält höchstens 3 Dumps: #190.
  - Fehlende Kerzen offline nachbauen (B5): #178, #183.
  - Mac-Qwen-Issue-Worker mit Codex- und Claude-Fallback, Sandbox-Tests, Triage und Dashboard: #167–#176, #184, #213, #222.
  - Worker bevorzugt den Server und hält Qwen warm: #280.
  - Die Repair-Gates und Teilaufgaben aus M09 (#14–#21) arbeitet der Worker in vielen kleinen PRs ab (#221–#326).
  - Seit dem 13.10. wurden 62 Issues geschlossen. Am 17.10. war kein PR offen.

## Was nicht funktioniert hat

- **Marktdaten seit 07.10. eingefroren** (Stand 12.10., 22:10 MESZ):
  - Die neueste Kerze stammte vom 07.10., 02:07 UTC.
  - `tim-runtime` lief, hing aber im Nachholen fest: Die Binance-Verbindung brach etwa alle 6 Minuten ab („catch-up … exceeded 300s“), und in 12 Minuten Echtzeit kamen nur rund 5 Minuten Daten herein. Den Rückstand holt sie so nie auf.
  - Beginn am 07.10. gegen 03:31 MESZ mit Neustarts im Abstand von 2–3 Minuten und TLS-Handshake-Timeouts zu Binance, also zur Zeit des Deploys von #159.
  - Ob #178/#183 das auf dem Server gelöst haben, ist **nicht verifiziert**.
- **`/var` war zu 93 % voll** (12.10.): 12 Dumps mit zusammen 50 GB in `/var/backups/tim`, ohne Rotation. Die Backups vom 11. und 12.10. scheiterten mit „kein Speicherplatz“. Die Rotation aus #190 ist gemergt, ob sie deployt ist, ist **nicht verifiziert**.
- **Ausgefallene Units (12.10.):**
  - `tim-backup`
  - `tim-server-health`
  - `tim-rolling-liveness` (meldete 0 % Abdeckung)
  - `tim-healthcheck` (meldet `FAIL tim-qwen-worker.service`, weil die System-Unit aus ist)
- **Checkup aus #164 war am 12.10. noch nicht installiert:** `tim-checkup.timer` und `tim-qwen-diagnose.timer` waren auf dem Server nicht vorhanden.
- **Server am 17.10. nicht erreichbar:** SSH und Ping auf 192.168.10.121 liefen aus dem LAN (Mac 192.168.10.177) in einen Timeout. Ein aktueller Server-Stand fehlt deshalb.
- Als `tim-server` gibt es **kein sudo**. Dumps, `/etc/tim` und die System-Units brauchen Root bzw. den Benutzer `tim`.

## Wichtige Dateien

- [TIM_CHECKUP.md](TIM_CHECKUP.md): Aufbau und Einrichtung des Checkups.
- `ops/debian/install_checkup.sh`, `ops/systemd/tim-checkup.*`, `ops/systemd/tim-qwen-diagnose.*`: Installer und Units.
- `src/tim_incident/`: Checkup, Vorfall-Issues, Qwen-Diagnose, Werkzeuge, Redaction.
- [DEFERRED_CANDLE_REBUILD.md](DEFERRED_CANDLE_REBUILD.md): Kerzen nachbauen (B5).
- [ISSUE_WORKFLOW.md](ISSUE_WORKFLOW.md): verbindliche Issue-Struktur für den Worker.
- [TIM_LINUX_QUBE_PLAN.md](TIM_LINUX_QUBE_PLAN.md): verbindliche Roadmap und Gates.

## Prüfen, ob noch alles steht

Auf dem Server (`ssh tim-server`), nur lesend:

- `systemctl --failed`: Im gesunden Zustand ist die Liste leer.
- `systemctl list-timers 'tim-*'`: `tim-checkup.timer` und `tim-qwen-diagnose.timer` müssen auftauchen, sobald #164 installiert ist.
- `journalctl -u tim-server-health -n 1 -o cat`: `candle_freshness` und `backup` müssen GREEN sein.
- `df -h /var`: deutlich unter 80 % belegt; `ls /var/backups/tim/*.dump | wc -l` ergibt höchstens 3.
- `ollama list`: zeigt das eingesetzte Modell.

## Offen und verschoben

- **Offen, Entscheidung von Uzi:** Cloud-Modell `qwen3-coder:480b-cloud` (schneller, aber Daten gehen an ollama.com) oder lokal bei `qwen3-coder:30b` bleiben.
- **Offen:** Checkup aus #164 auf dem Server installieren. Dafür muss Uzi eine GitHub App anlegen und eine sudo-Zeile eingeben (siehe TIM_CHECKUP.md).
- **Offen:** Datenfluss von `tim-runtime` mit frischer Evidenz prüfen. Ist die Kerzen-Frische GREEN, und sind die Lücken vom 07.10. bis zum Fix nachgebaut?
- **Offen:** Die doppelte `tim-qwen-worker`-Unit bereinigen (System-Unit aus, User-Unit an). Danach wieder `tim-healthcheck` grün.
- **Offen:** Warum ist der Server am 17.10. nicht erreichbar (Strom, Netz, Tailscale)?

## Hier weitermachen

Den Server wieder erreichbar machen und mit den Befehlen aus „Prüfen, ob noch alles steht“ einen frischen Stand erheben. Danach den Checkup nach TIM_CHECKUP.md installieren. Grenzen bleiben: `EXECUTION_MODE=OFF`, keine Secrets ausgeben, Änderungen nur per PR.
