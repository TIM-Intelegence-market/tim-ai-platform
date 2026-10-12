from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_local_qwen_developer as developer


IMPLEMENTATION = "src/example.py"
TEST = "tests/test_example.py"


def response(*, include_test: bool = False, **metadata):
    patches = [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]
    if include_test:
        patches.append({"path": TEST, "content": "def test_value():\n    assert 2 == 2\n"})
    return {"patches": patches, **metadata}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("TIM_LOCAL_PATCH_SANDBOX", "1")
    monkeypatch.setenv("TIM_LIVE_TRADING", "0")
    monkeypatch.setenv("TIM_EXECUTION_ENABLED", "0")
    marker = tmp_path / ".tim/local-first/PATCH_SANDBOX_ALLOWED"
    marker.parent.mkdir(parents=True)
    marker.write_text("test sandbox only\n")
    (tmp_path / "src").mkdir()
    (tmp_path / IMPLEMENTATION).write_text("VALUE = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / TEST).write_text(
        "from pathlib import Path\n"
        "def test_value():\n"
        "    ns = {}\n"
        "    exec(Path('src/example.py').read_text(), ns)\n"
        "    assert ns['VALUE'] == 2\n"
    )
    return tmp_path


def run_fake(repo, monkeypatch, replies, *, task_changes=None, real_tests=False, available=True):
    task = {"task_id": "existing-feeder", "risk": "A3", "sandboxed": True,
            "objective": "Repair the existing task", "allowed_paths": [IMPLEMENTATION, TEST]}
    task.update(task_changes or {})
    task_path = repo / "input.json"
    task_path.write_text(json.dumps(task))
    prompts = []
    applied_tests = []

    class FakeOllama:
        def __init__(self, *args, **kwargs):
            assert kwargs["observation_only"] is False

        async def available(self):
            return available

        async def generate_json(self, prompt, **kwargs):
            prompts.append(json.loads(prompt))
            value = replies[len(prompts) - 1]
            if isinstance(value, Exception):
                raise value
            return value() if callable(value) else value

    def fake_tests(self, paths):
        applied_tests.append(paths)
        assert all((repo / path).is_file() for path in paths)
        return {"returncode": 0, "tests": paths}

    monkeypatch.setattr(developer, "OllamaClient", FakeOllama)
    if not real_tests:
        monkeypatch.setattr(developer.SafePatchExecutor, "_run_tests", fake_tests)
    args = developer.parser().parse_args([str(task_path), "--repo-root", str(repo)])
    exit_code = asyncio.run(developer.run(args))
    result = json.loads((repo / ".tim/local-first/developer-results/existing-feeder.json").read_text())
    return exit_code, result, prompts, applied_tests


def test_binds_stale_metadata_and_runs_real_required_test(sandbox, monkeypatch):
    proposal = response(proposal_id="../../escape", tests=["tests/wrong.py"], next_action="FIXED")
    proposal["patches"][0]["expected_sha256"] = "stale"
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [proposal], real_tests=True)
    assert code == 0 and result["status"] == "VERIFYING"
    assert result["model_calls"] == 1 and not result["hash_retry_used"]
    assert result["tests"]["returncode"] == 0
    assert result["tests"]["tests"] == [TEST]
    assert result["proposal_id"].startswith("tim-") and "/" not in result["proposal_id"]
    assert result["next_action"] == "LOCAL_REVIEW"
    assert {item["path"] for item in prompts[0]["response_schema"]["patches"]} == {
        "allowed/existing.py", "allowed/new_file.py"}
    assert result["changed"][0]["before_sha256"] == hashlib.sha256(b"VALUE = 1\n").hexdigest()
    assert (sandbox / IMPLEMENTATION).read_text() == "VALUE = 2\n"


