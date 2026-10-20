from __future__ import annotations

import asyncio
import json

import pytest

from scripts import run_local_qwen_developer as developer
from src.local_first import qwen_tool_loop as loop_mod
from src.local_first.qwen_tool_loop import QwenToolLoop, RepoReader, parse_text_tool_calls

IMPLEMENTATION = "src/example.py"
TEST = "tests/test_example.py"
ORIGINAL = "VALUE = 1\n\n\ndef double(x):\n    return x * 2\n"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("TIM_LOCAL_PATCH_SANDBOX", "1")
    monkeypatch.setenv("TIM_LIVE_TRADING", "0")
    monkeypatch.setenv("TIM_EXECUTION_ENABLED", "0")
    monkeypatch.delenv("TIM_QWEN_TOOL_LOOP", raising=False)
    marker = tmp_path / ".tim/local-first/PATCH_SANDBOX_ALLOWED"
    marker.parent.mkdir(parents=True)
    marker.write_text("test sandbox only\n")
    (tmp_path / "src").mkdir()
    (tmp_path / IMPLEMENTATION).write_text(ORIGINAL)
    (tmp_path / "tests").mkdir()
    (tmp_path / TEST).write_text("def test_value():\n    assert True\n")
    return tmp_path


def contract_for(repo):
    task = {"task_id": "t", "allowed_paths": [IMPLEMENTATION, TEST]}
    return developer._build_contract(repo, task)


# --- search/replace edits -------------------------------------------------------------

def test_edits_are_applied_to_the_snapshot(sandbox):
    contract = contract_for(sandbox)
    bound = developer._bind_proposal({"patches": [{"path": IMPLEMENTATION, "edits": [
        {"search": "VALUE = 1\n", "replace": "VALUE = 2\n"},
        {"search": "return x * 2", "replace": "return x + x"},
    ]}]}, contract, "p")
    assert bound["patches"][0]["content"] == "VALUE = 2\n\n\ndef double(x):\n    return x + x\n"


@pytest.mark.parametrize("edits, message", [
    ([{"search": "missing", "replace": "x"}], "not found"),
    ([{"search": "\n", "replace": "x"}], "found"),
    ([{"search": "", "replace": "x"}], "empty search"),
    ([{"search": "VALUE"}], "string search and replace"),
    ([{"search": "VALUE = 1", "replace": "VALUE = ("}], "python syntax error"),
])
def test_bad_edits_are_repairable_errors(sandbox, edits, message):
    with pytest.raises(developer.ProposalError, match=message):
        developer._bind_proposal({"patches": [{"path": IMPLEMENTATION, "edits": edits}]},
                                 contract_for(sandbox), "p")


def test_edits_and_content_together_are_rejected(sandbox):
    with pytest.raises(developer.ProposalError, match="either content or edits"):
        developer._bind_proposal({"patches": [{"path": IMPLEMENTATION, "content": "X = 1\n",
                                               "edits": [{"search": "VALUE", "replace": "V"}]}]},
                                 contract_for(sandbox), "p")


def test_new_files_need_content(sandbox):
    (sandbox / TEST).unlink()
    with pytest.raises(developer.ProposalError, match="need complete content"):
        developer._bind_proposal({"patches": [{"path": TEST, "edits": [{"search": "a", "replace": "b"}]}]},
                                 contract_for(sandbox), "p")


def test_edits_cannot_target_paths_outside_allowlist(sandbox):
    with pytest.raises(developer.ContractError, match="not allowlisted"):
        developer._bind_proposal({"patches": [{"path": "src/other.py", "edits": [{"search": "a", "replace": "b"}]}]},
                                 contract_for(sandbox), "p")


def test_schema_limits_paths_to_allowlist(sandbox):
    schema = developer.proposal_schema(contract_for(sandbox))
    item = schema["properties"]["patches"]["items"]
    assert item["properties"]["path"]["enum"] == [IMPLEMENTATION, TEST]
    assert schema["properties"]["patches"]["maxItems"] == 2


# --- text tool-call parsing -----------------------------------------------------------

