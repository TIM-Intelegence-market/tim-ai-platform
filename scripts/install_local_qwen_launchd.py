#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

LABEL = "com.tim.local-qwen-worker"
DEFAULT_FALLBACK_MODELS = "qwen2.5:7b"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Install TIM unified Qwen supervisor as a macOS user LaunchAgent.")
    value.add_argument("--repo-root", type=Path, default=Path.cwd())
    value.add_argument("--python", default=sys.executable)
    value.add_argument("--model", default="qwen3.5:9b")
    value.add_argument("--fallback-models", default=DEFAULT_FALLBACK_MODELS)
    value.add_argument("--interval", type=float, default=5.0)
    value.add_argument("--pilot-task-id", default=None,
                       help="Keep the service limited to one named task while validating the worker.")
    value.add_argument("--github-worker-login", default=None)
    value.add_argument("--github-config-dir", type=Path, default=None)
    value.add_argument("--enable-github-escalation", action="store_true")
    value.add_argument("--enable-github-intake", action="store_true")
    value.add_argument("--github-pilot-issue", type=int, default=None)
    value.add_argument("--github-merge", action="store_true")
    value.add_argument("--enable-codex-advisor", action="store_true")
    value.add_argument("--enable-codex-patch-fallback", action="store_true")
    value.add_argument("--codex-model", default="gpt-5.6-luna")
    value.add_argument("--enable-claude-advisor", action="store_true")
    value.add_argument("--enable-claude-patch-fallback", action="store_true")
    value.add_argument("--claude-model", default="sonnet")
    value.add_argument("--claude-bin", type=Path, default=None,
                       help="Claude Code CLI path; defaults to ~/.local/bin, then Homebrew.")
    value.add_argument("--disable-qwen-tool-loop", action="store_true",
                       help="Let Qwen answer in one shot instead of using the read-only tool loop.")
    value.add_argument("--load", action="store_true", help="Bootstrap the LaunchAgent after writing the plist.")
    return value


def _default_claude_bin() -> Path:
    candidates = [Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude"),
                  Path("/usr/local/bin/claude")]
    return next((path for path in candidates if path.is_file()), candidates[0])


def _plist_payload(
    *,
    repo: Path,
    python: Path,
    worker: Path,
    state: Path,
    logs: Path,
    model: str,
    fallback_models: str,
    interval: float,
    pilot_task_id: str | None = None,
    github_worker_login: str | None = None,
    github_config_dir: Path | None = None,
    enable_github_escalation: bool = False,
    enable_github_intake: bool = False,
    github_pilot_issue: int | None = None,
    github_merge: bool = False,
    enable_codex_advisor: bool = False,
    enable_codex_patch_fallback: bool = False,
    codex_model: str = "gpt-5.6-luna",
    enable_claude_advisor: bool = False,
    enable_claude_patch_fallback: bool = False,
    claude_model: str = "sonnet",
    claude_bin: Path | None = None,
    disable_qwen_tool_loop: bool = False,
) -> dict[str, Any]:
    python_executable = python.absolute()
    program_arguments = [
        str(python_executable), str(worker),
        "--repo-root", str(repo), "--state-root", str(state),
        "--model", model, "--fallback-models", fallback_models,
        "--interval", str(interval),
    ]
    if pilot_task_id is not None:
        program_arguments.extend(["--pilot-task-id", pilot_task_id])
    if enable_github_intake:
        if not github_worker_login or github_config_dir is None:
            raise ValueError("GitHub intake requires a dedicated worker login and config directory")
        program_arguments.append("--github-intake")
        if github_pilot_issue is not None:
            if github_pilot_issue <= 0:
                raise ValueError("invalid GitHub pilot issue number")
            program_arguments.extend(["--github-pilot-issue", str(github_pilot_issue)])
        if github_merge:
            program_arguments.append("--github-merge")
    environment = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": str(repo),
        "TIM_LOCAL_PATCH_SANDBOX": "1",
        "TIM_BLOCKER_AUTO_WAIT": "0",
        "TIM_LIVE_TRADING": "0",
        "TIM_EXECUTION_ENABLED": "0",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": model,
        "TIM_QWEN_FALLBACK_MODELS": fallback_models,
        "TIM_TEST_SANDBOX": "required",
        "TIM_QWEN_TOOL_LOOP": "0" if disable_qwen_tool_loop else "1",
    }
    # Server model through the local SSH tunnel (docs/mac-qwen-issue-worker.md, "Hard issues"), and the
    # worker lane beside tim-core-01 ("Two workers"); without it a rerun would reset the Mac to lane "all".
    for key in ("TIM_QWEN_HARD_URL", "TIM_QWEN_HARD_MODEL",
                "TIM_QWEN_SERVER_PREFERRED", "TIM_QWEN_SERVER_KEEP_WARM", "TIM_WORKER_LANE"):
        if os.environ.get(key, "").strip():
            environment[key] = os.environ[key].strip()
    if enable_github_escalation or enable_github_intake:
        if not github_worker_login or github_config_dir is None:
            raise ValueError("GitHub escalation requires a dedicated worker login and config directory")
        environment.update({
            "TIM_QWEN_WORKER_LOGIN": github_worker_login,
            "GH_CONFIG_DIR": str(github_config_dir),
        })
        if enable_github_escalation:
            environment["TIM_QWEN_GITHUB_ESCALATION"] = "1"
    if enable_codex_advisor:
        environment.update({
            "TIM_CODEX_BLOCKER_ADVISOR": "1",
            "TIM_CODEX_MODEL": codex_model,
            "TIM_CODEX_BIN": str(Path.home() / ".local/bin/codex"),
        })
    if enable_codex_patch_fallback:
        environment.update({
            "TIM_CODEX_PATCH_FALLBACK": "1",
            "TIM_CODEX_MODEL": codex_model,
            "TIM_CODEX_BIN": str(Path.home() / ".local/bin/codex"),
        })
    if enable_claude_advisor or enable_claude_patch_fallback:
        environment.update({
            "TIM_CLAUDE_MODEL": claude_model,
            "TIM_CLAUDE_BIN": str(claude_bin or _default_claude_bin()),
        })
        if enable_claude_advisor:
            environment["TIM_CLAUDE_BLOCKER_ADVISOR"] = "1"
        if enable_claude_patch_fallback:
            environment["TIM_CLAUDE_PATCH_FALLBACK"] = "1"
    return {
        "Label": LABEL,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "local-first.out.log"),
        "StandardErrorPath": str(logs / "local-first.err.log"),
        "EnvironmentVariables": environment,
    }