@pytest.mark.parametrize("field", ["existing", "new", "test", "read_only"])
def test_snapshot_drift_stops_without_retry_or_apply(sandbox, monkeypatch, field):
    changes = {}
    target = sandbox / IMPLEMENTATION
    if field == "new":
        target.unlink()
    elif field == "test":
        target = sandbox / TEST
    elif field == "read_only":
        target = sandbox / "src/context.py"
        target.write_text("OLD = 1\n")
        changes["context_paths"] = ["src/context.py"]

    def concurrent_change():
        target.write_text("CONCURRENT = 7\n")
        return response()

    code, result, prompts, tests = run_fake(sandbox, monkeypatch, [concurrent_change], task_changes=changes)
    assert code == 2 and result["reason"].startswith("snapshot drift:")
    assert len(prompts) == 1 and not tests and not result["changed"]
    assert target.read_text() == "CONCURRENT = 7\n"
    assert not (sandbox / ".tim/local-first/patch-backups").exists()


def test_missing_new_test_repaired_before_any_write(sandbox, monkeypatch):
    (sandbox / TEST).unlink()

    def repaired():
        assert (sandbox / IMPLEMENTATION).read_text() == "VALUE = 1\n"
        assert not (sandbox / ".tim/local-first/patch-backups").exists()
        return response(include_test=True)

    code, result, prompts, tests = run_fake(sandbox, monkeypatch, [response(), repaired])
    assert code == 0 and result["model_calls"] == 2 and result["missing_test_retry_used"]
    assert prompts[1]["required_new_test_patches"] == [TEST]
    assert "include required new test" in prompts[1]["repair_same_task"]
    assert tests == [[TEST]]


@pytest.mark.parametrize("replies", [
    [json.JSONDecodeError("truncated", "{", 1), {"patches": []}],
    [response(), response()],
    [None, []],
])
def test_all_repair_classes_share_two_call_ceiling(sandbox, monkeypatch, replies):
    (sandbox / TEST).unlink()
    code, result, prompts, tests = run_fake(sandbox, monkeypatch, replies)
    assert code == 2 and result["reason"].startswith("QWEN_REPAIR_EXHAUSTED:")
    assert len(prompts) == result["model_calls"] == 2
    assert not tests and not result["changed"]
    assert (sandbox / IMPLEMENTATION).read_text() == "VALUE = 1\n"
    assert result["next_action"] == "REPAIR_AND_RESUME_SAME_TASK_DO_NOT_CREATE_SUBTASK"


def test_json_decode_error_can_repair_same_task(sandbox, monkeypatch):
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [json.JSONDecodeError("bad", "{", 1), response()])
    assert code == 0 and result["model_calls"] == 2
    assert prompts[0]["task"]["task_id"] == prompts[1]["task"]["task_id"] == result["task_id"]


@pytest.mark.parametrize("error", [TimeoutError(), OSError(), ValueError("wrong provider type")])
def test_provider_errors_do_not_retry(sandbox, monkeypatch, error):
    code, result, prompts, tests = run_fake(sandbox, monkeypatch, [error])
    assert code == 2 and result["reason"] == f"QWEN_ERROR:{type(error).__name__}"
    assert len(prompts) == 1 and not tests


def test_codex_patch_fallback_after_qwen_timeout_uses_same_safety_gate(sandbox, monkeypatch):
    from src.local_first import codex_patch_fallback

    monkeypatch.setenv("TIM_CODEX_PATCH_FALLBACK", "1")
    prompts = []

    def codex_proposal(prompt):
        prompts.append(json.loads(prompt))
        assert (sandbox / IMPLEMENTATION).read_text() == "VALUE = 1\n"
        return response()

    monkeypatch.setattr(codex_patch_fallback, "propose", codex_proposal)
    code, result, _, tests = run_fake(sandbox, monkeypatch, [TimeoutError()])
    assert code == 0 and result["status"] == "VERIFYING"
    assert result["model_calls"] == 1 and result["codex_fallback_calls"] == 1
    assert result["fallback_provider"] == "CODEX_CLI"
    assert result["qwen_blocker_reason"] == "QWEN_ERROR:TimeoutError"
    assert tests == [[TEST]] and len(prompts) == 1
    assert (sandbox / IMPLEMENTATION).read_text() == "VALUE = 2\n"


