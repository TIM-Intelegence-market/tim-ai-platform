from pathlib import Path
import asyncio
import json
import os

import pytest

from src.local_first.provider_broker import ProviderBroker, SafetyGate
from src.local_first.runtime import BlockerMailbox, LocalTask, LocalPrimaryWorker, RepairRecipeStore

def test_provider_broker_init(tmp_path: Path):
    broker = ProviderBroker(tmp_path)
    assert isinstance(broker.safety_gate, SafetyGate)


def _setup(tmp_path: Path) -> tuple[ProviderBroker, Path]:
    key = tmp_path / "worker.key"
    key.write_text("test-only-key", encoding="utf-8")
    os.chmod(key, 0o600)
    request = BlockerMailbox(tmp_path / "blockers").create_request(
        LocalTask("task-1", "Inspect /private/work/file.py", "Review blocker"),
        "token=super-secret\nRAW LOG CONTENT", [{"stderr": "raw log"}],
    )
    return ProviderBroker(tmp_path, key_path=key), request


def test_requires_chatgpt_record_and_exact_approval(tmp_path: Path) -> None:
    broker, request = _setup(tmp_path)
    assert broker.status("task-1")["state"] == "WAITING_FOR_CHATGPT"
    digest = broker.status("task-1")["request_sha256"]
    with pytest.raises(ValueError):
        broker.approve("task-1", digest)
    broker.mark_chatgpt_unavailable("task-1", "ChatGPT explicitly unavailable")
    assert broker.status("task-1")["state"] == "WAITING_FOR_APPROVAL"
    with pytest.raises(ValueError):
        broker.approve("task-1", "0" * 64)
    broker.approve("task-1", digest)
    assert broker.status("task-1")["state"] == "ROUTING"
    request.write_text(request.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert broker.status("task-1")["state"] == "WAITING_FOR_CHATGPT"


def test_automatic_blocker_routes_without_manual_approval_once(tmp_path: Path, monkeypatch) -> None:
    broker, _ = _setup(tmp_path)
    broker = ProviderBroker(tmp_path, key_path=broker.key_path, automatic=True)
    calls = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, *_):
            return b'{"choices":[{"message":{"content":"Check configuration locally"}}]}'

    def fake_urlopen(request, timeout):
        calls.append(request)
        return Response()

    monkeypatch.setattr("src.local_first.provider_broker.urlopen", fake_urlopen)
    assert broker.status("task-1")["state"] == "ROUTING"
    assert broker.route("task-1")["state"] == "RESOLVED"
    assert len(calls) == 1
    with pytest.raises(ValueError):
        broker.route("task-1")
    assert len(calls) == 1


def test_automatic_blocker_asks_codex_first(tmp_path: Path, monkeypatch) -> None:
    broker, _ = _setup(tmp_path)
    broker = ProviderBroker(tmp_path, key_path=broker.key_path, automatic=True)
    monkeypatch.setenv("TIM_CODEX_BLOCKER_ADVISOR", "1")
    monkeypatch.setattr(broker, "_codex_advice", lambda outbound: "Check the local test setup before retrying Qwen")
    monkeypatch.setattr("src.local_first.provider_broker.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Claude should not run")))
    assert broker.route("task-1")["state"] == "RESOLVED"
    payload = json.loads((tmp_path / "blockers/resolutions/task-1.json").read_text())
    assert payload["provider"] == "CODEX_CLI"
    assert payload["authority"] == "ADVISORY_ONLY"
    (tmp_path / "blockers/resolutions/task-1.json").unlink()
    request = tmp_path / "blockers/requests/task-1.json"
    request.write_text(request.read_text() + " ")
    assert broker.route("task-1")["state"] == "ROUTER_FAILED"
    assert not (tmp_path / "blockers/resolutions/task-1.json").exists()


