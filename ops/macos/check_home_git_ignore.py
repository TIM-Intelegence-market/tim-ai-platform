#!/usr/bin/env python3
"""Prüft, ob das Git-Repo im Home-Ordner (~/.git) TIM-Datenpfade und Schlüsseldateien ignoriert.

Nur lesend. Läuft auf dem Mac mini:

    python3 ops/macos/check_home_git_ignore.py            # Bericht, Exit 0 = alles ignoriert
    python3 ops/macos/check_home_git_ignore.py --json     # maschinenlesbar

Grundlage: docs/governance/runner_vertrauensgrenzen_t11.md Abschnitt 7 (Home-Git) und die Regel,
dass Geheimnisse nur im Schlüsselbund liegen. Das Skript ändert nichts, es fragt `git check-ignore`
und `git ls-files` und meldet, was ein `git add .` im Home erfassen würde.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Pfade relativ zum Home, die nie ins Home-Git gehören (Daten, Laufzeit, Klone, Schlüssel).
TIM_PATHS = [
    "Library/Application Support/TIM",
    "TIM-live", "TIM-worker", "TIM-trading-team", "TIM-bili-test",
    "Documents/TIM", "Downloads/broncx-library",
    "tim-ci-runner", "actions-runner",
    ".ssh", ".gnupg", ".aws", ".config/gh", ".docker/config.json",
    ".ollama", ".cache", ".venv", "Library/Caches", "Library/Logs",
]
# Dateimuster, die als Geheimnis gelten; wird gegen die bereits erfassten Dateien geprüft.
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx", ".netrc", ".npmrc", ".pypirc")
SECRET_NAMES = {".env", "database-password", "credentials", "credentials.json", "token", "token.txt", "id_rsa", "id_ed25519", "id_ecdsa"}


def git(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(home), *args], capture_output=True, text=True)


def check(home: Path) -> dict:
    result: dict = {"home": str(home), "git_repo": (home / ".git").exists(), "remote": None, "head": None,
                    "not_ignored": [], "missing": [], "tracked_total": 0, "tracked_suspicious": [], "ok": False}
    if not result["git_repo"]:
        result["note"] = "kein ~/.git: nichts zu prüfen"
        result["ok"] = True
        return result
    remote = git(home, "remote", "-v")
    result["remote"] = remote.stdout.strip() or "(kein Remote)"
    head = git(home, "log", "-1", "--format=%h %cI %s")
    result["head"] = head.stdout.strip() or "(keine Commits)"
    for rel in TIM_PATHS:
        path = home / rel
        if not path.exists():
            result["missing"].append(rel)
            continue
        probe = git(home, "check-ignore", "-q", "--", rel)
        if probe.returncode != 0:
            result["not_ignored"].append(rel)
    tracked = git(home, "ls-files", "-z")
    files = [f for f in tracked.stdout.split("\0") if f]
    result["tracked_total"] = len(files)
    for name in files:
        base = os.path.basename(name)
        if base in SECRET_NAMES or base.endswith(SECRET_SUFFIXES) or name.startswith(("Library/Application Support/TIM/", "TIM-live/", "TIM-worker/", "Documents/TIM/")):
            result["tracked_suspicious"].append(name)
    result["ok"] = not result["not_ignored"] and not result["tracked_suspicious"]
    return result


def render(result: dict) -> str:
    lines = [f"Home-Git-Prüfung für {result['home']}"]
    if not result["git_repo"]:
        return "\n".join(lines + ["kein ~/.git vorhanden: PASS"])
    lines += [f"Remote: {result['remote']}", f"HEAD: {result['head']}", f"Erfasste Dateien: {result['tracked_total']}", ""]
    if result["not_ignored"]:
        lines += ["NICHT ignoriert (ein `git add .` würde sie erfassen):"] + [f"  - {p}" for p in result["not_ignored"]]
    else:
        lines.append("Alle vorhandenen TIM-/Schlüsselpfade werden ignoriert.")
    if result["tracked_suspicious"]:
        lines += ["", "Bereits erfasste verdächtige Dateien (prüfen, ggf. `git rm --cached`):"] + [f"  - {p}" for p in result["tracked_suspicious"]]
    if result["missing"]:
        lines += ["", "Nicht vorhanden (übersprungen): " + ", ".join(result["missing"])]
    lines += ["", "Ergebnis: " + ("PASS" if result["ok"] else "FAIL")]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = check(args.home)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