def test_parses_tool_call_tags_and_function_tags():
    content = ('<tool_call>{"name": "read_file", "arguments": {"path": "src/a.py"}}</tool_call>'
               '<function=search_code><parameter=text>def x</parameter><parameter=path>src</parameter></function>')
    assert parse_text_tool_calls(content) == [
        ("read_file", {"path": "src/a.py"}), ("search_code", {"text": "def x", "path": "src"})]


def test_bare_patch_json_counts_as_submit():
    calls = parse_text_tool_calls('```json\n{"patches": [{"path": "src/a.py", "content": "X = 1\\n"}]}\n```')
    assert calls == [("submit_patch", {"patches": [{"path": "src/a.py", "content": "X = 1\n"}]})]


def test_plain_prose_has_no_calls():
    assert parse_text_tool_calls("I think the bug is in line 3.") == []


# --- read-only repository view --------------------------------------------------------

@pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "config/secrets.py", ".env",
                                  "src/.env", "src/../config/secrets.py", "scripts/run.py", "src\\a.py"])
def test_reader_refuses_paths_outside_read_roots(sandbox, path):
    with pytest.raises(ValueError):
        RepoReader(sandbox).read_file(path)


def test_reader_refuses_symlinks(sandbox, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "token.txt"
    outside.write_text("secret")
    (sandbox / "src/link.py").symlink_to(outside)
    with pytest.raises(ValueError):
        RepoReader(sandbox).read_file("src/link.py")


def test_reader_refuses_symlinked_folders(sandbox):
    (sandbox / ".tim/x.json").write_text("evidence")
    (sandbox / "src/state").symlink_to(sandbox / ".tim")
    with pytest.raises(ValueError):
        RepoReader(sandbox).read_file("src/state/x.json")
    with pytest.raises(ValueError):
        RepoReader(sandbox).list_dir("src/state")


def test_parser_bounds_runaway_output():
    import time
    start = time.monotonic()
    assert parse_text_tool_calls("<tool_call>{" * 100_000) == []
    assert time.monotonic() - start < 5


def test_reader_numbers_lines_and_redacts(sandbox):
    (sandbox / "src/conf.py").write_text("A = 1\napi_key = 'abc123'\nT = 'ghp_" + "z" * 30 + "'\n")
    loop = QwenToolLoop(None, sandbox, check_patch=lambda p: None, run_tests=dict)
    text = loop._result("read_file", {"path": "src/conf.py"})
    assert "1: A = 1" in text
    assert "abc123" not in text and "ghp_" + "z" * 20 not in text


def test_search_finds_exact_text(sandbox):
    assert RepoReader(sandbox).search("def double", "src") == "src/example.py:4: def double(x):"


# --- the loop -------------------------------------------------------------------------

class ScriptedChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []
        self.timeouts = []

    async def chat(self, messages, *, tools=None, options=None, timeout=None):
        self.seen.append([dict(m) for m in messages])
        self.timeouts.append(timeout)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def native(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def make_loop(sandbox, chat, checks=None, **kwargs):
    checks = [] if checks is None else checks

    def check(patches):
        checks.append(patches)
        if not isinstance(patches, list) or not patches or "content" not in patches[0]:
            raise ValueError("patch requires content")

    return QwenToolLoop(chat, sandbox, check_patch=check,
                        run_tests=lambda: {"returncode": 1, "stdout": "1 failed", "stderr": ""}, **kwargs)


def test_loop_reads_then_submits(sandbox):
    patch = [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]
    chat = ScriptedChat([native("read_file", path=IMPLEMENTATION), native("run_required_tests"),
                         native("submit_patch", patches=patch)])
    result = asyncio.run(make_loop(sandbox, chat).run("sys", "user"))
    assert result.proposal == {"patches": patch}
    assert result.stats["submitted"] and result.stats["native_calls"] == 3
    tool_messages = [m for m in chat.seen[-1] if m["role"] == "tool"]
    assert "1: VALUE = 1" in tool_messages[0]["content"]
    assert tool_messages[1]["content"].startswith("returncode=1")


def test_loop_uses_text_calls_and_rejects_bad_submit(sandbox):
    good = [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]
    chat = ScriptedChat([
        {"role": "assistant", "content": '<tool_call>{"name": "submit_patch", "arguments": {"patches": []}}</tool_call>'},
        {"role": "assistant", "content": json.dumps({"patches": good})},
    ])
    result = asyncio.run(make_loop(sandbox, chat).run("sys", "user"))
    assert result.proposal == {"patches": good}
    assert result.stats["text_parsed_calls"] == 2
    assert any(m["role"] == "tool" and m["content"].startswith("REJECTED") for m in chat.seen[-1])


def test_loop_turn_timeout_is_longer_than_client_default_but_within_budget(sandbox):
    now = [0.0]
    patch = [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]

    class SlowChat(ScriptedChat):
        async def chat(self, messages, **kwargs):
            reply = await super().chat(messages, **kwargs)
            now[0] += 250.0
            return reply

    chat = SlowChat([native("read_file", path=IMPLEMENTATION), native("read_file", path=IMPLEMENTATION),
                     native("submit_patch", patches=patch)])
    result = asyncio.run(make_loop(sandbox, chat, clock=lambda: now[0]).run("sys", "user"))
    assert result.stats["submitted"]
    assert chat.timeouts == [loop_mod.CHAT_TURN_SECONDS, loop_mod.CHAT_TURN_SECONDS, 100.0]


def test_hard_loop_allows_server_cold_start_and_keeps_total_deadline(sandbox, monkeypatch):
    monkeypatch.setenv("TIM_QWEN_HARD_RUN", "1")
    now = [0.0]
    patch = [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]

    class ColdServer(ScriptedChat):
        async def chat(self, messages, **kwargs):
            reply = await super().chat(messages, **kwargs)
            now[0] += 350.0
            return reply

    chat = ColdServer([native("read_file", path=IMPLEMENTATION), native("submit_patch", patches=patch)])
    loop = make_loop(sandbox, chat, clock=lambda: now[0])
    result = asyncio.run(loop.run("sys", "user"))
    assert result.stats["submitted"]
    assert chat.timeouts == [900.0, 550.0]
    assert loop_mod.chat_options()["num_ctx"] == 65536
    assert loop_mod.chat_options()["num_batch"] == 256


def test_explicit_short_deadline_still_limits_hard_server_calls(sandbox, monkeypatch):
    monkeypatch.setenv("TIM_QWEN_HARD_RUN", "1")
    patch = [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]
    chat = ScriptedChat([native("submit_patch", patches=patch)])
    result = asyncio.run(make_loop(sandbox, chat, max_seconds=10, clock=lambda: 0).run("s", "u"))
    assert result.stats["submitted"]
    assert chat.timeouts == [10.0]


def test_server_one_shot_retains_large_context_and_bounded_batch(monkeypatch):
    from src.llm import ollama_client

    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps({"response": '{"patches": []}'}).encode()

    def fake_urlopen(request, timeout):
        seen.update(json.loads(request.data))
        return Response()

    monkeypatch.setattr(ollama_client, "urlopen", fake_urlopen)
    monkeypatch.setenv("TIM_QWEN_HARD_RUN", "1")
    client = ollama_client.OllamaClient("http://127.0.0.1:11435", "qwen3-coder:30b",
                                      observation_only=False, generation_options=loop_mod.chat_options())
    assert asyncio.run(client.generate_json("large contract", schema={"type": "object"})) == {"patches": []}
    assert seen["options"]["num_ctx"] == 65536
    assert seen["options"]["num_batch"] == 256


def test_ollama_chat_uses_per_turn_timeout(monkeypatch):
    from src.llm import ollama_client

    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"message": {"role": "assistant", "content": "ok"}}).encode()

    def fake_urlopen(request, timeout):
        seen.setdefault("timeouts", []).append(timeout)
        return Response()

    monkeypatch.setattr(ollama_client, "urlopen", fake_urlopen)
    client = ollama_client.OllamaClient("http://127.0.0.1:11434", "qwen", timeout=120, observation_only=False)
    asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
    asyncio.run(client.chat([{"role": "user", "content": "hi"}], timeout=300.0))
    assert seen["timeouts"] == [120, 300.0]


