from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import run_local_qwen_daemon as daemon
from src.local_first.provider_broker import request_digest
from src.local_first.runtime import BlockerMailbox, LocalTask


SingleInstance = daemon.SingleInstance


def test_stale_pid_file_is_reused_but_concurrent_holder_is_rejected(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.lock"
    lock_path.write_text("pid=999999999\n", encoding="utf-8")

    first = SingleInstance(lock_path)
    first.__enter__()
    try:
        assert lock_path.read_text(encoding="utf-8").startswith("pid=")
        with pytest.raises(SystemExit, match="already running"):
            SingleInstance(lock_path).__enter__()
    finally:
        first.__exit__(None, None, None)

    with SingleInstance(lock_path):
        assert lock_path.read_text(encoding="utf-8").startswith("pid=")


def test_lock_path_symlink_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("must remain unchanged\n", encoding="utf-8")
    lock_path = tmp_path / "daemon.lock"
    lock_path.symlink_to(target)

    with pytest.raises(SystemExit, match="lock is unsafe"):
        SingleInstance(lock_path).__enter__()

    assert target.read_text(encoding="utf-8") == "must remain unchanged\n"


def test_nonregular_lock_path_fails_closed_without_blocking(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.lock"
    os.mkfifo(lock_path)

    with pytest.raises(SystemExit, match="lock is unsafe"):
        SingleInstance(lock_path).__enter__()


def test_abrupt_child_exit_releases_lock_and_preserves_task(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.lock"
    task_path = tmp_path / "task.json"
    task = {"task_id": "resume-me", "state": "IN_PROGRESS", "attempt_count": 2}
    task_path.write_text(json.dumps(task, sort_keys=True) + "\n", encoding="utf-8")
    script = (
        "import sys,time; from pathlib import Path; "
        "from scripts.run_local_qwen_daemon import SingleInstance; "
        "lock=SingleInstance(Path(sys.argv[1])); lock.__enter__(); "
        "print('locked', flush=True); time.sleep(60)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path)],
        cwd=Path(__file__).parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(SystemExit, match="already running"):
            SingleInstance(lock_path).__enter__()
        child.kill()
        child.wait(timeout=5)
        with SingleInstance(lock_path):
            assert json.loads(task_path.read_text(encoding="utf-8")) == task
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_flock_error_closes_descriptor(tmp_path: Path, monkeypatch) -> None:
    real_fdopen = os.fdopen
    retained: list[object] = []

    def retain(fd: int, *args, **kwargs):
        handle = real_fdopen(fd, *args, **kwargs)
        retained.append(handle)
        return handle

    def fail(_fd: int, _operation: int) -> None:
        raise OSError("injected flock failure")

    monkeypatch.setattr(daemon.os, "fdopen", retain)
    monkeypatch.setattr(daemon.fcntl, "flock", fail)
    with pytest.raises(OSError, match="injected flock failure"):
        SingleInstance(tmp_path / "daemon.lock").__enter__()

    assert len(retained) == 1
    assert retained[0].closed is True


def test_router_proposal_requeues_blocked_operational_task(tmp_path: Path) -> None:
    state = tmp_path / "state"
    task_id = "blocked-one"
    tasks = state / "tasks"
    resolutions = state / "blockers/resolutions"
    inbox = state / "inbox"
    for folder in (tasks, resolutions, inbox):
        folder.mkdir(parents=True)
    (tasks / f"{task_id}.json").write_text(json.dumps({"task_id": task_id, "state": "BLOCKED"}), encoding="utf-8")
    request = BlockerMailbox(state / "blockers").create_request(LocalTask(task_id, "Inspect", "Review"), "blocked", [])
    (resolutions / f"{task_id}.json").write_text(json.dumps({"kind": "BLOCKER_PROPOSAL", "task_id": task_id,
        "request_sha256": request_digest(request), "authority": "ADVISORY_ONLY", "proposal": {"diagnosis": "Check config"}}), encoding="utf-8")
    assert daemon._requeue_resolved(state, inbox) == {task_id}
    assert (inbox / f"{task_id}.json").is_file()
