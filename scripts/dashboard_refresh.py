#!/usr/bin/env python3
"""Keep the Control Center (8765) and the worker dashboard (8767) on current platform-main.

Runs from the live checkout (~/TIM-live) as LaunchAgent com.tim.dashboard-refresh every
10 minutes. Rules: ops/dashboard_refresh/policy.json; logic: src/operational/dashboard_refresh.py.
Status for the Control Center: data/operational/dashboard_refresh.json.

    .venv/bin/python scripts/dashboard_refresh.py --dry-run   # decide and probe only, change nothing
    .venv/bin/python scripts/dashboard_refresh.py             # one real run
    .venv/bin/python scripts/dashboard_refresh.py --install   # write and load the LaunchAgent

Pause: touch "~/Library/Application Support/TIM/dashboard-refresh/PAUSE" (delete to resume).
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.operational.dashboard_refresh import DashboardRefresh, iso, load_policy, utc_now  # noqa: E402
from src.v2_completion.mac_live import render_plist  # noqa: E402

LABEL = "com.tim.dashboard-refresh"
DEFAULT_POLICY = ROOT / "ops/dashboard_refresh/policy.json"
# Loaded in this order; a module may import the ones before it.
AGENT_FILES = ("src/operational/dashboard_help.py", "src/operational/dashboard_refresh.py",
               "ops/dashboard_refresh/policy.json")


def newer_agent(agent: DashboardRefresh) -> dict | None:
    """Agent code and rules of the newest CI-green platform-main commit, when they differ from the live ones.

    The old code must not decide whether its own fix may go live (on 25.10. and 26.10. it held because of
    problems the next commit had fixed). The new code is trusted exactly as far as a deploy trusts it:
    a fast-forward of the live checkout on platform-main with a green CI job ``test``.
    """
    if agent.git("fetch", "--quiet", "origin", agent.branch, timeout=180).returncode != 0:
        return None
    head = agent.git("rev-parse", "HEAD").stdout.strip()
    target = agent.git("rev-parse", f"origin/{agent.branch}").stdout.strip()
    if not head or not target or head == target:
        return None
    if agent.git("merge-base", "--is-ancestor", head, target).returncode != 0:
        return None
    if agent.git("diff", "--quiet", head, target, "--", *AGENT_FILES).returncode == 0:
        return None
    ci = agent.ci_result(target)
    if not ci or ci.get("status") != "completed" or ci.get("conclusion") != "success":
        return None
    folder = agent.state_dir / "agent-next"
    shutil.rmtree(folder, ignore_errors=True)
    files = {}
    for relative in AGENT_FILES:
        shown = agent.git("show", f"{target}:{relative}")
        if shown.returncode != 0:
            continue
        path = folder / target[:12] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(shown.stdout, encoding="utf-8")
        files[relative] = path
    if "src/operational/dashboard_refresh.py" not in files or "ops/dashboard_refresh/policy.json" not in files:
        return None
    return {"commit": target, "files": files}


def load_agent(newer: dict, home: Path) -> DashboardRefresh:
    module = None
    for relative, path in newer["files"].items():
        if not relative.endswith(".py"):
            continue
        name = relative[:-3].replace("/", ".")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        parent, _, child = name.rpartition(".")
        setattr(sys.modules[parent], child, module)
    agent = module.DashboardRefresh(ROOT, home, module.load_policy(newer["files"]["ops/dashboard_refresh/policy.json"]))
    agent.agent_source = {"commit": newer["commit"], "files": sorted(newer["files"])}
    return agent


def install(home: Path) -> int:
    if sys.platform != "darwin":
        raise SystemExit("--install runs on macOS only")
    target = home / "Library/LaunchAgents" / f"{LABEL}.plist"
    rendered = render_plist((ROOT / f"ops/launchd/{LABEL}.plist").read_bytes(), ROOT, home)
    (ROOT / "data/operational").mkdir(parents=True, exist_ok=True)
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
    parser.add_argument("--dry-run", action="store_true", help="decide and probe, change nothing")
    parser.add_argument("--install", action="store_true", help="write and load the LaunchAgent (macOS)")
    parser.add_argument("--policy", type=Path, default=ROOT / "ops/dashboard_refresh/policy.json")
    args = parser.parse_args(argv)
    home = Path.home()
    if args.install:
        return install(home)
    agent = DashboardRefresh(ROOT, home, load_policy(args.policy))
    agent.state_dir.mkdir(parents=True, exist_ok=True)
    with open(agent.state_dir / "run.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"result": "ALREADY_RUNNING"}))
            return 0
        if args.policy == DEFAULT_POLICY:
            try:
                newer = newer_agent(agent)
                if newer:
                    agent = load_agent(newer, home)
            except Exception as exc:  # a broken new version must not stop the working one
                agent.agent_source = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        try:
            status = agent.run_once(dry_run=args.dry_run)
        except Exception as exc:  # the Control Center must see a crash, not an old green status
            failure = {"schema_version": "1.0.0", "checked_at_utc": iso(utc_now()), "health_ok": False,
                       "decision": {"action": "HOLD", "reason": "agent_error", "text": f"Agent-Fehler: {type(exc).__name__}: {exc}"[:500]}}
            if not args.dry_run:
                agent.write_json(agent.status_path, failure)
            raise
    if args.dry_run:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:  # one line per run keeps the launchd log small; details are in the status file
        print(json.dumps({"checked_at_utc": status["checked_at_utc"], "action": status["decision"]["action"],
                          "reason": status["decision"]["reason"], "deployed": status["deployed_commit"][:7],
                          "health_ok": status["health_ok"], "worker": status["worker_dashboard"].get("result")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