def test_loop_reports_chat_errors_for_one_shot_fallback(sandbox):
    result = asyncio.run(make_loop(sandbox, ScriptedChat([OSError("400 tools unsupported")])).run("s", "u"))
    assert result.proposal is None and result.stats["ended"] == "chat_error:OSError"


def test_loop_nudges_then_stops_without_calls(sandbox):
    chat = ScriptedChat([{"role": "assistant", "content": "thinking"}] * 3)
    result = asyncio.run(make_loop(sandbox, chat).run("s", "u"))
    assert result.proposal is None and result.stats["ended"] == "no_tool_calls" and result.stats["nudges"] == 2


def test_loop_stops_at_time_budget(sandbox):
    ticks = iter([0.0, 0.0, 1000.0])
    chat = ScriptedChat([native("list_dir", path="src")] * 5)
    result = asyncio.run(make_loop(sandbox, chat, max_seconds=10, clock=lambda: next(ticks)).run("s", "u"))
    assert result.stats["ended"] == "time_budget_exhausted" and result.stats["steps"] == 1


def test_loop_turns_tool_errors_and_unknown_tools_into_text(sandbox):
    patch = [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]
    chat = ScriptedChat([native("read_file", path="../secret"), native("rm_rf", path="/"),
                         native("submit_patch", patches=patch)])
    result = asyncio.run(make_loop(sandbox, chat).run("s", "u"))
    tool_messages = [m["content"] for m in chat.seen[-1] if m["role"] == "tool"]
    assert tool_messages[0].startswith("ERROR:") and "unknown tool" in tool_messages[1]
    assert result.stats["invalid_calls"] == 1 and result.proposal == {"patches": patch}


