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
