from __future__ import annotations

import importlib.util
import plistlib
import sys
from pathlib import Path


def _load_installer():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts/install_local_qwen_launchd.py"
    )
    spec = importlib.util.spec_from_file_location(
        "tim_qwen_launchd_installer",
        path,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plist_payload_uses_safe_paths_and_minimal_environment(
    tmp_path: Path,
) -> None:
    installer = _load_installer()

    repo = tmp_path / "repo"
    worker = repo / "scripts/run_local_qwen_daemon.py"
    python = repo / ".venv/bin/python"
    state = (
        tmp_path
        / "Library/Application Support/TIM/local-first"
    )
    logs = tmp_path / "Library/Logs/TIM"

    payload = installer._plist_payload(
        repo=repo,
        python=python,
        worker=worker,
        state=state,
        logs=logs,
        model="qwen2.5:7b",
        fallback_models="qwen2.5:7b",
        interval=15.0,
    )

    assert payload["StandardOutPath"] == str(
        logs / "local-first.out.log"
    )
    assert payload["StandardErrorPath"] == str(
        logs / "local-first.err.log"
    )

    assert "Documents" not in payload["StandardOutPath"]
    assert "Documents" not in payload["StandardErrorPath"]

    args = payload["ProgramArguments"]
    state_index = args.index("--state-root")
    assert args[state_index + 1] == str(state)

    env = payload["EnvironmentVariables"]

    assert set(env) == {
        "PATH",
        "PYTHONPATH",
        "TIM_LOCAL_PATCH_SANDBOX",
        "TIM_BLOCKER_AUTO_WAIT",
        "TIM_LIVE_TRADING",
        "TIM_EXECUTION_ENABLED",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "TIM_QWEN_FALLBACK_MODELS",
        "TIM_TEST_SANDBOX",
        "TIM_QWEN_TOOL_LOOP",
    }
    assert env["TIM_TEST_SANDBOX"] == "required"
    assert env["TIM_QWEN_TOOL_LOOP"] == "1"

    assert env["TIM_LIVE_TRADING"] == "0"
    assert env["TIM_EXECUTION_ENABLED"] == "0"
    assert env["TIM_LOCAL_PATCH_SANDBOX"] == "1"
    assert env["PATH"].startswith("/opt/homebrew/bin:/usr/local/bin:")


def test_main_writes_library_plist_without_launchctl(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installer = _load_installer()

    home = tmp_path / "home"
    repo = tmp_path / "repo"
    worker = repo / "scripts/run_local_qwen_daemon.py"
    python = repo / ".venv/bin/python"

    worker.parent.mkdir(parents=True)
    worker.write_text("# test\n", encoding="utf-8")

    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))

    def forbidden_subprocess(*args, **kwargs):
        raise AssertionError(
            "launchctl/subprocess must not run without --load"
        )

    monkeypatch.setattr(
        installer.subprocess,
        "run",
        forbidden_subprocess,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "install_local_qwen_launchd.py",
            "--repo-root",
            str(repo),
            "--python",
            str(python),
            "--model",
            "qwen2.5:7b",
            "--interval",
            "15",
        ],
    )

    assert installer.main() == 0

    plist_path = (
        home
        / "Library/LaunchAgents/com.tim.local-qwen-worker.plist"
    )
    assert plist_path.is_file()

    with plist_path.open("rb") as handle:
        payload = plistlib.load(handle)

    assert payload["StandardOutPath"] == str(
        home / "Library/Logs/TIM/local-first.out.log"
    )
    assert payload["StandardErrorPath"] == str(
        home / "Library/Logs/TIM/local-first.err.log"
    )

    assert "Documents" not in payload["StandardOutPath"]
    assert "Documents" not in payload["StandardErrorPath"]

    env = payload["EnvironmentVariables"]
    assert env["TIM_LIVE_TRADING"] == "0"
    assert env["TIM_EXECUTION_ENABLED"] == "0"
