#!/usr/bin/env python3
"""Timetable of the research workshop (F6), LaunchAgent com.tim.research-workshop every 15 minutes.

Logic and rules: src/research_lab/workshop/schedule.py. Status: data/research/schedule/state.json,
history: data/research/schedule/history.jsonl. Writes only under data/research/.

    .venv/bin/python scripts/research_workshop_schedule.py --dry-run          # show what is due, change nothing
    .venv/bin/python scripts/research_workshop_schedule.py                    # one real wake-up
    .venv/bin/python scripts/research_workshop_schedule.py --task weekly      # run one task now (ignores PAUSE/CI)
    .venv/bin/python scripts/research_workshop_schedule.py --install          # write and load the LaunchAgent

Pause: touch data/research/schedule/PAUSE (delete to resume). Without AI round: --no-ki.
Every real wake-up also steps the S7b forward journal (paper only, data/research/forward/S7b/); --no-forward skips it.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research_lab.workshop.schedule import TASKS, Workshop  # noqa: E402

LABEL = "com.tim.research-workshop"
KI_TIMEOUT = 300


def ask_claude(prompt: str) -> str:
    from src.local_first.claude_cli_fallback import advise_text
    return advise_text(prompt, timeout=KI_TIMEOUT)


def forward_step(root: Path) -> dict:
    """One step of the S7b forward journal (paper only), data under data/research/forward/S7b/."""
    from src.research_lab.forward.s7b import FOLDER, ForwardJournal
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            check=False).stdout.strip()
    return ForwardJournal(root / FOLDER).step(code_commit=commit)


def install(home: Path) -> int:
    from src.v2_completion.mac_live import render_plist
    if sys.platform != "darwin":
        raise SystemExit("--install runs on macOS only")
    target = home / "Library/LaunchAgents" / f"{LABEL}.plist"
    rendered = render_plist((ROOT / f"ops/launchd/{LABEL}.plist").read_bytes(), ROOT, home)
    (ROOT / "data/research/schedule").mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".plist.tmp")
    temporary.write_bytes(rendered)
    os.chmod(temporary, 0o644)
    temporary.replace(target)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target)], check=False, capture_output=True)
    loaded = subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=False, capture_output=True, text=True)
    print(json.dumps({"written": str(target), "bootstrap_returncode": loaded.returncode, "stderr": loaded.stderr.strip()}))
    return loaded.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--task", choices=TASKS)
    parser.add_argument("--no-ki", action="store_true", help="weekly round without the AI ideas")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--no-forward", action="store_true", help="skip the S7b forward journal step")
    args = parser.parse_args(argv)
    if args.install:
        return install(Path.home())
    workshop = Workshop(ROOT, ask=None if args.no_ki else ask_claude, forward=None if args.no_forward else forward_step)
    workshop.state_dir.mkdir(parents=True, exist_ok=True)
    with open(workshop.state_dir / "run.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"result": "ALREADY_RUNNING"}))
            return 0
        summary = workshop.run_once(dry_run=args.dry_run, only=args.task)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(r.get("ok", True) for r in summary["ran"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
