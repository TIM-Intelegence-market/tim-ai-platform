#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

from src.llm.ollama_client import OllamaClient
from src.local_first.graphify_context import LocalGraphifyContextAdapter
from src.local_first.provider_broker import ProviderBroker
from src.local_first.runtime import BlockerMailbox, LocalPrimaryWorker, RepairRecipeStore


DEFAULT_FALLBACK_MODELS = "qwen2.5:7b"
DEFAULT_BLOCKED_RETRY_SECONDS = 30.0


class SingleInstance:
    """Crash-safe single-daemon lock.

    ``flock`` is released by the kernel when the process exits, so a crash cannot leave a stale
    lock file that permanently prevents the local supervisor from restarting.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: TextIO | None = None

    def __enter__(self) -> "SingleInstance":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
            )
        except OSError as exc:
            raise SystemExit(f"local-first supervisor lock is unsafe: {self.path}") from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise SystemExit(f"local-first supervisor lock is unsafe: {self.path}")
        try:
            handle = os.fdopen(descriptor, "r+", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SystemExit(f"local-first supervisor already running: {self.path}") from exc
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()}\n")
            handle.flush()
        except BaseException:
            handle.close()
            raise
        self.handle = handle
        return self

    def __exit__(self, *_: object) -> None:
        if self.handle is None:
            return
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="TIM unified local-first Qwen supervisor daemon")
    value.add_argument("--repo-root", type=Path, default=Path.cwd())
    value.add_argument("--state-root", type=Path, default=Path(".tim/local-first-runtime"))
    value.add_argument("--recipes", type=Path, default=Path("config/repair-recipes"))
    value.add_argument("--interval", type=float, default=5.0)
    value.add_argument("--pilot-task-id", default=None,
                       help="Process only this task ID; leave every other queued task untouched.")
    value.add_argument("--github-intake", action="store_true",
                       help="Poll explicitly ready GitHub issues through the isolated Mac issue runner.")
    value.add_argument("--github-pilot-issue", type=int, default=None)
    value.add_argument("--github-merge", action="store_true",
                       help="Let GitHub's required gates authorize a squash merge for a worker PR.")
    value.add_argument("--ollama-url", default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    value.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen3.5:9b"))
    value.add_argument(
        "--fallback-models",
        default=os.getenv("TIM_QWEN_FALLBACK_MODELS", DEFAULT_FALLBACK_MODELS),
        help="Comma-separated already-installed local fallback models; never pulled automatically.",
    )
    return value


def _resolve(base: Path, value: Path) -> Path:
    return value if value.is_absolute() else base / value


def _next_task(inbox: Path, pilot_task_id: str | None = None) -> Path | None:
    if pilot_task_id is not None:
        if not pilot_task_id or not all(char.isalnum() or char in "_-" for char in pilot_task_id):
            raise ValueError("invalid pilot task ID")
        candidate = inbox / f"{pilot_task_id}.json"
        return candidate if candidate.is_file() else None
    tasks = sorted(path for path in inbox.glob("*.json") if path.is_file())
    return tasks[0] if tasks else None


def _developer_state(repo_root: Path) -> Path:
    return repo_root / ".tim/local-first"


def _developer_task_pending(repo_root: Path, pilot_task_id: str | None = None) -> bool:
    return _next_task(_developer_state(repo_root) / "developer-inbox", pilot_task_id) is not None


def _model_candidates(preferred: str, fallbacks: str) -> tuple[str, ...]:
    values = [preferred, *(part.strip() for part in fallbacks.split(","))]
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return tuple(unique)


def _choose_local_model(installed: tuple[str, ...], candidates: tuple[str, ...]) -> str | None:
    installed_set = set(installed)
    return next((candidate for candidate in candidates if candidate in installed_set), None)


def _ollama_binary() -> str | None:
    candidates = [
        os.getenv("OLLAMA_BIN"),
        shutil.which("ollama"),
        "/opt/homebrew/bin/ollama",
        "/usr/local/bin/ollama",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _start_local_ollama(state_root: Path) -> bool:
    """Attempt one bounded local Ollama service start. Never downloads a model."""
    binary = _ollama_binary()
    if binary is None:
        return False
    logs = state_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "ollama-supervisor.log"
    try:
        handle = log_path.open("ab")
        process = subprocess.Popen(
            [binary, "serve"],
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return False
    finally:
        if "handle" in locals():
            handle.close()
    (state_root / "ollama-start.pid").write_text(f"{process.pid}\n", encoding="utf-8")
    return True


async def _ensure_local_qwen(
    base_url: str,
    preferred: str,
    fallbacks: str,
    state_root: Path,
) -> tuple[str | None, str | None]:
    """Resolve a usable already-installed local model, self-starting Ollama once if needed."""
    candidates = _model_candidates(preferred, fallbacks)
    probe = OllamaClient(base_url, preferred, timeout=3, observation_only=False)
    if not await probe.available():
        if not _start_local_ollama(state_root):
            return None, "LOCAL_OLLAMA_UNAVAILABLE_AND_START_FAILED"
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if await probe.available():
                break
            await asyncio.sleep(1.0)
        else:
            return None, "LOCAL_OLLAMA_START_TIMEOUT"

    installed = await probe.installed_models()
    selected = _choose_local_model(installed, candidates)
    if selected is None:
        safe_installed = list(installed[:12])
        return None, f"LOCAL_QWEN_MODEL_MISSING candidates={list(candidates)} installed={safe_installed}"
    return selected, None


def _developer_env(repo_root: Path, args: argparse.Namespace, model: str) -> dict[str, str]:
    current = os.environ.get("PYTHONPATH", "")
    pythonpath = str(repo_root) if not current else str(repo_root) + os.pathsep + current
    return {
        **os.environ,
        "PYTHONPATH": pythonpath,
        "TIM_LOCAL_PATCH_SANDBOX": "1",
        "TIM_BLOCKER_AUTO_WAIT": "0",
        "TIM_LIVE_TRADING": "0",
        "TIM_EXECUTION_ENABLED": "0",
        "OLLAMA_BASE_URL": args.ollama_url,
        "OLLAMA_MODEL": model,
        "TIM_QWEN_FALLBACK_MODELS": args.fallback_models,
    }


def _run_developer_queue(repo_root: Path, args: argparse.Namespace, model: str) -> int:
    """Run the deterministic patch/verify/acceptance supervisor for the existing developer queue."""
    script = repo_root / "scripts/run_local_qwen_build_queue.py"
    if not script.is_file():
        print(json.dumps({
            "TIM_QWEN_SUPERVISOR": "SAFE_STOP",
            "reason": "developer build queue entrypoint missing",
        }), flush=True)
        return 2
    timeout = max(60, int(os.getenv("TIM_SUPERVISOR_TASK_TIMEOUT_SECONDS", "1800")))
    try:
        command = [sys.executable, str(script)]
        if args.pilot_task_id is not None:
            command.extend(["--task-id", args.pilot_task_id])
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=_developer_env(repo_root, args, model),
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(json.dumps({
            "TIM_QWEN_SUPERVISOR": "SAFE_STOP",
            "reason": "developer queue timeout",
            "timeout_seconds": timeout,
        }), flush=True)
        return 2
    except OSError as exc:
        print(json.dumps({
            "TIM_QWEN_SUPERVISOR": "SAFE_STOP",
            "reason": f"developer queue launch failed: {type(exc).__name__}",
        }), flush=True)
        return 2
    return completed.returncode


SELF_UPDATED_EXIT = 3


def _run_github_intake(repo_root: Path, args: argparse.Namespace) -> int:
    script = repo_root / "scripts/run_mac_qwen_issue.py"
    if not script.is_file():
        print(json.dumps({"TIM_GITHUB_INTAKE": "SAFE_STOP", "reason": "runner missing"}), flush=True)
        return 2
    command = [sys.executable, str(script), "--repository", str(repo_root)]
    if args.github_pilot_issue is not None:
        command.extend(["--pilot-issue", str(args.github_pilot_issue)])
    if args.github_merge:
        command.append("--merge")
    if args.github_pilot_issue is None and os.getenv("TIM_GITHUB_TRIAGE", "1") != "0":
        command.append("--triage")
    if os.getenv("TIM_WORKER_SELF_UPDATE", "1") != "0":
        command.append("--self-update")
    try:
        completed = subprocess.run(command, cwd=repo_root, text=True, capture_output=True,
                                   check=False, timeout=1900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"TIM_GITHUB_INTAKE": "SAFE_STOP", "error_type": type(exc).__name__}), flush=True)
        return 2
    state = {0: "DONE", SELF_UPDATED_EXIT: "SELF_UPDATED"}.get(completed.returncode, "BLOCKED")
    print(json.dumps({"TIM_GITHUB_INTAKE": state,
                      "returncode": completed.returncode,
                      "output": completed.stdout.strip()[:500],
                      # The runner reports its safe-stop reason on stderr.
                      "error": (completed.stderr or "").strip()[-500:]}), flush=True)
    return completed.returncode


def _requeue_resolved(state_root: Path, inbox: Path, pilot_task_id: str | None = None) -> set[str]:
    requeued: set[str] = set()
    tasks_root = state_root / "tasks"
    resolutions = state_root / "blockers/resolutions"
    if not tasks_root.exists() or not resolutions.exists():
        return requeued
    mailbox = BlockerMailbox(state_root / "blockers")
    for resolution in sorted(resolutions.glob("*.json")):
        task_id = resolution.stem
        if pilot_task_id is not None and task_id != pilot_task_id:
            continue
        if mailbox.read_resolution(task_id) is None:
            continue
        persisted = tasks_root / f"{task_id}.json"
        target = inbox / f"{task_id}.json"
        if not persisted.exists() or target.exists():
            continue
        payload = json.loads(persisted.read_text(encoding="utf-8"))
        if payload.get("state") != "BLOCKED":
            continue
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        requeued.add(task_id)
    return requeued


def _consume_resolution(state_root: Path, task_id: str) -> None:
    source = state_root / "blockers/resolutions" / f"{task_id}.json"
    if not source.exists():
        return
    consumed = state_root / "blockers/resolutions-consumed"
    consumed.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), consumed / f"{task_id}.{time.time_ns()}.json")


def _route_active_blocker(state_root: Path, task_path: Path | None) -> None:
    if task_path is None:
        return
    try:
        task_id = json.loads(task_path.read_text(encoding="utf-8"))["task_id"]
    except (OSError, ValueError, KeyError, TypeError):
        return
    broker = ProviderBroker(state_root, automatic=True)
    try:
        if broker.status(task_id)["state"] == "ROUTING":
            result = broker.route(task_id)
            print(json.dumps({"TIM_BLOCKER_BROKER": result["state"], "task_id": task_id}), flush=True)
    except FileNotFoundError:
        return  # An inbox task has not produced a blocker request yet.
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"TIM_BLOCKER_BROKER": "SAFE_STOP", "task_id": task_id,
                          "error_type": type(exc).__name__}), flush=True)


def _publish_linked_github_blocker(repo_root: Path, state_root: Path, task_path: Path, task_id: str) -> None:
    """Escalate a failed GitHub-fed task on its own issue, once per request."""
    if os.getenv("TIM_QWEN_GITHUB_ESCALATION") != "1":
        return
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
        issue = task.get("issue_number")
        if (not isinstance(issue, int) or isinstance(issue, bool) or issue < 1
                or task_id != f"github-issue-{issue}"):
            return
        request = state_root / "blockers/requests" / f"{task_id}.json"
        if not request.is_file():
            return
        digest = hashlib.sha256(request.read_bytes()).hexdigest()
        marker = state_root / "blockers/github-published" / f"{task_id}.{digest}.json"
        if marker.is_file():
            return
        bridge = repo_root / "scripts/github_blocker_bridge.py"
        completed = subprocess.run(
            [sys.executable, str(bridge), "publish", "--request", str(request),
             "--issue", str(issue), "--escalate"],
            cwd=repo_root, capture_output=True, text=True, check=False, timeout=45,
        )
        if completed.returncode == 0:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"task_id": task_id, "issue": issue, "request_sha256": digest}) + "\n",
                              encoding="utf-8")
            marker.chmod(0o600)
        print(json.dumps({"TIM_GITHUB_ESCALATION": "PUBLISHED" if completed.returncode == 0 else "SAFE_STOP",
                          "task_id": task_id, "issue": issue}), flush=True)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"TIM_GITHUB_ESCALATION": "SAFE_STOP", "task_id": task_id,
                          "error_type": type(exc).__name__}), flush=True)


def _archive(source: Path, processed: Path, state: str) -> None:
    processed.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    shutil.move(str(source), processed / f"{source.stem}.{state.lower()}.{stamp}.json")


async def daemon(args: argparse.Namespace) -> int:
    repo_root = args.repo_root.resolve()
    state_root = _resolve(repo_root, args.state_root)
    recipes = _resolve(repo_root, args.recipes)
    inbox = state_root / "inbox"
    processed = state_root / "processed"
    inbox.mkdir(parents=True, exist_ok=True)

    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)

    # One top-level coordinator per repository. The child build queue owns its own narrower
    # supervisor.lock while it is actively applying/verifying patches.
    with SingleInstance(_developer_state(repo_root) / "daemon.lock"):
        next_github_poll = 0.0
        print(json.dumps({
            "TIM_QWEN_SUPERVISOR": "RUNNING",
            "policy": "LOCAL_FIRST_WIP_1",
            "developer_priority": True,
            "live_trading": "DISABLED",
            "execution": "DISABLED",
        }), flush=True)
        while not stopping:
            developer_task = _next_task(_developer_state(repo_root) / "developer-inbox", args.pilot_task_id)
            if developer_task is not None:
                _route_active_blocker(_developer_state(repo_root), developer_task)
            else:
                _route_active_blocker(state_root, _next_task(inbox, args.pilot_task_id))
            # Self-improving code repair has strict priority. Never process a second operational
            # task while an A3 developer task is waiting, repairing, verifying or blocked.
            if _developer_task_pending(repo_root, args.pilot_task_id):
                model, error = await _ensure_local_qwen(
                    args.ollama_url,
                    args.model,
                    args.fallback_models,
                    _developer_state(repo_root),
                )
                if model is None:
                    print(json.dumps({
                        "TIM_QWEN_SUPERVISOR": "LOCAL_BLOCKED",
                        "scope": "developer_queue",
                        "reason": error,
                        "external_fallback": "ELIGIBLE_ONLY_AFTER_LOCAL_PATH_EXHAUSTED",
                    }), flush=True)
                    await asyncio.sleep(max(DEFAULT_BLOCKED_RETRY_SECONDS, args.interval))
                    continue
                print(json.dumps({
                    "TIM_QWEN_SUPERVISOR": "DEVELOPER_QUEUE",
                    "model": model,
                    "wip": 1,
                }), flush=True)
                code = _run_developer_queue(repo_root, args, model)
                if code != 0:
                    print(json.dumps({
                        "TIM_QWEN_SUPERVISOR": "DEVELOPER_BLOCKED",
                        "returncode": code,
                        "policy": "KEEP_SAME_TASK_NO_SUBTASK",
                    }), flush=True)
                    await asyncio.sleep(max(DEFAULT_BLOCKED_RETRY_SECONDS, args.interval))
                continue

            resumed_ids = _requeue_resolved(state_root, inbox, args.pilot_task_id)
            task_path = _next_task(inbox, args.pilot_task_id)
            if task_path is None:
                if args.github_intake and time.monotonic() >= next_github_poll:
                    next_github_poll = time.monotonic() + 300.0
                    model, error = await _ensure_local_qwen(
                        args.ollama_url, args.model, args.fallback_models, _developer_state(repo_root))
                    if model is None:
                        # Without local Qwen every issue attempt would fail and use up its retries.
                        print(json.dumps({"TIM_GITHUB_INTAKE": "WAITING_FOR_OLLAMA", "reason": error}),
                              flush=True)
                    elif _run_github_intake(repo_root, args) == SELF_UPDATED_EXIT:
                        # The checkout moved to the newest platform-main; launchd restarts us on it.
                        print(json.dumps({"TIM_QWEN_SUPERVISOR": "RESTART_FOR_UPDATE"}), flush=True)
                        return 0
                await asyncio.sleep(args.interval)
                continue

            model, error = await _ensure_local_qwen(args.ollama_url, args.model, args.fallback_models, state_root)
            if model is None:
                print(json.dumps({
                    "TIM_QWEN_SUPERVISOR": "LOCAL_BLOCKED",
                    "scope": "operational_queue",
                    "reason": error,
                }), flush=True)
                await asyncio.sleep(max(DEFAULT_BLOCKED_RETRY_SECONDS, args.interval))
                continue

            worker = LocalPrimaryWorker(
                repo_root=repo_root,
                state_root=state_root,
                ollama=OllamaClient(args.ollama_url, model),
                recipes=RepairRecipeStore(recipes),
                context=LocalGraphifyContextAdapter(repo_root),
            )
            try:
                result = await worker.run_once(task_path)
                if result.state == "BLOCKED":
                    broker = ProviderBroker(state_root, automatic=True)
                    try:
                        routed = broker.route(result.task_id)
                    except (OSError, ValueError, KeyError, json.JSONDecodeError):
                        routed = {"state": "ROUTER_FAILED"}
                    print(json.dumps({"TIM_BLOCKER_ADVISOR": routed["state"],
                                      "task_id": result.task_id}), flush=True)
                    if routed["state"] != "RESOLVED":
                        _publish_linked_github_blocker(repo_root, state_root, task_path, result.task_id)
                _archive(task_path, processed, result.state)
                if result.task_id in resumed_ids:
                    _consume_resolution(state_root, result.task_id)
                print(json.dumps({
                    "task_id": result.task_id,
                    "state": result.state,
                    "next_action": result.next_action,
                    "blocker_reason": result.blocker_reason,
                    "model": model,
                }, sort_keys=True), flush=True)
            except Exception as exc:
                # Keep the input in the inbox for deterministic retry. Never silently skip work.
                print(json.dumps({
                    "TIM_QWEN_SUPERVISOR": "SAFE_STOP",
                    "error": type(exc).__name__,
                }), flush=True)
                await asyncio.sleep(max(args.interval, 5.0))
        return 0


def main() -> int:
    args = parser().parse_args()
    return asyncio.run(daemon(args))


if __name__ == "__main__":
    raise SystemExit(main())
