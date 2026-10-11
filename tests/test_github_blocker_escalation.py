import json
from pathlib import Path

from scripts import github_blocker_bridge
from scripts.run_local_qwen_build_queue import _escalation_issue
from scripts.run_local_qwen_daemon import _next_task, _publish_linked_github_blocker


def test_only_a_task_linked_to_its_own_issue_escalates():
    assert _escalation_issue({"issue_number": 42, "task_id": "github-issue-42"}, 12) == (42, True)
    assert _escalation_issue({"issue_number": 42, "task_id": "other-task"}, 12) == (12, False)
    assert _escalation_issue({"issue_number": True}, 12) == (12, False)
    assert _escalation_issue({}, 12) == (12, False)


def test_pilot_task_filter_leaves_other_backlog_untouched(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    existing = inbox / "other-task.json"
    existing.write_text("{}", encoding="utf-8")
    assert _next_task(inbox, "github-issue-42") is None
    assert existing.is_file()
    selected = inbox / "github-issue-42.json"
    selected.write_text("{}", encoding="utf-8")
    assert _next_task(inbox, "github-issue-42") == selected


def test_publish_marks_only_explicit_escalation(monkeypatch, tmp_path: Path):
    calls = []

    def fake_gh(argv, *, input_text=None):
        calls.append((argv, input_text))
        if argv[:2] == ["api", "user"]:
            return "qwen-worker\n"
        if argv[:2] == ["api", "repos/owner/repo"]:
            return json.dumps({"admin": False, "maintain": False})
        return ""

    monkeypatch.setattr(github_blocker_bridge, "_gh", fake_gh)
    request = tmp_path / "blocker.json"
    request.write_text(json.dumps({"kind": "BLOCKER_REQUEST", "task_id": "github-issue-42",
                                   "blocker_reason": "test failed", "evidence": ["test log"]}), encoding="utf-8")

    github_blocker_bridge.publish(request, 42, "owner/repo")
    assert len(calls) == 1
    assert "TIM_BLOCKER_REQUEST task_id=github-issue-42" in calls[0][1]

    calls.clear()
    monkeypatch.setenv("TIM_QWEN_WORKER_LOGIN", "qwen-worker")
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "worker-gh"))
    github_blocker_bridge.publish(request, 42, "owner/repo", escalate=True)
    assert len(calls) == 4
    assert calls[-1][0] == ["issue", "edit", "42", "--repo", "owner/repo", "--add-label", "agent:escalate"]


def test_operational_blocker_uses_own_issue_once(monkeypatch, tmp_path: Path):
    from subprocess import CompletedProcess
    import scripts.run_local_qwen_daemon as daemon

    repo, state = tmp_path / "repo", tmp_path / "state"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/github_blocker_bridge.py").write_text("", encoding="utf-8")
    request = state / "blockers/requests/github-issue-42.json"
    request.parent.mkdir(parents=True)
    request.write_text(json.dumps({"kind": "BLOCKER_REQUEST", "task_id": "github-issue-42",
                                   "reason": "test failed", "evidence": []}), encoding="utf-8")
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"task_id": "github-issue-42", "issue_number": 42}), encoding="utf-8")
    calls = []
    monkeypatch.setenv("TIM_QWEN_GITHUB_ESCALATION", "1")
    monkeypatch.setattr(daemon.subprocess, "run", lambda args, **kwargs: (calls.append(args) or CompletedProcess(args, 0)))
    _publish_linked_github_blocker(repo, state, task, "github-issue-42")
    _publish_linked_github_blocker(repo, state, task, "github-issue-42")
    assert len(calls) == 1
    assert calls[0][-2:] == ["42", "--escalate"]
