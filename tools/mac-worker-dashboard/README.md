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

## Installieren

```sh
tools/mac-worker-dashboard/install.sh        # baut mit cargo, installiert LaunchAgent com.tim.mac-worker-dashboard
```

Ohne LaunchAgent: `cargo run --release --manifest-path tools/mac-worker-dashboard/Cargo.toml`.
Einmalige Ausgabe als JSON: `MWD_PRINT_STATUS=1 target/release/mac-worker-dashboard`. Tests: `cargo test`.