def test_codex_patch_fallback_cannot_expand_paths(sandbox, monkeypatch):
    from src.local_first import codex_patch_fallback

    monkeypatch.setenv("TIM_CODEX_PATCH_FALLBACK", "1")
    monkeypatch.setattr(codex_patch_fallback, "propose", lambda _: {
        "patches": [{"path": "src/other.py", "content": "VALUE = 2\n"}]})
    code, result, _, tests = run_fake(sandbox, monkeypatch, [TimeoutError()])
    assert code == 2 and result["reason"] == "QWEN_ERROR:TimeoutError"
    assert result["codex_fallback_error"] == "ContractError"
    assert result["codex_fallback_calls"] == 1 and not tests
    assert not (sandbox / "src/other.py").exists()


def test_claude_patch_fallback_runs_when_codex_fails(sandbox, monkeypatch):
    from src.local_first import claude_cli_fallback, codex_patch_fallback

    monkeypatch.setenv("TIM_CODEX_PATCH_FALLBACK", "1")
    monkeypatch.setenv("TIM_CLAUDE_PATCH_FALLBACK", "1")
    monkeypatch.setattr(codex_patch_fallback, "propose",
                        lambda _: (_ for _ in ()).throw(RuntimeError("usage limit")))
    monkeypatch.setattr(claude_cli_fallback, "propose", lambda _: response())
    code, result, _, tests = run_fake(sandbox, monkeypatch, [TimeoutError()])
    assert code == 0 and result["status"] == "VERIFYING"
    assert result["codex_fallback_calls"] == 1 and result["claude_fallback_calls"] == 1
    assert result["codex_fallback_error"] == "RuntimeError"
    assert result["fallback_provider"] == "CLAUDE_CLI"
    assert tests == [[TEST]]
    assert (sandbox / IMPLEMENTATION).read_text() == "VALUE = 2\n"


def test_claude_patch_fallback_cannot_expand_paths(sandbox, monkeypatch):
    from src.local_first import claude_cli_fallback

    monkeypatch.setenv("TIM_CLAUDE_PATCH_FALLBACK", "1")
    monkeypatch.setattr(claude_cli_fallback, "propose", lambda _: {
        "patches": [{"path": "src/other.py", "content": "VALUE = 2\n"}]})
    code, result, _, tests = run_fake(sandbox, monkeypatch, [TimeoutError()])
    assert code == 2 and result["reason"] == "QWEN_ERROR:TimeoutError"
    assert result["claude_fallback_error"] == "ContractError"
    assert result["codex_fallback_calls"] == 0 and result["claude_fallback_calls"] == 1
    assert not tests and not (sandbox / "src/other.py").exists()


def test_safety_rejection_does_not_retry(sandbox, monkeypatch):
    proposal = response()
    proposal["patches"][0]["content"] = "import os\nos.system('anything')\n"
    code, result, prompts, tests = run_fake(sandbox, monkeypatch, [proposal])
    assert code == 2 and "forbidden code intent" in result["reason"]
    assert len(prompts) == 1 and not tests
    assert (sandbox / IMPLEMENTATION).read_text() == "VALUE = 1\n"


@pytest.mark.parametrize("bad_path", ["src/other.py", "src/../example.py", "/tmp/example.py", "src\\example.py"])
def test_model_cannot_expand_or_alias_allowed_paths(sandbox, monkeypatch, bad_path):
    proposal = {"patches": [{"path": bad_path, "content": "VALUE = 2\n"}]}
    code, result, prompts, tests = run_fake(sandbox, monkeypatch, [proposal])
    assert code == 2 and "not allowlisted" in result["reason"]
    assert len(prompts) == 1 and not tests