def test_codex_failure_falls_back_to_omniroute(tmp_path: Path, monkeypatch) -> None:
    broker, _ = _setup(tmp_path)
    broker = ProviderBroker(tmp_path, key_path=broker.key_path, automatic=True)
    monkeypatch.setenv("TIM_CODEX_BLOCKER_ADVISOR", "1")
    monkeypatch.setattr(broker, "_codex_advice", lambda outbound: (_ for _ in ()).throw(RuntimeError("offline")))

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, *_):
            return b'{"choices":[{"message":{"content":"Check configuration locally"}}]}'

    monkeypatch.setattr("src.local_first.provider_broker.urlopen", lambda *_args, **_kwargs: Response())
    assert broker.route("task-1")["state"] == "RESOLVED"
    payload = json.loads((tmp_path / "blockers/resolutions/task-1.json").read_text())
    assert payload["provider"] == "OMNIROUTE"
    assert (tmp_path / "blockers/codex-failed/task-1.json").exists()


def test_codex_failure_asks_claude_before_omniroute(tmp_path: Path, monkeypatch) -> None:
    broker, _ = _setup(tmp_path)
    broker = ProviderBroker(tmp_path, key_path=broker.key_path, automatic=True)
    monkeypatch.setenv("TIM_CODEX_BLOCKER_ADVISOR", "1")
    monkeypatch.setenv("TIM_CLAUDE_BLOCKER_ADVISOR", "1")
    monkeypatch.setattr(broker, "_codex_advice", lambda outbound: (_ for _ in ()).throw(RuntimeError("usage limit")))
    from src.local_first import claude_cli_fallback
    monkeypatch.setattr(claude_cli_fallback, "advise",
                        lambda outbound: "Fixture missing in /Users/x/repo/tests; token=abc")
    monkeypatch.setattr("src.local_first.provider_broker.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("OmniRoute should not run")))
    assert broker.route("task-1")["state"] == "RESOLVED"
    payload = json.loads((tmp_path / "blockers/resolutions/task-1.json").read_text())
    assert payload["provider"] == "CLAUDE_CLI"
    assert payload["authority"] == "ADVISORY_ONLY"
    assert "abc" not in payload["proposal"]["diagnosis"] and "/Users" not in payload["proposal"]["diagnosis"]
    assert (tmp_path / "blockers/codex-failed/task-1.json").exists()


def test_claude_failure_still_falls_back_to_omniroute(tmp_path: Path, monkeypatch) -> None:
    broker, _ = _setup(tmp_path)
    broker = ProviderBroker(tmp_path, key_path=broker.key_path, automatic=True)
    monkeypatch.setenv("TIM_CLAUDE_BLOCKER_ADVISOR", "1")
    monkeypatch.setattr(broker, "_claude_advice", lambda outbound: (_ for _ in ()).throw(RuntimeError("offline")))

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, *_):
            return b'{"choices":[{"message":{"content":"Check configuration locally"}}]}'

    monkeypatch.setattr("src.local_first.provider_broker.urlopen", lambda *_args, **_kwargs: Response())
    assert broker.route("task-1")["state"] == "RESOLVED"
    payload = json.loads((tmp_path / "blockers/resolutions/task-1.json").read_text())
    assert payload["provider"] == "OMNIROUTE"
    assert (tmp_path / "blockers/claude-failed/task-1.json").exists()


def test_codex_advisor_receives_no_github_environment(tmp_path: Path, monkeypatch) -> None:
    broker = ProviderBroker(tmp_path)
    binary = tmp_path / "codex"
    binary.write_text("test executable", encoding="utf-8")
    monkeypatch.setenv("TIM_CODEX_BIN", str(binary))
    monkeypatch.setenv("GH_CONFIG_DIR", "/private/github-config")
    monkeypatch.setenv("GH_TOKEN", "test-only-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-provider-secret")
    monkeypatch.setenv("TIM_QWEN_WORKER_LOGIN", "worker")

    class Result:
        returncode = 0

    def fake_run(args, **kwargs):
        assert args[args.index("--sandbox") + 1] == "read-only"
        assert "GH_CONFIG_DIR" not in kwargs["env"]
        assert "GH_TOKEN" not in kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        assert "TIM_QWEN_WORKER_LOGIN" not in kwargs["env"]
        Path(args[args.index("--output-last-message") + 1]).write_text("Inspect local evidence")
        return Result()

    monkeypatch.setattr("src.local_first.provider_broker.subprocess.run", fake_run)
    assert broker._codex_advice({"task_id": "test"}) == "Inspect local evidence"