def test_test_runs_are_budgeted(sandbox):
    runs = []
    loop = QwenToolLoop(ScriptedChat([]), sandbox, check_patch=lambda p: None,
                        run_tests=lambda: runs.append(1) or {"returncode": 0})
    outputs = [loop._result("run_required_tests", {}) for _ in range(3)]
    assert len(runs) == loop_mod.MAX_TEST_RUNS and "budget" in outputs[-1]


# --- developer integration ------------------------------------------------------------

def run_developer(repo, monkeypatch, *, chat_replies, json_replies=()):
    task = {"task_id": "loop-task", "risk": "A3", "sandboxed": True,
            "objective": "Set VALUE to 2", "allowed_paths": [IMPLEMENTATION, TEST]}
    task_path = repo / "input.json"
    task_path.write_text(json.dumps(task))
    chats, prompts = list(chat_replies), list(json_replies)
    seen = {"chat": 0, "json": 0, "schema": None}

    class FakeOllama:
        def __init__(self, *args, **kwargs):
            pass

        async def available(self):
            return True

        async def chat(self, messages, *, tools=None, options=None, timeout=None):
            seen["chat"] += 1
            assert {tool["function"]["name"] for tool in tools} == loop_mod.TOOL_NAMES
            reply = chats.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        async def generate_json(self, prompt, *, schema=None):
            seen["json"] += 1
            seen["schema"] = schema
            return prompts.pop(0)

    monkeypatch.setattr(developer, "OllamaClient", FakeOllama)
    monkeypatch.setattr(developer.SafePatchExecutor, "_run_tests",
                        lambda self, paths: {"returncode": 0, "tests": paths, "sandbox": "none"})
    args = developer.parser().parse_args([str(task_path), "--repo-root", str(repo)])
    code = asyncio.run(developer.run(args))
    result = json.loads((repo / ".tim/local-first/developer-results/loop-task.json").read_text())
    return code, result, seen