@pytest.mark.parametrize("test_paths", [[], "tests/test_example.py", None, [TEST, TEST],
    ["tests/../other.py"], ["src/example.py"], ["tests\\test_example.py"], [f"tests/t{i}.py" for i in range(9)]])
def test_invalid_explicit_tests_do_not_fall_back_or_call_model(sandbox, monkeypatch, test_paths):
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [], task_changes={"tests": test_paths})
    assert code == 2 and not prompts and result["model_calls"] == 0
    assert not result["changed"]


def test_explicit_read_only_test_contract(sandbox, monkeypatch):
    code, result, _, tests = run_fake(sandbox, monkeypatch, [response()],
        task_changes={"allowed_paths": [IMPLEMENTATION], "tests": [TEST]})
    assert code == 0 and tests == [[TEST]] and result["required_tests"] == [TEST]


def test_missing_read_only_required_test_blocks_before_model(sandbox, monkeypatch):
    (sandbox / TEST).unlink()
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [],
        task_changes={"allowed_paths": [IMPLEMENTATION], "tests": [TEST]})
    assert code == 2 and "not writable" in result["reason"] and not prompts


@pytest.mark.parametrize("relative", [IMPLEMENTATION, TEST])
def test_symlink_contract_path_blocks_before_model(sandbox, monkeypatch, relative):
    target = sandbox / relative
    target.unlink()
    target.symlink_to(sandbox.parent / "outside.py")
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [])
    assert code == 2 and "unsafe contract path" in result["reason"] and not prompts


def test_allowed_files_cannot_be_displaced_by_read_only_context(sandbox):
    task = {"allowed_paths": [IMPLEMENTATION, TEST],
            "context_paths": [f"src/read_only_{i}.py" for i in range(12)]}
    contract = developer._build_contract(sandbox, task)
    assert [x["path"] for x in contract["context"]][:2] == [IMPLEMENTATION, TEST]
    assert len(contract["context"]) == developer.MAX_CONTEXT_FILES


@pytest.mark.parametrize("content", ["x" * (developer.MAX_WRITABLE_CONTEXT_CHARS + 1), "password = \"credential\"\n", "\udcff"])
def test_incomplete_writable_context_blocks_before_model(sandbox, monkeypatch, content):
    (sandbox / IMPLEMENTATION).write_bytes(content.encode("utf-8", errors="surrogateescape"))
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [])
    assert code == 2 and "truncated, redacted or not UTF-8" in result["reason"] and not prompts


def test_hash_and_content_describe_same_read(sandbox, monkeypatch):
    original = Path.read_bytes

    def racing_read(path):
        raw = original(path)
        if path == sandbox / IMPLEMENTATION:
            path.write_text("CONCURRENT = 7\n")
        return raw

    monkeypatch.setattr(Path, "read_bytes", racing_read)
    context = developer._safe_context(sandbox, [IMPLEMENTATION])
    assert context[0]["content"] == "VALUE = 1\n"
    assert context[0]["sha256"] == hashlib.sha256(b"VALUE = 1\n").hexdigest()
    with pytest.raises(developer.ContractError, match="snapshot drift"):
        developer._check_snapshot(sandbox, {"context": context})


@pytest.mark.parametrize("proposal", [None, [], {"patches": []}, {"patches": [None]},
    {"patches": [{"path": IMPLEMENTATION, "content": None}]},
    {"patches": [{"path": IMPLEMENTATION, "content": "x"}] * 2},
    {"patches": [{"path": IMPLEMENTATION, "content": "x"}] * 7},
])
def test_invalid_content_envelopes_never_bind(sandbox, proposal):
    contract = developer._build_contract(sandbox, {"allowed_paths": [IMPLEMENTATION, TEST]})
    with pytest.raises(developer.ProposalError):
        developer._bind_proposal(proposal, contract, "tim-test")


