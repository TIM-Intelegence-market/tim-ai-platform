from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest


def _load_installer():
    path = Path(__file__).resolve().parents[1] / "scripts/install_local_qwen_launchd.py"
    spec = importlib.util.spec_from_file_location("tim_qwen_launchd_installer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plist_preserves_venv_python_and_repo_pythonpath(tmp_path: Path) -> None:
    installer = _load_installer()
    repo = tmp_path / "repo"
    worker = repo / "scripts/run_local_qwen_daemon.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("# test\n", encoding="utf-8")

    real_python = tmp_path / "framework-python"
    real_python.write_text("", encoding="utf-8")
    venv_python = repo / ".venv/bin/python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(real_python)

    payload = installer._plist_payload(
        repo=repo,
        python=venv_python,
        worker=worker,
        state=tmp_path / "state",
        logs=tmp_path / "logs",
        model="qwen2.5-coder:7b",
        fallback_models="qwen2.5:7b",
        interval=5.0,
    )

    assert payload["ProgramArguments"][0] == str(venv_python.absolute())
    assert payload["ProgramArguments"][0] != str(real_python.resolve())
    assert payload["EnvironmentVariables"]["PYTHONPATH"] == str(repo)
    assert "/opt/homebrew/bin" in payload["EnvironmentVariables"]["PATH"]
    assert payload["EnvironmentVariables"]["TIM_LIVE_TRADING"] == "0"
    assert payload["EnvironmentVariables"]["TIM_EXECUTION_ENABLED"] == "0"


def test_github_escalation_requires_separate_worker_config(tmp_path: Path) -> None:
    installer = _load_installer()
    kwargs = dict(
        repo=tmp_path, python=tmp_path / "python", worker=tmp_path / "worker.py",
        state=tmp_path / "state", logs=tmp_path / "logs", model="qwen3.5:9b",
        fallback_models="", interval=5.0,
    )
    with pytest.raises(ValueError):
        installer._plist_payload(**kwargs, enable_github_escalation=True)
    payload = installer._plist_payload(
        **kwargs, enable_github_escalation=True,
        github_worker_login="apoman74-art", github_config_dir=tmp_path / "gh-worker",
    )
    env = payload["EnvironmentVariables"]
    assert env["GH_CONFIG_DIR"] == str(tmp_path / "gh-worker")
    assert env["TIM_QWEN_WORKER_LOGIN"] == "apoman74-art"
    assert env["TIM_QWEN_GITHUB_ESCALATION"] == "1"


def test_codex_patch_fallback_is_opt_in(tmp_path: Path) -> None:
    installer = _load_installer()
    kwargs = dict(repo=tmp_path, python=tmp_path / "python", worker=tmp_path / "worker.py",
                  state=tmp_path / "state", logs=tmp_path / "logs", model="qwen3.5:9b",
                  fallback_models="", interval=5.0)
    assert "TIM_CODEX_PATCH_FALLBACK" not in installer._plist_payload(**kwargs)["EnvironmentVariables"]
    payload = installer._plist_payload(**kwargs, enable_codex_patch_fallback=True)
    assert payload["EnvironmentVariables"]["TIM_CODEX_PATCH_FALLBACK"] == "1"


def test_claude_fallbacks_are_opt_in(tmp_path: Path) -> None:
    installer = _load_installer()
    kwargs = dict(repo=tmp_path, python=tmp_path / "python", worker=tmp_path / "worker.py",
                  state=tmp_path / "state", logs=tmp_path / "logs", model="qwen3.5:9b",
                  fallback_models="", interval=5.0)
    env = installer._plist_payload(**kwargs)["EnvironmentVariables"]
    assert not {key for key in env if key.startswith("TIM_CLAUDE_")}
    env = installer._plist_payload(**kwargs, enable_claude_advisor=True,
                                   enable_claude_patch_fallback=True)["EnvironmentVariables"]
    assert env["TIM_CLAUDE_BLOCKER_ADVISOR"] == "1"
    assert env["TIM_CLAUDE_PATCH_FALLBACK"] == "1"
    assert env["TIM_CLAUDE_MODEL"] == "sonnet"
    assert env["TIM_CLAUDE_BIN"].endswith("/claude")
    env = installer._plist_payload(**kwargs, enable_claude_patch_fallback=True,
                                   claude_bin=Path("/opt/homebrew/bin/claude"))["EnvironmentVariables"]
    assert env["TIM_CLAUDE_BIN"] == "/opt/homebrew/bin/claude"
    assert not any("KEY" in key or "TOKEN" in key for key in env)


def test_github_intake_has_worker_identity_and_pilot_scope(tmp_path: Path) -> None:
    installer = _load_installer()
    kwargs = dict(repo=tmp_path, python=tmp_path / "python", worker=tmp_path / "worker.py",
                  state=tmp_path / "state", logs=tmp_path / "logs", model="qwen3.5:9b",
                  fallback_models="", interval=5.0)
    with pytest.raises(ValueError):
        installer._plist_payload(**kwargs, enable_github_intake=True)
    payload = installer._plist_payload(**kwargs, enable_github_intake=True, github_pilot_issue=166,
                                       github_merge=True, github_worker_login="apoman74-art",
                                       github_config_dir=tmp_path / "worker-gh")
    assert payload["ProgramArguments"][-4:] == ["--github-intake", "--github-pilot-issue", "166", "--github-merge"]
    assert payload["EnvironmentVariables"]["GH_CONFIG_DIR"] == str(tmp_path / "worker-gh")


def test_worker_lane_is_kept_from_installer_environment(tmp_path: Path, monkeypatch) -> None:
    installer = _load_installer()
    kwargs = dict(repo=tmp_path, python=tmp_path / "python", worker=tmp_path / "worker.py",
                  state=tmp_path / "state", logs=tmp_path / "logs", model="qwen3.5:9b",
                  fallback_models="", interval=5.0)
    monkeypatch.delenv("TIM_WORKER_LANE", raising=False)
    assert "TIM_WORKER_LANE" not in installer._plist_payload(**kwargs)["EnvironmentVariables"]
    monkeypatch.setenv("TIM_WORKER_LANE", "easy")
    assert installer._plist_payload(**kwargs)["EnvironmentVariables"]["TIM_WORKER_LANE"] == "easy"
