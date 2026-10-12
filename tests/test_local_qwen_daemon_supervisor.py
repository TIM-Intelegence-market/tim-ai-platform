from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import install_local_qwen_launchd as installer
from scripts import run_local_qwen_daemon as daemon


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        ollama_url="http://127.0.0.1:11434",
        model="qwen2.5-coder:7b",
        fallback_models="qwen2.5:7b",
        pilot_task_id=None,
    )


def test_daemon_lock_is_crash_safe_and_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "daemon.lock"
    first = daemon.SingleInstance(path)
    first.__enter__()
    try:
        with pytest.raises(SystemExit, match="already running"):
            daemon.SingleInstance(path).__enter__()
    finally:
        first.__exit__(None, None, None)

    # The persistent lock file is harmless: after release a new process can lock the same inode.
    third = daemon.SingleInstance(path)
    third.__enter__()
    third.__exit__(None, None, None)


def test_local_model_selection_prefers_coder_then_installed_fallback() -> None:
    candidates = daemon._model_candidates("qwen2.5-coder:7b", "qwen2.5:7b,qwen2.5-coder:3b")
    assert candidates == ("qwen2.5-coder:7b", "qwen2.5:7b", "qwen2.5-coder:3b")
    assert daemon._choose_local_model(("qwen2.5-coder:7b", "qwen2.5:7b"), candidates) == "qwen2.5-coder:7b"
    assert daemon._choose_local_model(("qwen2.5:7b",), candidates) == "qwen2.5:7b"
    assert daemon._choose_local_model(("other:latest",), candidates) is None


