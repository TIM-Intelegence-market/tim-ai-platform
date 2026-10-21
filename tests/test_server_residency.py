import asyncio
import json

import pytest

from src.local_first import server_residency as residency
from src.llm.ollama_client import OllamaClient


@pytest.mark.parametrize("url", ["http://127.0.0.1:11435", "http://localhost:11435/"])
def test_accepts_only_configured_loopback_tunnel(monkeypatch, url):
    monkeypatch.setenv("TIM_QWEN_HARD_URL", url)
    monkeypatch.delenv("TIM_QWEN_HARD_MODEL", raising=False)
    assert residency.configured_server() == (url.rstrip("/"), "qwen3-coder:30b")


@pytest.mark.parametrize("url", [
    "http://127.0.0.1.evil.test:11435", "https://localhost:11435", "http://other:11435",
    "http://user@localhost:11435", "http://localhost:11435/path", "http://localhost:0",
    "http://localhost:invalid", "http://localhost:11435?other=1", "http://localhost:11435#other",
])
def test_rejects_non_tunnel_urls(monkeypatch, url):
    monkeypatch.setenv("TIM_QWEN_HARD_URL", url)
    assert residency.configured_server() is None


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, *_):
        return json.dumps(self.data).encode()


def test_warmer_loads_without_prompt_or_download(monkeypatch):
    seen = []
    monkeypatch.setattr(residency, "urlopen", lambda req, **kw: seen.append(req) or Response(
        {"models": []} if req.full_url.endswith("/api/ps") else {"done": True}))
    assert residency.warm_server("http://127.0.0.1:11435", "qwen3-coder:30b") == "WARM"
    assert seen[0].full_url.endswith("/api/ps") and seen[0].get_method() == "GET"
    payload = json.loads(seen[1].data)
    assert seen[1].full_url.endswith("/api/generate")
    assert "prompt" not in payload
    assert payload["keep_alive"] == -1
    assert payload["options"] == residency.SERVER_OPTIONS


@pytest.mark.parametrize("resident,expected", [
    ({"models": [{"name": "qwen3-coder:30b", "context_length": 4096}]}, "WARM"),
    ({"models": [{"model": "qwen3-coder:30b", "context_length": 4096}]}, "WARM"),
    ({"models": [{"name": "other:latest"}]}, "RESIDENT_OTHER"),
])
def test_warm_tick_never_reloads_or_evicts_a_resident_runner(monkeypatch, resident, expected):
    seen = []
    def respond(req, **kwargs):
        seen.append(req)
        assert req.get_method() == "GET" and req.full_url.endswith("/api/ps")
        assert req.data is None
        return Response(resident)
    monkeypatch.setattr(residency, "urlopen", respond)
    assert residency.warm_server("http://127.0.0.1:11435", "qwen3-coder:30b") == expected
    assert len(seen) == 1


@pytest.mark.parametrize("data", [{}, {"models": None}, {"models": {}}, {"models": [None]},
                                  {"models": [{}]}, {"models": [{"name": 17}]}])
def test_unknown_residency_never_blindly_loads(monkeypatch, data):
    seen = []
    monkeypatch.setattr(residency, "urlopen", lambda req, **kw: seen.append(req) or Response(data))
    with pytest.raises(ValueError):
        residency.warm_server("http://127.0.0.1:11435", "qwen3-coder:30b")
    assert len(seen) == 1 and seen[0].get_method() == "GET"


def test_residency_http_failure_never_posts(monkeypatch):
    seen = []
    def fail(req, **kwargs):
        seen.append(req)
        raise TimeoutError("residency unknown")
    monkeypatch.setattr(residency, "urlopen", fail)
    with pytest.raises(TimeoutError):
        residency.warm_server("http://127.0.0.1:11435", "qwen3-coder:30b")
    assert len(seen) == 1 and seen[0].get_method() == "GET"


