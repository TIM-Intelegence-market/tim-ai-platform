from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.local_first import claude_cli_fallback


def _fake_binary(tmp_path, monkeypatch):
    binary = tmp_path / "claude"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setenv("TIM_CLAUDE_BIN", str(binary))
    return binary


def test_claude_proposal_has_no_tools_and_no_github_credentials(tmp_path, monkeypatch):
    binary = _fake_binary(tmp_path, monkeypatch)
    monkeypatch.setenv("GH_TOKEN", "secret-test-token")
    monkeypatch.setenv("GH_CONFIG_DIR", "/private/worker-config")
    monkeypatch.setenv("TIM_QWEN_WORKER_LOGIN", "apoman74-art")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")

    def fake_run(args, **kwargs):
        assert args[:4] == [str(binary), "-p", "--model", "sonnet"]
        assert args[args.index("--tools") + 1] == ""
        assert "--restricted" in args and "--strict-mcp-config" in args
        assert "--no-session-persistence" in args
        for key in ("GH_TOKEN", "GH_CONFIG_DIR", "TIM_QWEN_WORKER_LOGIN", "OPENAI_API_KEY"):
            assert key not in kwargs["env"]
        assert kwargs["cwd"] != str(tmp_path)
        assert "Return exactly one JSON object" in kwargs["input"]
        return SimpleNamespace(returncode=0, stdout='```json\n{"patches": []}\n```\n')

    monkeypatch.setattr(claude_cli_fallback.subprocess, "run", fake_run)
    assert claude_cli_fallback.propose("test prompt") == {"patches": []}


def test_claude_advice_and_failures(tmp_path, monkeypatch):
    _fake_binary(tmp_path, monkeypatch)
    replies = [SimpleNamespace(returncode=0, stdout="Check the fixture path\n"),
               SimpleNamespace(returncode=1, stdout="usage limit reached")]
    monkeypatch.setattr(claude_cli_fallback.subprocess, "run", lambda *_a, **_k: replies.pop(0))
    assert claude_cli_fallback.advise({"task_id": "t"}) == "Check the fixture path"
    with pytest.raises(RuntimeError):
        claude_cli_fallback.advise({"task_id": "t"})


def test_claude_missing_binary_and_bad_model(tmp_path, monkeypatch):
    monkeypatch.setenv("TIM_CLAUDE_BIN", str(tmp_path / "missing"))
    with pytest.raises(FileNotFoundError):
        claude_cli_fallback.propose("x")
    _fake_binary(tmp_path, monkeypatch)
    monkeypatch.setenv("TIM_CLAUDE_MODEL", "sonnet; rm -rf")
    with pytest.raises(ValueError):
        claude_cli_fallback.propose("x")


def test_default_binary_prefers_native_then_homebrew(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_cli_fallback.Path, "home", lambda: tmp_path)
    native = tmp_path / ".local/bin/claude"
    assert claude_cli_fallback.default_binary() in {
        native, claude_cli_fallback.Path("/opt/homebrew/bin/claude"),
        claude_cli_fallback.Path("/usr/local/bin/claude")}
    native.parent.mkdir(parents=True)
    native.write_text("", encoding="utf-8")
    assert claude_cli_fallback.default_binary() == native
