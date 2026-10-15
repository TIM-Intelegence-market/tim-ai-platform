# Mac-Worker-Dashboard

Kleine, nur lesende Web-App für den Mac-Qwen-Issue-Worker (`com.tim.local-qwen-worker`).
Läuft nur auf `http://127.0.0.1:8767` und zeigt vier Bereiche:

- **Aktuell**: ob der Worker und Ollama laufen, an welchem Issue er arbeitet, in welcher Phase
  (Auftrag, Blocker, Rat von Codex/Claude, Patch, Abnahme, PR), der letzte Fehler aus dem Log
  und liegen gebliebene Läufe (Worktree ohne PR, nur solange das Issue noch offen ist).
- **Server-Modell**: ob der SSH-Tunnel zum Server (`com.tim.server-ollama-tunnel`, 127.0.0.1:11435)
  antwortet, ob `qwen3-coder:30b` gerade geladen ist (warm, mit Ablaufzeit) oder kalt, und wie viele
  große Issues (`agent:qwen-hard`) auf das Server-Modell warten. Hard-Issues und PRs, an denen das
  Server-Modell gearbeitet hat, tragen den Chip „Server-Modell“ bzw. „Server-Qwen“.
- **Offen**: alle offenen Issues, eingeteilt nach den Regeln aus
  `src/local_first/github_issue_queue.py` und `src/local_first/issue_triage.py`: bereit für den
  Worker, wartet auf Triage durch Claude, blockiert (`agent:blocked`) oder nicht für den Worker
  (mit Grund, z. B. `agent:not-suitable`, Epic, Server-Arbeit).
- **Erledigt**: PRs des Worker-Kontos auf Branches `codex/issue-N-qwen`, mit Link, Laufdauer bis
  zum PR, Dauer bis zum Merge, Zahl der Versuche und welcher Helfer eingesprungen ist.

## Datenquellen (nur gelesen)

- `launchctl list com.tim.local-qwen-worker`, `~/Library/Application Support/TIM Mac Issue Worker/`
  (`run.lock`, `worktrees/`, `archive/`, `runs/`) und die `.tim/local-first/`-Dateien darin
- `~/Library/Logs/TIM/local-first.{out,err}.log` (nur die letzten 2 MB, Zugangsdaten werden geschwärzt)
- `gh issue list` und `gh pr list` (Ergebnis 60 s zwischengespeichert), Ollama `/api/tags`, Server-Ollama über den Tunnel `/api/tags` und `/api/ps`,
  `launchctl list com.tim.server-ollama-tunnel`

Die App schreibt nichts, nimmt nur `GET` an und beantwortet nur Anfragen mit Host `127.0.0.1` oder
`localhost`. Sie zeigt keine Tokens; `gh` läuft mit dem normalen Login des Mac-Benutzers.

## Warteschlange

Die offene Warteschlange unterscheidet sofort startbare Aufgaben, Aufgaben mit
offenen Abhängigkeiten, über Worker-Teilaufgaben eingeplante Sammel-Issues
(`agent:split`) und automatisch gepflegte Übersichten (`agent:coordination`).
Sammel-Issues sind selbst nicht ausführbar; ihre verlinkten Codeaufgaben tragen
die validierten Verträge. Eine blockierte Gesamtabnahme bleibt auf der Karte
sichtbar. Issue-Bodies werden nur zur Abhängigkeitsprüfung gelesen und nicht an
den Browser ausgegeben.

## Für Mitentwickler im Tailnet freigeben

Der Mac mini hängt im Tailnet `tailnet.example.ts.net`. `tailscale serve` reicht das Dashboard nur
innerhalb des Tailnets weiter (kein Funnel, nicht öffentlich); die App selbst bleibt auf 127.0.0.1:

```sh
MWD_ALLOW_HOSTS="tim-mac-mini.tailnet.example.ts.net tim-mac-mini" tools/mac-worker-dashboard/install.sh
tailscale serve --bg --http=80 http://127.0.0.1:8767
```

Link: `http://tim-mac-mini.tailnet.example.ts.net/`. Abschalten: `tailscale serve --http=80 off`.
Wer im Tailnet den Mac erreichen darf, regeln die ACLs des Tailnets.

## Installieren

```sh
tools/mac-worker-dashboard/install.sh        # baut mit cargo, installiert LaunchAgent com.tim.mac-worker-dashboard
```

Ohne LaunchAgent: `cargo run --release --manifest-path tools/mac-worker-dashboard/Cargo.toml`.
Einmalige Ausgabe als JSON: `MWD_PRINT_STATUS=1 target/release/mac-worker-dashboard`. Tests: `cargo test`.

## Ausführungsort und Auslastung

Das Dashboard liest die Routing-Einstellungen des laufenden Workers und das Qwen-Ziel
des Entwicklerprozesses über `ps`. Es gibt ausschließlich freigegebene Routing-Felder
weiter, keine vollständigen Prozessumgebungen. Der Prozess muss zum aktuellen Issue-Worktree
gehören; ohne Prozessbeleg wird kein Ausführungsort aus Issue-Labels geraten.
Ein laufender Entwicklerprozess kann auf Modellantworten, Tests oder Helfer warten.
Die Ereignisliste ist eine Historie abgeschlossener Schritte. „Warm“ bedeutet nur,
dass Ollama das Modell im Speicher hält. CPU-Auslastung wird nicht erhoben.

Der aktuelle Auftrag wird ausschließlich aus laufenden Nachfahren des Worker-Prozesses
ermittelt. Eine vorhandene Lock-Datei oder ein alter Worktree belegt keinen aktiven Auftrag.
Während einer CI-Pause erscheint diese als aktueller Zustand. Frühere Triage-Meldungen,
Fehler und beendete Läufe ohne PR stehen in einer getrennten, standardmäßig eingeklappten
Historie. Zeitangaben werden nicht aus der Anzahl von Log-Zeilen geschätzt.

Issue-Nachweise werden ausschließlich aus `Application Support/TIM Mac Issue Worker`
gelesen (Worktrees und Archiv). Der Quellcode-Checkout im geschützten Dokumente-Ordner
wird dafür nicht geöffnet; eine macOS-Datenschutzabfrage soll die Live-Anzeige nicht
blockieren.