def test_broken_tunnel_uses_backoff_instead_of_stopping_worker(monkeypatch):
    monkeypatch.setenv("TIM_QWEN_HARD_URL", "http://127.0.0.1:11435")
    monkeypatch.setattr(residency, "warm_server", lambda *_: (_ for _ in ()).throw(TimeoutError()))

    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, seconds):
            assert seconds == 60
            self.stopped = True

    residency.residency_loop(Stop())


def test_chat_and_generate_preserve_server_residency(monkeypatch):
    seen = []

    def respond(req, **_):
        seen.append(json.loads(req.data))
        return Response({"message": {"content": "OK"}, "response": "{}"})

    monkeypatch.setattr("src.llm.ollama_client.urlopen", respond)
    client = OllamaClient("http://localhost:11435", "qwen3-coder:30b", observation_only=False, keep_alive=-1)
    asyncio.run(client.chat([{"role": "user", "content": "test"}]))
    asyncio.run(client.generate_json("test"))
    assert all(payload["keep_alive"] == -1 for payload in seen)
    # Other Ollama users retain their existing residency policy.
    asyncio.run(OllamaClient("http://localhost:11434", "other", observation_only=False).generate_json("test"))
    assert "keep_alive" not in seen[-1]


def test_small_issue_uses_server_without_expanding_file_contract(tmp_path, monkeypatch):
    from scripts import run_mac_qwen_issue as runner
    from scripts.github_issue_pipeline import PipelineError

    monkeypatch.setenv("TIM_QWEN_SERVER_PREFERRED", "1")
    monkeypatch.delenv("TIM_QWEN_HARD_RUN", raising=False)
    monkeypatch.setattr(runner, "_hard_backend", lambda: ("http://localhost:11435", "qwen3-coder:30b"))
    seen = {}
    monkeypatch.setattr(runner, "_run_task_group", lambda cmd, cwd, env, **kw: seen.update(env) or 2)
    task = {"task_id": "test-server", "allowed_paths": ["src/a.py"], "tests": ["tests/test_a.py"]}
    with pytest.raises(PipelineError):
        runner._run_local_task(tmp_path, task, codex_fallback=False)
    assert seen["OLLAMA_MODEL"] == "qwen3-coder:30b"
    assert seen["TIM_QWEN_SERVER_RUN"] == "1"
    assert "TIM_QWEN_HARD_RUN" not in seen
    assert seen["TIM_TEST_SANDBOX"] == "required"


def test_server_intake_does_not_require_a_working_mac_model(tmp_path, monkeypatch):
    from scripts import run_local_qwen_daemon as daemon

    monkeypatch.setenv("TIM_QWEN_SERVER_PREFERRED", "1")
    monkeypatch.setenv("TIM_QWEN_HARD_URL", "http://localhost:11435")
    monkeypatch.setenv("TIM_QWEN_HARD_MODEL", "qwen3-coder:30b")

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def model_available(self):
            return True

    monkeypatch.setattr(daemon, "OllamaClient", Client)
    monkeypatch.setattr(daemon, "_ensure_local_qwen", lambda *_: pytest.fail("Mac preflight must not run"))
    assert asyncio.run(daemon._ensure_issue_qwen(object(), tmp_path)) == ("qwen3-coder:30b", None)


def test_server_outage_falls_back_to_mac_preflight(tmp_path, monkeypatch):
    from scripts import run_local_qwen_daemon as daemon
    from types import SimpleNamespace

    monkeypatch.setenv("TIM_QWEN_SERVER_PREFERRED", "1")
    monkeypatch.setenv("TIM_QWEN_HARD_URL", "http://localhost:11435")

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def model_available(self):
            return False

    async def local(*_):
        return "mac-model", None

    monkeypatch.setattr(daemon, "OllamaClient", Client)
    monkeypatch.setattr(daemon, "_ensure_local_qwen", local)
    args = SimpleNamespace(ollama_url="http://localhost:11434", model="mac-model", fallback_models="")
    assert asyncio.run(daemon._ensure_issue_qwen(args, tmp_path)) == ("mac-model", None)