def main() -> int:
    args = parser().parse_args()
    repo = args.repo_root.resolve()
    worker = repo / "scripts/run_local_qwen_daemon.py"
    if not worker.exists():
        raise SystemExit(f"worker script not found: {worker}")

    # This marker is created only by the explicit installer invocation. The supervisor cannot
    # self-authorize patching merely because Ollama is running.
    sandbox_marker = repo / ".tim/local-first/PATCH_SANDBOX_ALLOWED"
    sandbox_marker.parent.mkdir(parents=True, exist_ok=True)
    sandbox_marker.write_text("launchd-local-sandbox-only\n", encoding="utf-8")
    os.chmod(sandbox_marker, 0o600)

    home = Path.home()
    state = home / "Library/Application Support/TIM/local-first"
    logs = home / "Library/Logs/TIM"
    agents = home / "Library/LaunchAgents"
    for directory in (state, logs, agents):
        directory.mkdir(parents=True, exist_ok=True)

    plist_path = agents / f"{LABEL}.plist"
    payload = _plist_payload(
        repo=repo,
        python=Path(args.python),
        worker=worker,
        state=state,
        logs=logs,
        model=args.model,
        fallback_models=args.fallback_models,
        interval=args.interval,
        pilot_task_id=args.pilot_task_id,
        github_worker_login=args.github_worker_login,
        github_config_dir=args.github_config_dir,
        enable_github_escalation=args.enable_github_escalation,
        enable_github_intake=args.enable_github_intake,
        github_pilot_issue=args.github_pilot_issue,
        github_merge=args.github_merge,
        enable_codex_advisor=args.enable_codex_advisor,
        enable_codex_patch_fallback=args.enable_codex_patch_fallback,
        codex_model=args.codex_model,
        enable_claude_advisor=args.enable_claude_advisor,
        enable_claude_patch_fallback=args.enable_claude_patch_fallback,
        claude_model=args.claude_model,
        claude_bin=args.claude_bin,
        disable_qwen_tool_loop=args.disable_qwen_tool_loop,
    )
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    os.chmod(plist_path, 0o600)
    print(f"WROTE {plist_path}")
    print(f"SANDBOX_MARKER {sandbox_marker}")

    if not args.load:
        print("NOT_LOADED; rerun with --load after reviewing the plist")
        return 0

    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], capture_output=True, check=False)
    completed = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        print(f"BOOTSTRAP_FAILED exit={completed.returncode}")
        if completed.stderr:
            print(completed.stderr.strip())
        return completed.returncode
    print(f"LOADED {LABEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
