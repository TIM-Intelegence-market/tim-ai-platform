#!/usr/bin/env python3
"""Write the launchd agents for a live TIM checkout on the Mac mini (macOS only).

Renders ops/launchd/<label>.plist for THIS checkout and the current home directory and
writes it to ~/Library/LaunchAgents/<label>.plist (mode 0644). It never calls launchctl:
loading, the runtime switch and the safe stop/start are separate, explicit steps (see
ops/macos/LIVE_MAC.md). With --check it only reports which agents differ.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.mac_live import LIVE_AGENTS, launchd_drift, render_plist


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only report drift, write nothing")
    parser.add_argument("--labels", nargs="+", default=list(LIVE_AGENTS), choices=LIVE_AGENTS)
    args = parser.parse_args(argv)
    home = Path.home()
    agents = home / "Library/LaunchAgents"
    if args.check:
        drift = launchd_drift(ROOT, agents, home, tuple(args.labels))
        print(json.dumps({"root": str(ROOT), "drift": drift}))
        return 0 if drift == [] else 2
    if sys.platform != "darwin":
        raise SystemExit("mac_live_install.py writes launchd agents and runs on macOS only")
    agents.mkdir(parents=True, exist_ok=True)
    (ROOT / "data/operational").mkdir(parents=True, exist_ok=True)
    written = []
    for label in args.labels:
        target = agents / f"{label}.plist"
        temporary = target.with_suffix(".plist.tmp")
        temporary.write_bytes(render_plist((ROOT / f"ops/launchd/{label}.plist").read_bytes(), ROOT, home))
        os.chmod(temporary, 0o644)
        temporary.replace(target)
        written.append(str(target))
    print(json.dumps({"root": str(ROOT), "written": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
