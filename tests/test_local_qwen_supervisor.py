from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import run_local_qwen_build_queue as supervisor


def test_selected_tasks_respects_pilot_id(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "pilot.json").write_text("{}")
    (inbox / "other.json").write_text("{}")
    assert [p.name for p in supervisor._selected_tasks(inbox, "pilot")] == ["pilot.json"]
    assert [p.name for p in supervisor._selected_tasks(inbox, "missing")] == []


def _task() -> dict:
    return {
        "task_id": "task-1",
        "risk": "A3",
        "sandboxed": True,
        "objective": "Repair the existing task",
        "allowed_paths": ["src/example.py", "tests/test_example.py"],
        "tests": ["tests/test_example.py"],
    }


def _verifying_result() -> dict:
    return {
        "status": "VERIFYING",
        "proposal_id": "tim-test",
        "changed": [
            {
                "path": "src/example.py",
                "before_sha256": "before",
                "after_sha256": "after",
            }
        ],
        "tests": {
            "returncode": 0,
            "tests": ["tests/test_example.py"],
            "stdout": "1 passed",
            "stderr": "",
            "python": "python",
        },
        "rollback": False,
        "reason": None,
        "authority": "LOCAL_SAFETY_GATES",
        "required_outputs": [],
        "required_tests": ["tests/test_example.py"],
        "next_action": "LOCAL_REVIEW",
    }


