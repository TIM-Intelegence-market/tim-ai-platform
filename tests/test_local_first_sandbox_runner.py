from __future__ import annotations

from pathlib import Path

import pytest

from src.local_first import sandbox_runner
from src.local_first.patch_executor import SafePatchExecutor, redact_tokens


def test_seatbelt_profile_hides_credentials_and_blocks_network(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    scratch = tmp_path / "scratch"
    profile, denied = sandbox_runner.seatbelt_profile(repo, scratch, home)
    gh_dir = str((home / ".config/gh-tim-mac-worker").resolve())
    assert gh_dir in denied
    assert f'(subpath "{gh_dir}")' in profile
    assert '(global-name "com.apple.SecurityServer")' in profile
    assert "(deny network-outbound)" in profile
    assert '(allow network-outbound (remote ip "localhost:*"))' in profile
    # Only scratch is writable; the worktree is denied after that allowance (last rule wins),
    # because the worker later runs code from the worktree outside the sandbox.
    allow = profile.index(f'(allow file-write* (subpath "{scratch.resolve()}")')
    deny_repo = profile.index(f'(deny file-write* (subpath "{repo.resolve()}"))')
    assert allow < deny_repo
    assert f'(allow file-write* (subpath "{repo.resolve()}")' not in profile
    assert '(literal "/bin/launchctl")' in profile and '(literal "/usr/bin/security")' in profile
    assert profile.index('(deny network-outbound (remote ip "localhost:11434"))') > profile.index(
        '(allow network-outbound (remote ip "localhost:*"))')
    assert str((home / ".zsh_history").resolve()) in denied


def test_profile_escapes_quotes_in_paths(tmp_path):
    repo = tmp_path / 'we"ird'
    profile, _ = sandbox_runner.seatbelt_profile(repo, tmp_path / "s", tmp_path / "h")
    assert 'we\\"ird' in profile


def test_minimal_env_drops_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_" + "a" * 36)
    monkeypatch.setenv("GH_CONFIG_DIR", "/Users/x/.config/gh-tim-mac-worker")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    env = sandbox_runner.minimal_env(tmp_path, tmp_path / "repo")
    assert not {"GH_TOKEN", "GH_CONFIG_DIR", "OPENAI_API_KEY"} & set(env)
    assert env["HOME"] == str(tmp_path / "home") and Path(env["HOME"]).is_dir()
    assert env["TIM_LIVE_TRADING"] == "0" and env["TIM_EXECUTION_ENABLED"] == "0"


def test_darwin_plan_wraps_with_sandbox_exec(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner.os, "access", lambda path, mode: path == sandbox_runner.SANDBOX_EXEC)
    plan = sandbox_runner.plan(["python", "-m", "pytest"], tmp_path, mode="required",
                               platform="darwin", home=tmp_path / "home")
    try:
        assert plan.kind == "seatbelt"
        assert plan.argv[:2] == [sandbox_runner.SANDBOX_EXEC, "-f"]
        assert plan.argv[3:] == ["python", "-m", "pytest"]
        assert Path(plan.argv[2]).read_text().startswith("(version 1)")
    finally:
        plan.cleanup()
    assert not plan.scratch.exists()


def test_required_mode_fails_closed_without_sandbox(tmp_path):
    with pytest.raises(sandbox_runner.SandboxUnavailable):
        sandbox_runner.plan(["python"], tmp_path, mode="required", platform="linux")


def test_auto_mode_runs_unwrapped_with_minimal_env(tmp_path):
    plan = sandbox_runner.plan(["python"], tmp_path, mode="auto", platform="linux")
    try:
        assert plan.kind == "none" and plan.argv == ["python"]
    finally:
        plan.cleanup()


def test_unknown_mode_is_treated_as_required(monkeypatch):
    monkeypatch.setenv("TIM_TEST_SANDBOX", "maybe")
    assert sandbox_runner.configured_mode() == "required"


def test_executor_blocks_when_sandbox_required_but_missing(tmp_path, monkeypatch):
    if sandbox_runner.os.access(sandbox_runner.SANDBOX_EXEC, sandbox_runner.os.X_OK):
        pytest.skip("this machine has a sandbox")
    monkeypatch.setenv("TIM_TEST_SANDBOX", "required")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("def test_x():\n    assert True\n")
    result = SafePatchExecutor(tmp_path, tmp_path / "state")._run_tests(["tests/test_x.py"])
    assert result["returncode"] == 2
    assert result["stderr"].startswith("TEST_SANDBOX_UNAVAILABLE")


def test_model_written_test_cannot_see_worker_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("TIM_TEST_SANDBOX", "auto")
    monkeypatch.setenv("GH_TOKEN", "ghp_" + "b" * 36)
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "gh"))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_env.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "def test_env():\n"
        "    assert 'GH_TOKEN' not in os.environ and 'GH_CONFIG_DIR' not in os.environ\n"
        "    assert 'tim-test-sandbox-' in os.environ['HOME']\n"
        "def test_leak():\n"
        "    assert False, 'ghp_' + 'c' * 36\n"
    )
    result = SafePatchExecutor(tmp_path, tmp_path / "state")._run_tests(["tests/test_env.py"])
    assert result["returncode"] == 1, result
    assert "1 failed, 1 passed" in result["stdout"]
    assert "<REDACTED_TOKEN>" in result["stdout"]
    assert "ghp_" + "c" * 16 not in result["stdout"]


def test_redact_tokens_covers_common_shapes():
    text = "a ghp_" + "x" * 36 + " b github_pat_" + "y" * 30 + " c sk-" + "z" * 24
    assert redact_tokens(text) == "a <REDACTED_TOKEN> b <REDACTED_TOKEN> c <REDACTED_TOKEN>"
