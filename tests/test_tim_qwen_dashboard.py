import importlib.util
import json
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("tim_qwen_dashboard", Path(__file__).parents[1] / "scripts/tim_qwen_dashboard.py")
dashboard = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(dashboard)


def test_snapshot_is_read_only_and_reports_safety(tmp_path: Path) -> None:
    repo, qwen = tmp_path / "tim", tmp_path / "qwen"
    (repo / "TIM_MASTER_PROMPTS").mkdir(parents=True)
    (qwen / ".tim/local-first/developer-results").mkdir(parents=True)
    (qwen / ".tim/local-first/developer-results/result.json").write_text(json.dumps({"task_id": "t1", "status": "BLOCKED", "tests": {"returncode": 1}}))
    result = dashboard.snapshot(repo, qwen, "http://127.0.0.1:1")
    assert result["safety_gates"]["live_trading"] == "DISABLED"
    assert result["safety_gates"]["github_writes"] == "FORBIDDEN_WITHOUT_EXPLICIT_APPROVAL"
    assert result["repair"]["last_status"] == "BLOCKED"
    page = dashboard._page(result)
    assert "TIM QWEN-DASHBOARD" in page
    assert "no trading or execution controls" in page
    assert "textContent" in page


def test_enqueue_requires_explicit_safe_contract(tmp_path: Path) -> None:
    qwen = tmp_path / "qwen"; task = tmp_path / "task.json"
    task.write_text(json.dumps({"task_id": "safe_1", "risk": "A3", "sandboxed": True, "allowed_paths": ["tests/x.py"], "tests": ["tests/x.py"]}))
    target = Path(dashboard.enqueue(qwen, task))
    assert target.is_file()
    assert json.loads(target.read_text())["task_id"] == "safe_1"


def test_enqueue_rejects_unsafe_task(tmp_path: Path) -> None:
    task = tmp_path / "task.json"; task.write_text("{}")
    try: dashboard.enqueue(tmp_path / "qwen", task)
    except ValueError as error: assert "risk=A3" in str(error)
    else: raise AssertionError("unsafe task was accepted")


def test_log_tail_is_bounded_and_redacts_secrets(tmp_path: Path) -> None:
    path = tmp_path / "worker.log"
    path.write_text("ok\ntoken=should-not-appear\n")
    report = dashboard._log_tail(path)
    assert report["available"] is True
    assert "should-not-appear" not in "\n".join(report["tail"])