def test_local_qwen_preflight_uses_installed_fallback_without_external_provider(tmp_path: Path, monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def available(self) -> bool:
            return True

        async def installed_models(self) -> tuple[str, ...]:
            return ("qwen2.5:7b",)

    monkeypatch.setattr(daemon, "OllamaClient", FakeClient)
    monkeypatch.setattr(daemon, "_start_local_ollama", lambda _state: (_ for _ in ()).throw(AssertionError("must not start")))
    model, error = asyncio.run(
        daemon._ensure_local_qwen(
            "http://127.0.0.1:11434",
            "qwen2.5-coder:7b",
            "qwen2.5:7b",
            tmp_path,
        )
    )
    assert model == "qwen2.5:7b"
    assert error is None


def test_developer_queue_is_repo_local_and_detected(tmp_path: Path) -> None:
    inbox = tmp_path / ".tim/local-first/developer-inbox"
    inbox.mkdir(parents=True)
    assert daemon._developer_task_pending(tmp_path) is False
    (inbox / "task-1.json").write_text("{}", encoding="utf-8")
    assert daemon._developer_task_pending(tmp_path) is True


def test_developer_queue_child_environment_forces_safety(tmp_path: Path) -> None:
    env = daemon._developer_env(tmp_path, _args(), "qwen2.5:7b")
    assert env["TIM_LOCAL_PATCH_SANDBOX"] == "1"
    assert env["TIM_BLOCKER_AUTO_WAIT"] == "0"
    assert env["TIM_LIVE_TRADING"] == "0"
    assert env["TIM_EXECUTION_ENABLED"] == "0"
    assert env["OLLAMA_MODEL"] == "qwen2.5:7b"
    assert str(tmp_path) in env["PYTHONPATH"]


def test_developer_queue_invokes_existing_deterministic_supervisor(tmp_path: Path, monkeypatch) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    entrypoint = scripts / "run_local_qwen_build_queue.py"
    entrypoint.write_text("raise SystemExit(0)\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    assert daemon._run_developer_queue(tmp_path, _args(), "qwen2.5:7b") == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert command[1] == str(entrypoint)
    assert captured["cwd"] == tmp_path
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env["OLLAMA_MODEL"] == "qwen2.5:7b"
    assert child_env["TIM_LIVE_TRADING"] == "0"

    pilot = _args()
    pilot.pilot_task_id = "github-issue-166"
    assert daemon._run_developer_queue(tmp_path, pilot, "qwen2.5:7b") == 0
    assert captured["command"][-2:] == ["--task-id", "github-issue-166"]


def test_github_intake_invokes_only_pilot_issue_with_merge_gate(tmp_path: Path, monkeypatch) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    entrypoint = scripts / "run_mac_qwen_issue.py"
    entrypoint.write_text("# test\n", encoding="utf-8")
    captured = []

    def fake_run(command, **kwargs):
        captured.extend(command)
        return SimpleNamespace(returncode=0, stdout="No eligible Mac Qwen issue.", stderr="")

    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    args = _args()
    args.github_pilot_issue = 166
    args.github_merge = True
    monkeypatch.delenv("TIM_WORKER_SELF_UPDATE", raising=False)
    assert daemon._run_github_intake(tmp_path, args) == 0
    # A pilot issue never triggers triage of other issues.
    assert captured[1:] == [str(entrypoint), "--repository", str(tmp_path),
                             "--pilot-issue", "166", "--merge", "--self-update"]


def test_github_intake_triages_and_self_updates_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_mac_qwen_issue.py").write_text("# test\n", encoding="utf-8")
    captured = []

    def fake_run(command, **kwargs):
        captured.append(command)
        return SimpleNamespace(returncode=daemon.SELF_UPDATED_EXIT, stdout="TIM_SELF_UPDATED a -> b", stderr="")

    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    monkeypatch.delenv("TIM_GITHUB_TRIAGE", raising=False)
    monkeypatch.delenv("TIM_WORKER_SELF_UPDATE", raising=False)
    args = _args()
    args.github_pilot_issue = None
    args.github_merge = True
    assert daemon._run_github_intake(tmp_path, args) == daemon.SELF_UPDATED_EXIT
    assert captured[0][-3:] == ["--merge", "--triage", "--self-update"]
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["TIM_GITHUB_INTAKE"] == "SELF_UPDATED"

    monkeypatch.setenv("TIM_GITHUB_TRIAGE", "0")
    monkeypatch.setenv("TIM_WORKER_SELF_UPDATE", "0")
    daemon._run_github_intake(tmp_path, args)
    assert "--triage" not in captured[1] and "--self-update" not in captured[1]


def test_github_intake_logs_the_runner_stop_reason(tmp_path: Path, monkeypatch, capsys) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_mac_qwen_issue.py").write_text("# test\n", encoding="utf-8")
    monkeypatch.setattr(daemon.subprocess, "run", lambda *_a, **_k: SimpleNamespace(
        returncode=2, stdout="",
        stderr="Mac Qwen issue worker stopped safely: issue worktree or branch already exists"))
    args = _args()
    args.github_pilot_issue = 166
    args.github_merge = False
    assert daemon._run_github_intake(tmp_path, args) == 2
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["TIM_GITHUB_INTAKE"] == "BLOCKED"
    assert "worktree or branch already exists" in line["error"]


def test_launchd_payload_runs_unified_daemon_with_local_patch_gate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    worker = repo / "scripts/run_local_qwen_daemon.py"
    payload = installer._plist_payload(
        repo=repo,
        python=Path("/usr/bin/python3"),
        worker=worker,
        state=tmp_path / "state",
        logs=tmp_path / "logs",
        model="qwen2.5-coder:7b",
        fallback_models="qwen2.5:7b",
        interval=5.0,
    )
    arguments = payload["ProgramArguments"]
    assert str(worker) in arguments
    assert "--fallback-models" in arguments
    env = payload["EnvironmentVariables"]
    assert env["TIM_LOCAL_PATCH_SANDBOX"] == "1"
    assert env["TIM_BLOCKER_AUTO_WAIT"] == "0"
    assert env["TIM_LIVE_TRADING"] == "0"
    assert env["TIM_EXECUTION_ENABLED"] == "0"
