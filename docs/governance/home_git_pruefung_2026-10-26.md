# Home-Git-Prüfung auf dem Mac mini (Grün-Plan S1)

Stand 26.10.2026, 10:10 Ortszeit. Werkzeug: `ops/macos/check_home_git_ignore.py` (PR #425), ausgeführt aus dem
Worktree `~/Documents/TIM/worktrees/s2-zaehllauf` auf `06c8bc2`. Hintergrund: Der ganze Home-Ordner des Mac mini ist
ein Git-Repo (`~/.git`, kein Remote, 25 erfasste Dateien); ein unbedachtes `git add .` würde TIM-Daten und
Schlüsseldateien erfassen.

## Erster Lauf: FAIL (Exit 1)

Nicht ignoriert waren: `Library/Application Support/TIM`, `TIM-live`, `TIM-worker`, `TIM-trading-team`, `TIM-bili-test`,
`Documents/TIM`, `Downloads/broncx-library`, `tim-ci-runner`, `.ssh`, `.config/gh`, `.ollama`, `.cache`, `.venv`,
`Library/Caches`, `Library/Logs`. Nicht vorhanden und übersprungen: `actions-runner`, `.gnupg`, `.aws`,
`.docker/config.json`. Bereits erfasste verdächtige Dateien: keine.

## Behebung

Die Muster stehen jetzt in `~/.git/info/exclude` (nicht in einer `~/.gitignore`, die selbst erfasst würde). Vorher
Sicherung nach `~/.git/info/exclude.bak-20261026` (6 Zeilen); angehängt wurden ein Kommentarblock und 27 Muster
(Datenpfade oben plus `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.kdbx`, `.netrc`, `.npmrc`, `.pypirc`). Nichts gelöscht.
Rückgängig: `cp -p ~/.git/info/exclude.bak-20261026 ~/.git/info/exclude`.

Gegenprobe im Home-Git: `git ls-files` enthält 0 Pfade unter den TIM-, SSH-, gh- oder Ollama-Verzeichnissen und
0 Dateien mit Schlüsselmustern.

## Zweiter Lauf: PASS (Exit 0)

```json
{"home": "/Users/tim", "git_repo": true, "remote": "(kein Remote)", "head": "a418894 2026-07-06T21:06:36+02:00 Add Codex usage fallback protocol", "not_ignored": [], "missing": ["actions-runner", ".gnupg", ".aws", ".docker/config.json"], "tracked_total": 25, "tracked_suspicious": [], "ok": true}
```

## Offen

- `~/.git/info/exclude` ist lokal und ohne Remote; bei einer Neuinstallation des Mac muss der Block neu gesetzt
  werden. Vorschlag: Prüfung in die Wochen-Checkliste von `ops/macos/LIVE_MAC.md` aufnehmen.
- Ob das Home-Git überhaupt gebraucht wird, entscheidet Uzi; eine Löschung von `~/.git` ist kein Teil dieses Pakets.