def _sandbox(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TIM_LOCAL_PATCH_SANDBOX", "1")
    monkeypatch.setenv("TIM_BLOCKER_AUTO_WAIT", "0")
    marker = tmp_path / ".tim/local-first/PATCH_SANDBOX_ALLOWED"
    marker.parent.mkdir(parents=True)
    marker.write_text("sandbox-only\n", encoding="utf-8")
    inbox = tmp_path / ".tim/local-first/developer-inbox"
    inbox.mkdir(parents=True)
    (inbox / "task-1.json").write_text(json.dumps(_task()), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/example.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_example.py").write_text("def test_value():\n    assert True\n", encoding="utf-8")
    return tmp_path


def test_acceptance_gate_promotes_verifying_to_fixed(tmp_path: Path) -> None:
    repo = tmp_path
    state = repo / ".tim/local-first"
    (repo / "src").mkdir()
    (repo / "src/example.py").write_text("VALUE = 2\n", encoding="utf-8")
    evidence = supervisor._acceptance_gate(repo, state, _task(), _verifying_result())
    assert evidence["passed"] is True
    assert evidence["status"] == "FIXED"
    assert evidence["authority"] == "TIM_LOCAL_SUPERVISOR"
    assert evidence["live_trading"] == "DISABLED"
    durable = json.loads((state / "acceptance-results/task-1.json").read_text(encoding="utf-8"))
    assert durable["evidence_sha256"] == evidence["evidence_sha256"]


def test_acceptance_gate_requires_sandboxed_tests_when_configured(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/example.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setenv("TIM_TEST_SANDBOX", "required")
    evidence = supervisor._acceptance_gate(tmp_path, tmp_path / ".tim/local-first", _task(), _verifying_result())
    assert evidence["passed"] is False and evidence["repairable"] is False
    assert "test_sandbox_enforced" in evidence["failed_checks"]
    result = _verifying_result()
    result["tests"]["sandbox"] = "seatbelt"
    evidence = supervisor._acceptance_gate(tmp_path, tmp_path / ".tim/local-first", _task(), result)
    assert evidence["passed"] is True and evidence["tests"]["sandbox"] == "seatbelt"


def test_acceptance_gate_missing_required_output_is_repairable(tmp_path: Path) -> None:
    result = _verifying_result()
    result["required_outputs"] = ["src/required.py"]
    evidence = supervisor._acceptance_gate(tmp_path, tmp_path / ".tim/local-first", _task(), result)
    assert evidence["passed"] is False
    assert evidence["repairable"] is True
    assert "required_outputs_exist" in evidence["failed_checks"]


def test_single_supervisor_lock_rejects_second_holder(tmp_path: Path) -> None:
    state = tmp_path / ".tim/local-first"
    first = supervisor._acquire_supervisor_lock(state)
    try:
        assert first is not None
        second = supervisor._acquire_supervisor_lock(state)
        assert second is None
    finally:
        supervisor._release_supervisor_lock(first)
    third = supervisor._acquire_supervisor_lock(state)
    try:
        assert third is not None
    finally:
        supervisor._release_supervisor_lock(third)


def test_blocker_class_keeps_safety_failures_hard() -> None:
    assert supervisor._blocker_class({"reason": "snapshot drift: src/example.py"}) == "HARD_BLOCKER"
    assert supervisor._blocker_class({"reason": "forbidden code intent: src/example.py"}) == "HARD_BLOCKER"
    assert supervisor._blocker_class({"reason": "QWEN_REPAIR_EXHAUSTED: invalid JSON"}) == "LOCAL_REPAIRABLE"
    assert supervisor._blocker_class({"reason": "verification failed; rolled back"}) == "LOCAL_REPAIRABLE"


def test_main_closes_only_after_acceptance_gate(tmp_path: Path, monkeypatch) -> None:
    repo = _sandbox(tmp_path, monkeypatch)
    result_path = repo / ".tim/local-first/developer-results/task-1.json"

    def fake_run(command, **kwargs):
        if command[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(_verifying_result()), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    assert supervisor.main() == 0
    assert not (repo / ".tim/local-first/developer-inbox/task-1.json").exists()
    assert (repo / ".tim/local-first/developer-processed/task-1.json").exists()
    acceptance = json.loads((repo / ".tim/local-first/acceptance-results/task-1.json").read_text())
    assert acceptance["status"] == "FIXED"
    assert acceptance["passed"] is True


def test_main_retries_local_failure_then_accepts_same_task(tmp_path: Path, monkeypatch) -> None:
    repo = _sandbox(tmp_path, monkeypatch)
    result_path = repo / ".tim/local-first/developer-results/task-1.json"
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        if command[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
        calls += 1
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if calls == 1:
            result = {
                "status": "BLOCKED",
                "reason": "QWEN_REPAIR_EXHAUSTED: invalid JSON",
                "tests": {},
                "next_action": "REPAIR_AND_RESUME_SAME_TASK_DO_NOT_CREATE_SUBTASK",
            }
            code = 2
        else:
            result = _verifying_result()
            code = 0
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return SimpleNamespace(returncode=code, stdout="", stderr="")

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    monkeypatch.setattr(supervisor.time, "sleep", lambda _seconds: None)
    assert supervisor.main() == 0
    assert calls == 2
    processed = json.loads((repo / ".tim/local-first/developer-processed/task-1.json").read_text())
    assert processed["supervisor_repair_cycle"] == 1
    assert "QWEN_REPAIR_EXHAUSTED" in processed["supervisor_repair_reason"]


def test_main_does_not_retry_snapshot_drift(tmp_path: Path, monkeypatch) -> None:
    repo = _sandbox(tmp_path, monkeypatch)
    result_path = repo / ".tim/local-first/developer-results/task-1.json"
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps({
            "status": "BLOCKED",
            "reason": "snapshot drift: src/example.py; resume same task with fresh context",
            "tests": {},
            "next_action": "REPAIR_AND_RESUME_SAME_TASK_DO_NOT_CREATE_SUBTASK",
        }), encoding="utf-8")
        return SimpleNamespace(returncode=2, stdout="", stderr="")

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    monkeypatch.setattr(supervisor, "_publish_blocker", lambda *args, **kwargs: False)
    assert supervisor.main() == 2
    assert calls == 1


def test_repair_feedback_preserves_pytest_stdout_for_qwen() -> None:
    feedback = supervisor._repair_feedback({
        "reason": "verification failed; rolled back",
        "tests": {
            "returncode": 1,
            "stderr": "",
            "stdout": "FAILED test_fetch_issues - SSL: CERTIFICATE_VERIFY_FAILED",
        },
    })
    assert "CERTIFICATE_VERIFY_FAILED" in feedback
    assert "Targeted test stdout:" in feedback



def test_main_honors_persisted_repair_budget_across_restarts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _sandbox(
        tmp_path,
        monkeypatch,
    )

    task_path = (
        repo
        / ".tim/local-first/developer-inbox"
        / "task-1.json"
    )

    task = json.loads(
        task_path.read_text(
            encoding="utf-8"
        )
    )

    task["supervisor_repair_cycle"] = 2

    task_path.write_text(
        json.dumps(task),
        encoding="utf-8",
    )

    result_path = (
        repo
        / ".tim/local-first/developer-results"
        / "task-1.json"
    )

    result_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result_path.write_text(
        json.dumps(
            {
                "status": "BLOCKED",
                "reason":
                    "verification failed; rolled back",
                "tests": {
                    "returncode": 1,
                    "stdout": "failed",
                    "stderr": "",
                },
                "next_action":
                    "REPAIR_AND_RESUME_SAME_TASK_DO_NOT_CREATE_SUBTASK",
            }
        ),
        encoding="utf-8",
    )

    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=2,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        supervisor.subprocess,
        "run",
        fake_run,
    )

    monkeypatch.setattr(
        supervisor,
        "_publish_blocker",
        lambda *args, **kwargs: False,
    )

    assert supervisor.main() == 2

    assert calls == 0

    persisted = json.loads(
        task_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        persisted["supervisor_repair_cycle"]
        == 2
    )



def test_main_rejects_invalid_resolution_after_budget_exhaustion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _sandbox(tmp_path, monkeypatch)
    state = repo / ".tim/local-first"
    task_path = state / "developer-inbox/task-1.json"

    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["supervisor_repair_cycle"] = 2
    task_path.write_text(json.dumps(task), encoding="utf-8")

    result_path = state / "developer-results/task-1.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps({
            "status": "BLOCKED",
            "reason": "verification failed; rolled back",
            "tests": {
                "returncode": 1,
                "stdout": "failed",
                "stderr": "",
            },
            "next_action":
                "REPAIR_AND_RESUME_SAME_TASK_DO_NOT_CREATE_SUBTASK",
        }),
        encoding="utf-8",
    )

    resolution = state / "blockers/resolutions/task-1.json"
    resolution.parent.mkdir(parents=True, exist_ok=True)
    resolution.write_text(
        json.dumps({
            "kind": "BLOCKER_RESOLVED",
            "task_id": "task-1",
            "authority": "NOT_LOCAL_SAFETY_GATES",
        }),
        encoding="utf-8",
    )

    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            returncode=2,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    monkeypatch.setattr(
        supervisor,
        "_publish_blocker",
        lambda *args, **kwargs: False,
    )

    assert supervisor.main() == 2
    assert calls == 0
    assert task_path.exists()
    assert not (
        state / "developer-processed/task-1.json"
    ).exists()

    persisted = json.loads(
        task_path.read_text(encoding="utf-8")
    )
    assert persisted["supervisor_repair_cycle"] == 2