def test_sandbox_gate_prevents_model_work(sandbox, monkeypatch):
    monkeypatch.delenv("TIM_LOCAL_PATCH_SANDBOX")
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [])
    assert code == 2 and result["reason"] == "sandbox env gate is closed" and not prompts


def test_outage_writes_fresh_durable_result(sandbox, monkeypatch):
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [], available=False)
    assert code == 2 and result["reason"] == "LOCAL_QWEN_UNAVAILABLE" and not prompts
    assert (sandbox / ".tim/local-first/blockers/requests/existing-feeder.json").exists()


def test_invalid_utf8_content_uses_shared_repair(sandbox, monkeypatch):
    proposal = response()
    proposal["patches"][0]["content"] = "\ud800"
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [proposal, response()])
    assert code == 0 and result["model_calls"] == 2
    assert "valid UTF-8" in prompts[1]["repair_same_task"]


def test_impossible_new_test_count_blocks_before_model(sandbox, monkeypatch):
    paths = [f"tests/test_new_{i}.py" for i in range(7)]
    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [],
        task_changes={"allowed_paths": paths})
    assert code == 2 and "exceed the patch budget" in result["reason"] and not prompts


def test_snapshot_drift_before_repair_prevents_second_call(sandbox, monkeypatch):
    def malformed_after_drift():
        (sandbox / IMPLEMENTATION).write_text("CONCURRENT = 7\n")
        raise json.JSONDecodeError("bad", "{", 1)

    code, result, prompts, _ = run_fake(sandbox, monkeypatch, [malformed_after_drift])
    assert code == 2 and result["reason"].startswith("snapshot drift:") and len(prompts) == 1
    assert (sandbox / IMPLEMENTATION).read_text() == "CONCURRENT = 7\n"


def test_prompt_requires_offline_deterministic_unit_tests() -> None:
    import json
    from scripts import run_local_qwen_developer as developer

    task = {
        "task_id": "offline-test-policy",
        "risk": "A3",
        "sandboxed": True,
        "objective": "Implement a safe GitHub feeder",
    }
    contract = {
        "allowed_paths": [
            "src/local_first/github_feeder.py",
            "tests/test_local_first_github_feeder.py",
        ],
        "required_outputs": [],
        "tests": ["tests/test_local_first_github_feeder.py"],
        "context": [],
    }

    payload = json.loads(developer._prompt(task, contract))
    rules = " ".join(payload["hard_rules"]).lower()

    assert "deterministic and offline" in rules
    assert "never call real github" in rules
    assert "never disable tls" in rules



def test_writable_file_can_exceed_readonly_context_budget(
    sandbox,
):
    content = (
        "VALUE = 1\n"
        + "x" * (developer.MAX_CONTEXT_CHARS + 100)
    )

    assert (
        len(content)
        < developer.MAX_WRITABLE_CONTEXT_CHARS
    )

    (sandbox / IMPLEMENTATION).write_text(
        content,
        encoding="utf-8",
    )

    contract = developer._build_contract(
        sandbox,
        {
            "allowed_paths": [
                IMPLEMENTATION,
                TEST,
            ]
        },
    )

    item = next(
        entry
        for entry in contract["context"]
        if entry["path"] == IMPLEMENTATION
    )

    assert item["complete"] is True
    assert item["content"] == content


def test_readonly_context_keeps_small_budget(
    sandbox,
):
    relative = "src/large_read_only.py"

    content = (
        "x"
        * (developer.MAX_CONTEXT_CHARS + 100)
    )

    (sandbox / relative).write_text(
        content,
        encoding="utf-8",
    )

    contract = developer._build_contract(
        sandbox,
        {
            "allowed_paths": [
                IMPLEMENTATION,
                TEST,
            ],
            "context_paths": [relative],
        },
    )

    item = next(
        entry
        for entry in contract["context"]
        if entry["path"] == relative
    )

    assert item["complete"] is False

    assert (
        len(item["content"])
        == developer.MAX_CONTEXT_CHARS
    )