def test_developer_uses_tool_loop_when_enabled(sandbox, monkeypatch):
    monkeypatch.setenv("TIM_QWEN_TOOL_LOOP", "1")
    edit = [{"path": IMPLEMENTATION, "edits": [{"search": "VALUE = 1", "replace": "VALUE = 2"}]}]
    code, result, seen = run_developer(sandbox, monkeypatch, chat_replies=[
        native("check_patch", patches=edit), native("submit_patch", patches=edit)])
    assert code == 0 and result["status"] == "VERIFYING"
    assert seen == {"chat": 2, "json": 0, "schema": None}
    assert result["tool_loop"]["submitted"] is True and result["tool_loop"]["calls_by_tool"] == {
        "check_patch": 1, "submit_patch": 1}
    assert (sandbox / IMPLEMENTATION).read_text().startswith("VALUE = 2\n")


def test_developer_falls_back_to_one_shot_with_schema(sandbox, monkeypatch):
    monkeypatch.setenv("TIM_QWEN_TOOL_LOOP", "1")
    code, result, seen = run_developer(
        sandbox, monkeypatch, chat_replies=[OSError("tools unsupported")],
        json_replies=[{"patches": [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]}])
    assert code == 0 and result["status"] == "VERIFYING" and result["model_calls"] == 2
    assert result["tool_loop"]["ended"] == "chat_error:OSError"
    assert seen["json"] == 1 and seen["schema"]["required"] == ["patches"]


def test_issue_budget_exhaustion_still_runs_helper_and_persists_result(sandbox, monkeypatch):
    from src.local_first import claude_cli_fallback

    monkeypatch.setenv("TIM_QWEN_TOOL_LOOP", "1")
    monkeypatch.setenv("TIM_QWEN_GITHUB_RUN", "1")
    monkeypatch.setenv("TIM_CODEX_PATCH_FALLBACK", "0")
    monkeypatch.setenv("TIM_CLAUDE_PATCH_FALLBACK", "1")
    clock = [100.0]
    monkeypatch.setattr(developer.time, "monotonic", lambda: clock[0])
    limits = []

    async def exhausted(*args, max_seconds):
        limits.append(max_seconds)
        clock[0] += max_seconds
        return None, {"ended": "budget"}

    monkeypatch.setattr(developer, "_tool_loop_proposal", exhausted)
    helpers = []

    def helper(prompt):
        helpers.append(prompt)
        return {"patches": [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]}

    monkeypatch.setattr(claude_cli_fallback, "propose", helper)
    code, result, seen = run_developer(sandbox, monkeypatch, chat_replies=[])
    assert limits == [900.0]
    assert seen["json"] == 0  # No fresh 900s request after the loop spent its budget.
    assert code == 0 and result["status"] == "VERIFYING"
    assert result["fallback_provider"] == "CLAUDE_CLI" and len(helpers) == 1
    assert result["model_calls"] == 1
    assert "budget exhausted" in result["qwen_blocker_reason"]


def test_issue_structured_retry_uses_only_remaining_budget(sandbox, monkeypatch):
    monkeypatch.setenv("TIM_QWEN_TOOL_LOOP", "1")
    monkeypatch.setenv("TIM_QWEN_GITHUB_RUN", "1")
    clock = [100.0]
    monkeypatch.setattr(developer.time, "monotonic", lambda: clock[0])

    clients = []

    async def early_failure(ollama, *args, max_seconds):
        assert max_seconds == 900
        clients.append(ollama)
        clock[0] += 840
        return None, {"ended": "chat_error"}

    monkeypatch.setattr(developer, "_tool_loop_proposal", early_failure)
    code, result, seen = run_developer(sandbox, monkeypatch, chat_replies=[], json_replies=[
        {"patches": [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]}])
    assert code == 0 and result["model_calls"] == 2 and seen["json"] == 1
    assert clients[0].timeout == 60.0


def test_tool_loop_is_off_by_default(sandbox, monkeypatch):
    code, result, seen = run_developer(
        sandbox, monkeypatch, chat_replies=[],
        json_replies=[{"patches": [{"path": IMPLEMENTATION, "content": "VALUE = 2\n"}]}])
    assert code == 0 and seen["chat"] == 0 and result["tool_loop"] is None
