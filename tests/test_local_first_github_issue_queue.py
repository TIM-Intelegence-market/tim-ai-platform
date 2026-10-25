import json

import pytest

from src.local_first.github_issue_queue import build_task, select_ready_issue


def _issue(number, labels, **changes):
    issue = {"number": number, "state": "open", "labels": [{"name": name} for name in labels]}
    issue.update(changes)
    return issue


def test_selects_priority_then_issue_number():
    ready = ["agent:qwen-ready", "status:ready"]
    issues = [
        _issue(8, ready + ["priority:p1"]),
        _issue(7, ready + ["priority:p0"]),
        _issue(3, ready + ["priority:p0"]),
    ]
    assert select_ready_issue(issues)["number"] == 3
    assert select_ready_issue(issues, only_number=8)["number"] == 8


def test_rejects_blocked_epic_pull_request_and_malformed_issue():
    ready = ["agent:qwen-ready", "status:ready", "priority:p0"]
    issues = [
        _issue(1, ready + ["blocked"]),
        _issue(2, ready + ["epic"]),
        _issue(3, ready, pull_request={"url": "https://example.invalid/pr"}),
        _issue(4, ready, state="closed"),
        _issue(True, ready),
        _issue(6, ready + ["pr:open"]),
        _issue(7, ready + ["dependency:blocked"]),
        {"number": 8, "state": "open", "labels": "bad"},
        _issue(10, ready + ["type:epic"]),
        _issue(11, ready, body="Blocked by #12"),
        _issue(12, [], body="dependency"),
    ]
    assert select_ready_issue(issues) is None
    assert select_ready_issue(issues, only_number=11) is None


def test_rejects_german_dependency_phrases_on_open_issue():
    ready = ["agent:qwen-ready", "status:ready", "priority:p0"]
    blocker = _issue(999999, [])
    for body in ("Blockiert durch #999999", "Abhängig von #999999"):
        issue = _issue(20, ready, body="Kontext\n" + body + "\nEnde")
        assert select_ready_issue([issue, blocker]) is None
        assert select_ready_issue([issue, blocker], only_number=20) is None


def test_german_dependency_on_closed_issue_does_not_block():
    ready = ["agent:qwen-ready", "status:ready", "priority:p0"]
    closed = _issue(999999, [], state="closed")
    for body in ("Blockiert durch #999999", "Abhängig von #999999"):
        issue = _issue(20, ready, body=body)
        assert select_ready_issue([issue, closed]) is issue


def test_selects_only_ready_issue():
    ready = ["agent:qwen-ready", "status:ready", "priority:p1"]
    issue = _issue(9, ready, state="OPEN")
    assert select_ready_issue([{}, issue]) is issue


def test_builds_only_explicit_a3_issue_task():
    task = {"task_id": "github-issue-16", "issue_number": 16, "risk": "A3", "sandboxed": True,
            "objective": "Fix bounded bug", "allowed_paths": ["src/tim/example.py"],
            "tests": ["tests/test_example.py"]}
    issue = _issue(16, ["agent:qwen-ready", "status:ready", "priority:p1"],
                   body="Context\n```json TIM_QWEN_TASK_V1\n" + json.dumps(task) + "\n```\n")
    assert build_task(issue) == task
    for invalid in ({**task, "risk": "A1"}, {**task, "task_id": "github-issue-17"},
                    {**task, "allowed_paths": ["../secrets.py"]},
                    {**task, "allowed_paths": ["src/database/migrate.py"]},
                    {**task, "allowed_paths": ["src/local_first/sandbox_runner.py"]},
                    {**task, "allowed_paths": ["src/llm/ollama_client.py"]},
                    {**task, "allowed_paths": ["tests/conftest.py"]}):
        issue["body"] = "```json TIM_QWEN_TASK_V1\n" + json.dumps(invalid) + "\n```"
        with pytest.raises(ValueError):
            build_task(issue)
    issue["number"] = 1
    issue["body"] = "```json TIM_QWEN_TASK_V1\n" + json.dumps({**task,
        "task_id": "github-issue-1", "issue_number": True}) + "\n```"
    with pytest.raises(ValueError):
        build_task(issue)


def test_hard_label_is_selectable_and_marked():
    from src.local_first.github_issue_queue import is_hard_issue

    hard = {"number": 3, "state": "open", "labels": ["agent:qwen-hard", "status:ready", "priority:p1"]}
    assert select_ready_issue([hard]) is hard
    assert is_hard_issue(hard) is True
    assert is_hard_issue({**hard, "labels": ["agent:qwen-ready", "status:ready", "priority:p1"]}) is False
    assert select_ready_issue([{**hard, "labels": ["agent:qwen-hard", "priority:p1"]}]) is None


def test_lanes_split_hard_and_easy_issues():
    issues = [
        _issue(5, ["agent:qwen-ready", "status:ready", "priority:p0"]),
        _issue(6, ["agent:qwen-hard", "status:ready", "priority:p1"]),
        _issue(7, ["agent:qwen-ready", "agent:qwen-hard", "status:ready", "priority:p0"]),
    ]
    assert select_ready_issue(issues)["number"] == 5
    assert select_ready_issue(issues, lane="easy")["number"] == 5
    # An issue with both labels needs the server model, so only the hard lane takes it.
    assert select_ready_issue(issues, lane="hard")["number"] == 7
    assert select_ready_issue(issues, lane="easy", skip={5}) is None
    with pytest.raises(ValueError):
        select_ready_issue(issues, lane="fast")
