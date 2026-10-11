from __future__ import annotations

from types import SimpleNamespace

from src.local_first import codex_patch_fallback


def test_codex_proposal_is_read_only_and_has_no_github_credentials(tmp_path, monkeypatch):
    binary = tmp_path / "codex"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setenv("TIM_CODEX_BIN", str(binary))
    monkeypatch.setenv("GH_TOKEN", "secret-test-token")
    monkeypatch.setenv("GITHUB_TOKEN", "other-secret-test-token")
    monkeypatch.setenv("GH_CONFIG_DIR", "/private/worker-config")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-secret")

    def fake_run(args, **kwargs):
        assert args[:4] == [str(binary), "exec", "--model", "gpt-5.6-luna"]
        assert "read-only" in args and "--ephemeral" in args
        assert "GH_TOKEN" not in kwargs["env"]
        assert "GITHUB_TOKEN" not in kwargs["env"]
        assert "GH_CONFIG_DIR" not in kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        assert kwargs["cwd"] != str(tmp_path)
        assert "Return exactly one JSON object" in kwargs["input"]
        output = args[args.index("--output-last-message") + 1]
        from pathlib import Path
        Path(output).write_text('{"patches": []}', encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(codex_patch_fallback.subprocess, "run", fake_run)
    assert codex_patch_fallback.propose("test prompt") == {"patches": []}
