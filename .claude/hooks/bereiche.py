"""UserPromptSubmit hook: load only the memory areas a message is about (Uzi 04.11.2026).

The shared project memory keeps a short core in MEMORY.md (always loaded by the
memory service) and one file per area (bereich-*.md). This hook reads the user's
message, matches keywords per area and adds the matching area files as context.
Safety rules never depend on it: they live in the core.

- Memory folder: $TIM_MEMORY_DIR when set (only that), else the cloud path below. No folder: no output.
- Never blocks a prompt: every error ends with exit 0 and no output.
- Reads only; writes nothing; no network. At most MAX_CHARS of context.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

CANDIDATES = ("/tmp/claude/memory/team/silo",)
MAX_CHARS = 9000
# Area file -> keywords (lower case, matched as word starts; words up to 3 letters as whole words).
# Public file: keywords only, never facts from the memory.
AREAS = {
    "bereich-mac-server": ("mac", "server", "runner", "warpgate", "ssh", "desktop commander", "control center", "launchagent",
                           "tim-live", "tim-core", "issue-worker", "worker", "qwen", "ollama", "neustart", "backup", "remote"),
    "bereich-git-pr": ("pr", "pull request", "merge", "branch", "commit", "ci", "cl", "suite", "pytest", "dco", "gate",
                       "ruleset", "github", "repo", "dependabot"),
    "bereich-research": ("studie", "research", "holdout", "register", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s12", "s13",
                         "s14", "s15", "s16", "s17", "backtest", "edge", "glückstest", "journal", "lernschleife", "filter",
                         "engine", "reel", "hypothese"),
    "bereich-chart-link": ("chart", "link", "tim-online", "volume profile", "vp", "footprint", "gamma", "gex", "wall",
                           "poc", "vah", "val", "heatmap", "tpo", "dashboard", "journal"),
    "bereich-echtgeld": ("echtgeld", "kraken", "live-trader", "echt traden", "position", "order", "trade", "$", "dollar"),
    "bereich-allgemein": ("plan", "gesamtplan", "broncx", "goathub", "discord", "telegram", "gutachten", "obsidian"),
}


def memory_dir() -> Path | None:
    chosen = os.environ.get("TIM_MEMORY_DIR")
    for path in ((chosen,) if chosen else CANDIDATES):
        if path and Path(path).is_dir():
            return Path(path)
    return None


def areas_for(prompt: str) -> list[str]:
    text = prompt.lower()
    hits = []
    for area, words in AREAS.items():
        for word in words:
            pattern = re.escape(word) if not word[0].isalnum() else r"(?<![\w-])" + re.escape(word)
            if word[0].isalnum() and len(word) <= 3:
                pattern += r"(?![^\W\d_])"  # short words whole ("pr" not in "prüfen"; "s7" also in "s7b")
            if re.search(pattern, text):
                hits.append(area)
                break
    return hits


def body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    return text.strip()


def context(prompt: str, folder: Path) -> str:
    parts, used = [], 0
    for area in areas_for(prompt):
        path = folder / f"{area}.md"
        if not path.is_file():
            continue
        block = f"## {area}\n{body(path)}"
        if used + len(block) > MAX_CHARS:
            continue  # too long for what is left: skip this area, smaller ones may still fit
        parts.append(block)
        used += len(block)
    if not parts:
        return ""
    return "Bereichsregeln aus dem Projekt-Gedächtnis (passend zur Nachricht geladen):\n\n" + "\n\n".join(parts)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        folder = memory_dir()
        prompt = str(payload.get("prompt") or "")
        text = context(prompt, folder) if folder and prompt else ""
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    except Exception:  # noqa: BLE001 - a hook must never block a prompt
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
