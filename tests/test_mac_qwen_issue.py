from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_mac_qwen_issue import _assert_task_diff, _merge_when_ready
from scripts.github_issue_pipeline import PipelineError


class FakePipeline:
    def __init__(self, paths=None, states=None):
        self.paths = paths or []
        self.states = iter(states or [])
        self.merges = []

    def worktree_git(self, worktree, gitdir, *args):
        if args[:2] == ("diff", "--name-only"):
            return "\0".join(self.paths) + "\0"
        if args[:2] == ("ls-files", "--others"):
            return ""
        raise AssertionError(args)

    def github(self, *args):
        if args[:2] == ("pr", "view"):
            return json.dumps(next(self.states))
        self.merges.append(args)
        return ""


def test_rejects_changes_outside_issue_allowlist(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/allowed.py").write_text("VALUE = 2\n", encoding="utf-8")
    task = {"allowed_paths": ["src/allowed.py"]}
    assert _assert_task_diff(FakePipeline(["src/allowed.py", ".tim/state.json"]), tmp_path,
                           tmp_path / ".git", task) == ["src/allowed.py"]
    with pytest.raises(PipelineError):
        _assert_task_diff(FakePipeline(["src/allowed.py", "src/extra.py"]), tmp_path,
                          tmp_path / ".git", task)


def test_merge_requires_exact_worker_pr_head():
    state = {"state": "OPEN", "mergeStateStatus": "CLEAN", "headRefOid": "expected",
             "headRefName": "codex/issue-5-qwen", "baseRefName": "platform-main",
             "author": {"login": "apoman74-art"}}
    pipeline = FakePipeline(states=[state])
    _merge_when_ready(pipeline, 8, "codex/issue-5-qwen", "expected", wait_seconds=1)
    assert pipeline.merges == [("pr", "merge", "8", "--squash")]
    with pytest.raises(PipelineError):
        _merge_when_ready(FakePipeline(states=[{**state, "headRefOid": "changed"}]),
                          8, "codex/issue-5-qwen", "expected", wait_seconds=1)


@pytest.mark.parametrize("tool_loop_env, expected", [(None, "1"), ("0", "0")])
def test_local_task_runs_with_required_test_sandbox(tmp_path: Path, monkeypatch, tool_loop_env, expected):
    from scripts import run_mac_qwen_issue

    if tool_loop_env is None:
        monkeypatch.delenv("TIM_QWEN_TOOL_LOOP", raising=False)
    else:
        monkeypatch.setenv("TIM_QWEN_TOOL_LOOP", tool_loop_env)
    monkeypatch.setenv("GH_TOKEN", "must-not-leak")
    seen = {}

    class FakePopen:
        pid = 0

        def __init__(self, command, **kwargs):
            seen.update(kwargs["env"])
            assert kwargs["start_new_session"] is True

        def wait(self, timeout=None):
            return 2

    monkeypatch.setattr(run_mac_qwen_issue.subprocess, "Popen", FakePopen)
    task = {"task_id": "github-issue-7", "allowed_paths": ["src/a.py"], "tests": ["tests/test_a.py"]}
    with pytest.raises(PipelineError):
        run_mac_qwen_issue._run_local_task(tmp_path, task, codex_fallback=False)
    assert seen["TIM_TEST_SANDBOX"] == "required"
    assert seen["TIM_QWEN_TOOL_LOOP"] == expected
    assert "GH_TOKEN" not in seen


def test_timeout_stops_the_whole_process_group(tmp_path: Path):
    import os
    import sys
    import time

    from scripts import run_mac_qwen_issue

    marker = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    with pytest.raises(PipelineError, match="timed out"):
        run_mac_qwen_issue._run_task_group([sys.executable, "-c", script], tmp_path, dict(os.environ), timeout=2)
    grandchild = int(marker.read_text())
    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("grandchild kept running after the timeout")


def test_hard_issue_routes_to_server_model_only_when_tunnel_answers(tmp_path: Path, monkeypatch):
    from scripts import run_mac_qwen_issue

    monkeypatch.setenv("TIM_QWEN_HARD_URL", "http://127.0.0.1:11435")
    monkeypatch.delenv("TIM_QWEN_HARD_MODEL", raising=False)
    seen = {}

    class FakePopen:
        pid = 0

        def __init__(self, command, **kwargs):
            seen.update(kwargs["env"])

        def wait(self, timeout=None):
            return 2

    monkeypatch.setattr(run_mac_qwen_issue.subprocess, "Popen", FakePopen)
    task = {"task_id": "github-issue-9", "allowed_paths": ["src/a.py"], "tests": ["tests/test_a.py"]}

    monkeypatch.setattr(run_mac_qwen_issue, "_hard_backend", lambda: ("http://127.0.0.1:11435", "qwen3-coder:30b"))
    with pytest.raises(PipelineError):
        run_mac_qwen_issue._run_local_task(tmp_path, task, codex_fallback=False, hard=True)
    assert seen["OLLAMA_BASE_URL"] == "http://127.0.0.1:11435"
    assert seen["OLLAMA_MODEL"] == "qwen3-coder:30b"
    assert seen["TIM_QWEN_REQUEST_TIMEOUT"] == run_mac_qwen_issue.HARD_REQUEST_TIMEOUT

    seen.clear()
    monkeypatch.setattr(run_mac_qwen_issue, "_hard_backend", lambda: None)
    with pytest.raises(PipelineError, match="server model unavailable"):
        run_mac_qwen_issue._run_local_task(tmp_path, task, codex_fallback=False, hard=True)
    assert not seen  # No Mac fallback starts after the server disappears.


def test_hard_backend_refuses_non_loopback_url(monkeypatch):
    from scripts import run_mac_qwen_issue

    monkeypatch.setenv("TIM_QWEN_HARD_URL", "http://192.168.10.121:11434")
    assert run_mac_qwen_issue._hard_backend() is None
    monkeypatch.delenv("TIM_QWEN_HARD_URL")
    assert run_mac_qwen_issue._hard_backend() is None


def test_review_patch_is_advisory_and_redacted(monkeypatch):
    from scripts import run_mac_qwen_issue

    monkeypatch.setattr(run_mac_qwen_issue, "_hard_backend", lambda: ("http://127.0.0.1:11435", "qwen3-coder:30b"))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def chat(self, messages, **kwargs):
            assert "Patch:" in messages[0]["content"]
            return {"content": "PROBLEM\nmissing test for ```edge``` case\nGH_TOKEN=ghp_abcdef1234567890 leaked\n\n\n6th\n7th\n8th"}

    import src.llm.ollama_client as module
    monkeypatch.setattr(module, "OllamaClient", FakeClient)
    task = {"objective": "fix", "allowed_paths": ["src/a.py"]}
    review = run_mac_qwen_issue._review_patch(task, "diff --git a/src/a.py b/src/a.py\n+x = 1\n")
    assert review["model"] == "qwen3-coder:30b"
    assert review["verdict"].startswith("PROBLEM")
    assert "```" not in review["verdict"]
    assert "ghp_abcdef1234567890" not in review["verdict"]
    assert len(review["verdict"].splitlines()) == 5

    monkeypatch.setattr(run_mac_qwen_issue, "_hard_backend", lambda: None)
    assert run_mac_qwen_issue._review_patch(task, "+x\n") is None

    class BrokenClient(FakeClient):
        async def chat(self, messages, **kwargs):
            raise OSError("tunnel down")

    monkeypatch.setattr(run_mac_qwen_issue, "_hard_backend", lambda: ("http://127.0.0.1:11435", "m"))
    monkeypatch.setattr(module, "OllamaClient", BrokenClient)
    assert run_mac_qwen_issue._review_patch(task, "+x\n") is None
