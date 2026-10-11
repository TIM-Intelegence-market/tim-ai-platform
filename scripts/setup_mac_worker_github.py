#!/usr/bin/env python3
"""Set up an isolated GitHub CLI login for the Mac Qwen worker.

The token is read from the terminal without echo and is never passed as an
argument or written by this script. GitHub CLI manages its own credential store.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

EXPECTED_LOGIN = "apoman74-art"
REPO = "TIM-Intelegence-market/tim-ai-platform"
CONFIG_DIR = Path.home() / ".config/gh-tim-mac-worker"


def gh(*args: str, input_text: str | None = None) -> str:
    env = {**os.environ, "GH_CONFIG_DIR": str(CONFIG_DIR)}
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    result = subprocess.run(
        ["gh", *args], input=input_text, capture_output=True, text=True,
        check=False, env=env, timeout=45,
    )
    if result.returncode:
        raise RuntimeError(f"GitHub check failed ({result.returncode}); no token details displayed")
    return result.stdout


def main() -> int:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    token = getpass.getpass("Token des Kontos apoman74-art eingeben (Eingabe unsichtbar): ")
    if not token:
        print("Kein Token eingegeben.", file=sys.stderr)
        return 1
    try:
        gh("auth", "login", "--hostname", "github.com", "--with-token", input_text=token + "\n")
    finally:
        token = ""

    login = gh("api", "user", "--jq", ".login").strip()
    if login.casefold() != EXPECTED_LOGIN.casefold():
        print(f"Falscher GitHub-Login: {login}. Erwartet: {EXPECTED_LOGIN}.", file=sys.stderr)
        return 2
    permissions = json.loads(gh("api", f"repos/{REPO}", "--jq", ".permissions"))
    if permissions.get("push") is not True or permissions.get("admin") is not False or permissions.get("maintain") is not False:
        print("Worker-Rechte sind nicht genau wie erwartet; Pilot bleibt gesperrt.", file=sys.stderr)
        return 3
    print(f"Worker-Anmeldung geprüft: {login}; Konfiguration: {CONFIG_DIR}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Einrichtung fehlgeschlagen: {exc}", file=sys.stderr)
        raise SystemExit(4) from None