def test_main_resumes_same_task_once_with_valid_external_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _sandbox(tmp_path, monkeypatch)
    state = repo / ".tim/local-first"
    task_path = state / "developer-inbox/task-1.json"

    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["supervisor_repair_cycle"] = 2
    task_path.write_text(json.dumps(task), encoding="utf-8")

    result_path = state / "developer-results/task-1.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps({
            "status": "BLOCKED",
            "reason": "verification failed; rolled back",
            "tests": {
                "returncode": 1,
                "stdout": "failed",
                "stderr": "",
            },
            "next_action":
                "REPAIR_AND_RESUME_SAME_TASK_DO_NOT_CREATE_SUBTASK",
        }),
        encoding="utf-8",
    )

    resolution = state / "blockers/resolutions/task-1.json"
    resolution.parent.mkdir(parents=True, exist_ok=True)
    resolution.write_text(
        json.dumps({
            "schema_version": 1,
            "kind": "BLOCKER_RESOLVED",
            "task_id": "task-1",
            "resolution_status": "RESOLVED_FOR_LOCAL_RETRY",
            "root_cause": "test blocker",
            "repair": "retry same task",
            "next_action": "retry same task",
            "authority": "LOCAL_SAFETY_GATES",
        }),
        encoding="utf-8",
    )

    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls

        if command[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(
                returncode=0,
                stdout="abc123\n",
                stderr="",
            )

        calls += 1

        result = _verifying_result()
        result["external_resolution_used"] = True

        result_path.write_text(
            json.dumps(result),
            encoding="utf-8",
        )

        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)

    assert supervisor.main() == 0
    assert calls == 1

    assert not task_path.exists()

    processed_path = (
        state / "developer-processed/task-1.json"
    )
    assert processed_path.exists()

    processed = json.loads(
        processed_path.read_text(encoding="utf-8")
    )

    # Historical retry evidence must not be reset.
    assert processed["supervisor_repair_cycle"] == 2

    acceptance = json.loads(
        (
            state
            / "acceptance-results/task-1.json"
        ).read_text(encoding="utf-8")
    )
    assert acceptance["passed"] is True
    assert acceptance["status"] == "FIXED"

    assert not resolution.exists()

    consumed = list(
        (state / "blockers/resolutions-consumed").glob(
            "task-1.*.json"
        )
    )
    assert len(consumed) == 1