def test_only_bounded_reviewed_fields_leave_broker(tmp_path: Path, monkeypatch) -> None:
    broker, _ = _setup(tmp_path)
    digest = broker.mark_chatgpt_unavailable("task-1", "Unavailable")
    broker.approve("task-1", digest)
    sent = {}

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, *_):
            return json.dumps({"choices": [{"message": {"content": "Check local configuration."}}]}).encode()

    def fake_urlopen(request, timeout):
        sent.update(json.loads(request.data))
        assert timeout == 120
        return Response()

    monkeypatch.setattr("src.local_first.provider_broker.urlopen", fake_urlopen)
    assert broker.route("task-1", model="ollama-local/qwen2.5:7b")["state"] == "RESOLVED"
    outbound = json.loads(sent["messages"][0]["content"])
    assert "super-secret" not in json.dumps(outbound)
    assert "RAW LOG" not in json.dumps(outbound)
    assert "raw log" not in json.dumps(outbound)
    assert "/private/work" not in json.dumps(outbound)
    assert (tmp_path / "blockers/resolutions/task-1.json").is_file()


def test_router_failure_stays_blocked_and_is_not_retried(tmp_path: Path, monkeypatch) -> None:
    broker, _ = _setup(tmp_path)
    digest = broker.mark_chatgpt_unavailable("task-1", "Unavailable")
    broker.approve("task-1", digest)
    monkeypatch.setattr("src.local_first.provider_broker.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    assert broker.route("task-1")["state"] == "ROUTER_FAILED"
    assert not (tmp_path / "blockers/resolutions/task-1.json").exists()
    with pytest.raises(ValueError):
        broker.route("task-1")


def test_router_advice_cannot_override_local_safety_gate(tmp_path: Path, monkeypatch) -> None:
    broker, request = _setup(tmp_path)
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["risk"] = "A3"
    request.write_text(json.dumps(payload), encoding="utf-8")
    digest = broker.mark_chatgpt_unavailable("task-1", "Unavailable")
    broker.approve("task-1", digest)

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, *_):
            return b'{"choices":[{"message":{"content":"Proceed"}}]}'

    monkeypatch.setattr("src.local_first.provider_broker.urlopen", lambda *_args, **_kwargs: Response())
    assert broker.route("task-1", model="ollama-local/qwen2.5:7b")["state"] == "RESOLVED"

    class NeverCalled:
        async def available(self):
            raise AssertionError("safety gate must run before model")

    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps({"task_id": "task-1", "objective": "Inspect config",
                                     "next_action": "Review", "risk": "A3"}), encoding="utf-8")
    worker = LocalPrimaryWorker(tmp_path, tmp_path, NeverCalled(), RepairRecipeStore(tmp_path / "recipes"))
    assert asyncio.run(worker.run_once(task_path)).state == "BLOCKED"


@pytest.mark.skipif(os.getenv("TIM_OMNIROUTE_LIVE_TEST") != "1", reason="live local router opt-in")
def test_live_local_blocker_round_trip(tmp_path: Path) -> None:
    class FakeQwen:
        calls = 0
        async def available(self):
            return True
        async def generate_json(self, _prompt):
            self.calls += 1
            if self.calls == 1:
                return {"disposition": "BLOCKED", "blocker_reason": "Need another diagnosis"}
            return {"disposition": "READY_FOR_VERIFICATION", "next_action": "RUN_TARGETED_TEST"}

    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps({"task_id": "live-smoke", "objective": "Inspect a test configuration",
                                     "next_action": "Review status", "risk": "A1"}), encoding="utf-8")
    state = tmp_path / "state"
    qwen = FakeQwen()
    worker = LocalPrimaryWorker(tmp_path, state, qwen, RepairRecipeStore(tmp_path / "recipes"))
    assert asyncio.run(worker.run_once(task_path)).state == "BLOCKED"
    broker = ProviderBroker(state)
    digest = broker.mark_chatgpt_unavailable("live-smoke", "Explicit synthetic test")
    broker.approve("live-smoke", digest)
    assert broker.route("live-smoke", model="ollama-local/qwen2.5:7b")["state"] == "RESOLVED"
    assert asyncio.run(worker.run_once(state / "tasks/live-smoke.json")).state == "VERIFYING"
    assert qwen.calls == 2
