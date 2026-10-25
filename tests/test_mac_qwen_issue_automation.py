from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_mac_qwen_issue as runner
from scripts.github_issue_pipeline import PipelineError
from src.local_first import issue_triage
from src.local_first.github_issue_queue import build_task, select_ready_issue
from src.local_first.issue_triage import IssueLedger, attach_worker_contract

WORKER = "apoman74-art"


def _issue(number, labels=(), body="", author="uezeyiraydin-cell", comments=()):
    return {"number": number, "title": f"Issue {number}", "state": "OPEN", "body": body,
            "labels": [{"name": name} for name in labels], "author": {"login": author},
            "comments": list(comments)}


def _contract(number, paths=("src/example.py", "tests/test_example.py")):
    return issue_triage.render_contract_block({
        "task_id": f"github-issue-{number}", "issue_number": number, "risk": "A3", "sandboxed": True,
        "objective": "Fix the rounding", "allowed_paths": list(paths), "tests": ["tests/test_example.py"]})


READY = ("agent:qwen-ready", "status:ready", "priority:p1")
HARD = ("agent:qwen-hard", "status:ready", "priority:p1")


@pytest.fixture(autouse=True)
def _no_ci_job_or_server(monkeypatch):
    # These tests themselves run inside a CI job (Runner.Worker) on the Mac runner.
    monkeypatch.setattr(runner, "ci_job_running", lambda: False)
    monkeypatch.delenv("TIM_QWEN_HARD_URL", raising=False)


class FakePipeline:
    def __init__(self, issues, prs=(), repository=Path("/repo")):
        self.issues, self.prs, self.repository = issues, list(prs), repository
        self.calls = []

    def verify_worker_identity(self):
        pass

    def repository_slug(self):
        return runner.REPO

    def github(self, *args):
        self.calls.append(("gh",) + args)
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        if args[:2] == ("pr", "list"):
            return json.dumps(self.prs)
        if args[:2] == ("label", "list"):
            return "[]"
        return ""

    def command(self, *args, **kwargs):
        self.calls.append(args)
        return ""

    def default_base_ref(self):
        return "origin/platform-main"


def _gh(pipeline, *prefix):
    return [call for call in pipeline.calls if call[:len(prefix) + 1] == ("gh",) + prefix]


def test_worker_comment_contract_counts_but_not_from_others():
    stranger = {"author": {"login": "someone"}, "body": issue_triage.TRIAGE_MARKER + "\n" + _contract(5)}
    issue = _issue(5, READY, body="Bitte reparieren", comments=[stranger])
    assert attach_worker_contract(issue, WORKER) is issue
    with pytest.raises(ValueError):
        build_task(issue)
    own = {**stranger, "author": {"login": WORKER}}
    prepared = attach_worker_contract(_issue(5, READY, body="x", comments=[own]), WORKER)
    assert build_task(prepared)["allowed_paths"] == ["src/example.py", "tests/test_example.py"]


def test_select_skips_numbers():
    issues = [_issue(3, READY, _contract(3)), _issue(4, READY, _contract(4))]
    assert select_ready_issue(issues)["number"] == 3
    assert select_ready_issue(issues, skip={3})["number"] == 4


def test_triage_candidates_filter_and_order(tmp_path):
    ledger = IssueLedger(tmp_path / "ledger.json")
    issues = [
        _issue(10), _issue(11, ("priority:p0",)), _issue(12, ("type:epic",)),
        _issue(13, author="stranger"), _issue(14, ("agent:not-suitable",)),
        _issue(15, body=_contract(15)), _issue(16, READY),
    ]
    assert [i["number"] for i in issue_triage.triage_candidates(issues, ledger)] == [11, 10]


def test_triage_runs_at_most_twice_per_issue_version(tmp_path):
    ledger = IssueLedger(tmp_path / "ledger.json")
    issue = _issue(20, body="v1")
    ledger.record_triage(issue, "error:RuntimeError")
    assert ledger.triage_allowed(issue)
    ledger.record_triage(issue, "error:RuntimeError")
    assert not ledger.triage_allowed(issue)
    assert ledger.triage_allowed({**issue, "body": "v2"})
    assert not IssueLedger(tmp_path / "ledger.json").triage_allowed(issue)  # survives a restart


def test_parse_triage_binds_answer_to_contract_rules():
    issue = _issue(30)
    good = json.dumps({"decision": "ready", "reason": "klein", "priority": "p0", "objective": "Fix x",
                       "allowed_paths": ["src/x.py", "tests/test_x.py"], "tests": ["tests/test_x.py"]})
    result = issue_triage.parse_triage(f"Antwort:\n```json\n{good}\n```", issue)
    assert result["decision"] == "ready" and result["priority"] == "p0"
    assert result["task"]["task_id"] == "github-issue-30"
    protected = json.loads(good)
    protected["allowed_paths"] = ["src/local_first/runtime.py"]
    assert issue_triage.parse_triage(json.dumps(protected), issue)["decision"] == "skip"
    assert issue_triage.parse_triage("kein json", issue)["decision"] == "skip"
    skip = issue_triage.parse_triage('{"decision": "skip", "reason": "Epic"}', issue)
    assert skip == {"decision": "skip", "reason": "Epic"}


def test_attempts_stop_after_two_failures_and_reset_when_label_removed(tmp_path):
    ledger = IssueLedger(tmp_path / "ledger.json")
    ledger.start_attempt(40, "c1")
    assert not ledger.record_failure(40, "c1", "boom ghp_" + "a" * 36)
    assert "<REDACTED_TOKEN>" in ledger.errors(40)[0]
    ledger.start_attempt(40, "c1")
    assert ledger.record_failure(40, "c1", "boom")
    assert ledger.exhausted(40, "c1") and not ledger.exhausted(40, "c2")
    ledger.mark_blocked(40)
    ledger.reconcile([_issue(40, READY + ("agent:blocked",))])
    assert ledger.exhausted(40, "c1")
    ledger.reconcile([_issue(40, READY)])
    assert not ledger.exhausted(40, "c1")


def test_triage_prepares_issue_when_nothing_is_ready(tmp_path, monkeypatch):
    answer = json.dumps({"decision": "ready", "reason": "klein", "priority": "p1", "objective": "Fix x",
                         "allowed_paths": ["src/x.py"], "tests": ["tests/test_x.py"]})
    monkeypatch.setattr(issue_triage, "ask_claude", lambda prompt, root: answer)
    pipeline = FakePipeline([_issue(50, body="Rundung falsch")])
    result = runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False,
                                merge=True, triage=True)
    assert "#50 prepared" in result
    comment = _gh(pipeline, "issue", "comment")[0]
    assert issue_triage.TRIAGE_MARKER in comment[-1] and "TIM_QWEN_TASK_V1" in comment[-1]
    assert _gh(pipeline, "issue", "edit")[0][-1] == "agent:qwen-ready,status:ready,priority:p1"
    # The next poll does not triage the same issue again while GitHub still shows it unlabelled.
    monkeypatch.setattr(issue_triage, "ask_claude", lambda prompt, root: pytest.fail("triaged twice"))
    ledger = IssueLedger(tmp_path / "issue-ledger.json")
    ledger.record_triage(_issue(50, body="Rundung falsch"), "ready")
    assert "nothing left" in runner.process_one(FakePipeline([_issue(50, body="Rundung falsch")]), tmp_path,
                                                pilot_issue=None, codex_fallback=False, merge=True,
                                                triage=True)


def test_unsuitable_issue_is_labelled_once(tmp_path, monkeypatch):
    monkeypatch.setattr(issue_triage, "ask_claude",
                        lambda prompt, root: '{"decision": "skip", "reason": "Serverarbeit"}')
    pipeline = FakePipeline([_issue(51)])
    assert "not a Mac Qwen task" in runner.process_one(pipeline, tmp_path, pilot_issue=None,
                                                       codex_fallback=False, merge=True, triage=True)
    assert _gh(pipeline, "issue", "edit")[0][-1] == "agent:not-suitable"


def test_failed_attempts_block_the_issue_and_free_the_queue(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise PipelineError("local task acceptance is not FIXED")

    monkeypatch.setattr(runner, "_run_local_task", fail)
    issues = [_issue(60, READY, _contract(60)), _issue(61, READY, _contract(61))]
    for _ in range(2):
        with pytest.raises(PipelineError):
            runner.process_one(FakePipeline(issues), tmp_path, pilot_issue=None,
                               codex_fallback=False, merge=True)
    ledger = IssueLedger(tmp_path / "issue-ledger.json")
    assert ledger.entry(60)["blocked"] is True
    issues[0] = _issue(60, READY + ("agent:blocked",), _contract(60))  # as GitHub now shows it
    pipeline = FakePipeline(issues)
    with pytest.raises(PipelineError):
        runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False, merge=True)
    # Issue 60 is skipped now, so the queue moves on to 61 instead of repeating the same failure.
    assert any("issue-61-qwen" in str(call) for call in pipeline.calls)
    assert not any("issue-60-qwen" in str(call) for call in pipeline.calls)


def test_block_comment_and_label_once_after_second_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_run_local_task",
                        lambda *a, **k: (_ for _ in ()).throw(PipelineError("same failure")))
    issues = [_issue(62, READY, _contract(62))]
    pipelines = [FakePipeline(issues) for _ in range(2)]
    for pipeline in pipelines:
        with pytest.raises(PipelineError):
            runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False, merge=True)
    assert not _gh(pipelines[0], "issue", "edit")
    assert _gh(pipelines[1], "issue", "edit")[0][-1] == "agent:blocked"
    assert "same failure" in _gh(pipelines[1], "issue", "comment")[0][-1]


def test_invalid_contract_on_ready_issue_does_not_block_others(tmp_path):
    issues = [_issue(70, READY, "kein Vertrag"), _issue(71, READY, _contract(71))]
    pipeline = FakePipeline(issues)
    assert "#71" in runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False,
                                       merge=True, dry_run=True)
    pipeline = FakePipeline(issues)
    runner._select(pipeline, IssueLedger(tmp_path / "l.json"), issues, pilot_issue=None,
                   skip=set(), dry_run=False)
    assert _gh(pipeline, "issue", "edit")[0][-1] == "agent:blocked"


def test_worker_prs_are_merged_updated_or_retired(tmp_path):
    base = {"baseRefName": "platform-main", "createdAt": "2026-10-12T10:00:00Z",
            "author": {"login": WORKER}}
    prs = [{**base, "number": 1, "headRefName": "codex/issue-80-qwen", "mergeStateStatus": "CLEAN"},
           {**base, "number": 2, "headRefName": "codex/issue-81-qwen", "mergeStateStatus": "BEHIND"},
           {**base, "number": 3, "headRefName": "codex/issue-82-qwen", "mergeStateStatus": "DIRTY"},
           {**base, "number": 4, "headRefName": "codex/issue-83-qwen", "mergeStateStatus": "BLOCKED"},
           {**base, "number": 5, "headRefName": "claude/other", "mergeStateStatus": "CLEAN"}]
    pipeline = FakePipeline([], prs)
    ledger = IssueLedger(tmp_path / "l.json")
    now = 1_791_800_000.0  # 2026-10-12 about 12:53 UTC, under the stale limit
    covered = runner._maintain_worker_prs(pipeline, ledger, merge=True, now=now)
    assert covered == {80, 81, 83}
    assert ("gh", "pr", "merge", "1", "--squash") in pipeline.calls
    assert ("gh", "pr", "update-branch", "2") in pipeline.calls
    assert _gh(pipeline, "pr", "close")[0][3] == "3"
    stale = runner._maintain_worker_prs(FakePipeline([], prs[3:4]), ledger, merge=True,
                                        now=now + runner.STALE_PR_SECONDS)
    assert stale == set()


def test_self_update_fast_forwards_only_a_clean_checkout():
    class Git(FakePipeline):
        def __init__(self, head, target, dirty="", ancestor=True):
            super().__init__([])
            self.answers = {("git", "rev-parse", "HEAD"): head,
                            ("git", "rev-parse", "origin/platform-main"): target,
                            ("git", "status", "--porcelain", "--untracked-files=no"): dirty}
            self.ancestor = ancestor

        def command(self, *args, **kwargs):
            self.calls.append(args)
            if args[:2] == ("git", "merge-base") and not self.ancestor:
                raise PipelineError("not ancestor")
            return self.answers.get(args, "")

    assert runner.self_update(Git("a" * 40, "a" * 40)) is None
    moved = Git("a" * 40, "b" * 40)
    assert runner.self_update(moved).startswith("TIM_SELF_UPDATED")
    assert ("git", "checkout", "--quiet", "--detach", "origin/platform-main") in moved.calls
    for blocked in (Git("a" * 40, "b" * 40, dirty=" M x.py"), Git("a" * 40, "b" * 40, ancestor=False)):
        assert runner.self_update(blocked) is None
        assert not any(call[:2] == ("git", "checkout") for call in blocked.calls)


def _split_answer(*subtasks):
    return json.dumps({"decision": "split", "reason": "Sammel-Issue", "subtasks": list(subtasks)})


GOOD_SUB = {"title": "Marker erneut lesen", "priority": "p1", "objective": "Fix marker",
            "allowed_paths": ["src/x.py", "tests/test_x.py"], "tests": ["tests/test_x.py"]}


def test_parse_split_keeps_only_valid_subtasks():
    bad = {**GOOD_SUB, "allowed_paths": ["src/local_first/runtime.py"]}
    result = issue_triage.parse_triage(_split_answer(GOOD_SUB, bad, {**GOOD_SUB, "title": ""}), _issue(90))
    assert result["decision"] == "split" and len(result["subtasks"]) == 1
    assert issue_triage.parse_triage(_split_answer(bad), _issue(90))["decision"] == "skip"
    many = issue_triage.parse_triage(_split_answer(*[GOOD_SUB] * 9), _issue(90))
    assert len(many["subtasks"]) == issue_triage.MAX_SUBTASKS


def test_split_creates_ready_child_issues_once(tmp_path, monkeypatch):
    monkeypatch.setattr(issue_triage, "ask_claude", lambda prompt, root: _split_answer(GOOD_SUB, GOOD_SUB))

    class Creating(FakePipeline):
        next_number = 200

        def github(self, *args):
            if args[:2] == ("issue", "create"):
                self.calls.append(("gh",) + args)
                Creating.next_number += 1
                return f"https://github.com/o/r/issues/{Creating.next_number}"
            return super().github(*args)

    parent = _issue(91, body="viele Punkte")
    pipeline = Creating([parent])
    result = runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False,
                                merge=True, triage=True)
    assert "split into 2" in result
    bodies = [call[-1] for call in _gh(pipeline, "issue", "edit") if call[-2] == "--body"]
    assert len(bodies) == 2
    child = attach_worker_contract({**_issue(201, READY), "body": bodies[0]}, WORKER)
    assert build_task(child)["task_id"] == "github-issue-201"
    assert ("gh", "issue", "edit", "91", "--add-label", "agent:split") in pipeline.calls
    assert IssueLedger(tmp_path / "issue-ledger.json").entry(91)["children"] == [201, 202]
    # Same version is never split again, even if GitHub lost the label.
    monkeypatch.setattr(issue_triage, "ask_claude", lambda prompt, root: pytest.fail("split twice"))
    assert "nothing left" in runner.process_one(Creating([parent]), tmp_path, pilot_issue=None,
                                                codex_fallback=False, merge=True, triage=True)


def test_rejected_contract_blocks_at_once_with_its_reason(tmp_path, monkeypatch):
    reason = "allowed file context is truncated, redacted or not UTF-8: tests/test_big.py"
    result = tmp_path / "developer-result.json"
    result.write_text(json.dumps({"model_calls": 0, "codex_fallback_calls": 0,
                                  "claude_fallback_calls": 0, "reason": reason}), encoding="utf-8")
    assert runner._contract_rejection(result) == reason

    def reject(*_args, **_kwargs):
        raise runner.ContractRejected(f"Vertrag nicht ausführbar: {runner._contract_rejection(result)}")

    monkeypatch.setattr(runner, "_run_local_task", reject)
    pipeline = FakePipeline([_issue(63, READY, _contract(63))])
    with pytest.raises(PipelineError):
        runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False, merge=True)
    assert _gh(pipeline, "issue", "edit")[0][-1] == "agent:blocked"
    assert "tests/test_big.py" in _gh(pipeline, "issue", "comment")[0][-1]


def test_model_failures_and_ollama_outage_are_not_contract_rejections(tmp_path):
    result = tmp_path / "developer-result.json"
    for outcome in ({"model_calls": 1, "reason": "required files exceed the context budget"},
                    {"model_calls": 0, "reason": "LOCAL_QWEN_UNAVAILABLE"},
                    {"model_calls": 0, "reason": "snapshot drift: src/x.py; resume same task with fresh context"}):
        result.write_text(json.dumps(outcome), encoding="utf-8")
        assert runner._contract_rejection(result) is None


def test_triage_rejects_files_the_model_cannot_see_in_full(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_big.py").write_text("x = 1\n" * 6000, encoding="utf-8")
    answer = json.dumps({"decision": "ready", "reason": "klein", "objective": "Fix",
                         "allowed_paths": ["src/example.py", "tests/test_big.py"],
                         "tests": ["tests/test_big.py"]})
    result = issue_triage.parse_triage(answer, _issue(64), tmp_path)
    assert result["decision"] == "skip" and "32000" in result["reason"]
    assert issue_triage.parse_triage(answer, _issue(64))["decision"] == "ready"


def _check(name, conclusion, start="2026-10-12T22:56:14Z", end="2026-10-12T22:56:17Z"):
    return {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": conclusion,
            "startedAt": start, "completedAt": end}


def test_stale_pr_is_kept_when_actions_started_no_runner(tmp_path):
    no_runner = [_check("PR gate", "FAILURE"), _check("test", "FAILURE"), _check("TIM full suite", "FAILURE")]
    pr = {"baseRefName": "platform-main", "createdAt": "2026-10-12T10:00:00Z", "author": {"login": WORKER},
          "number": 7, "headRefName": "codex/issue-84-qwen", "mergeStateStatus": "BLOCKED",
          "statusCheckRollup": no_runner}
    ledger = IssueLedger(tmp_path / "l.json")
    ledger.start_attempt(84, "c")
    later = 1_791_800_000.0 + runner.STALE_PR_SECONDS
    pipeline = FakePipeline([], [pr])
    assert runner._maintain_worker_prs(pipeline, ledger, merge=True, now=later) == {84}
    assert not _gh(pipeline, "pr", "close") and not ledger.errors(84)
    # A real test failure after minutes still retires the stale PR.
    real = {**pr, "statusCheckRollup": [_check("PR gate", "SUCCESS"),
                                        _check("test", "FAILURE", end="2026-10-12T23:09:00Z")]}
    pipeline = FakePipeline([], [real])
    assert runner._maintain_worker_prs(pipeline, ledger, merge=True, now=later) == set()
    assert _gh(pipeline, "pr", "close")


def test_quick_pr_gate_failure_alone_is_not_an_outage():
    assert not runner._ci_unavailable({"statusCheckRollup": [_check("PR gate", "FAILURE")]})
    assert not runner._ci_unavailable({"statusCheckRollup": []})


def test_worker_prs_are_listed_without_checks_when_the_token_cannot_read_them(tmp_path):
    class NoStatusRead(FakePipeline):
        def github(self, *args):
            if args[:2] == ("pr", "list") and "statusCheckRollup" in args[-1]:
                self.calls.append(("gh",) + args)
                raise PipelineError("GraphQL: Resource not accessible by personal access token "
                                    "(search.nodes.0.statusCheckRollup)")
            return super().github(*args)

    pr = {"baseRefName": "platform-main", "createdAt": "2026-10-12T10:00:00Z", "author": {"login": WORKER},
          "number": 1, "headRefName": "codex/issue-80-qwen", "mergeStateStatus": "CLEAN"}
    pipeline = NoStatusRead([], [pr])
    covered = runner._maintain_worker_prs(pipeline, IssueLedger(tmp_path / "l.json"), merge=True,
                                          now=1_791_800_000.0)
    assert covered == {80}
    assert ("gh", "pr", "merge", "1", "--squash") in pipeline.calls
    assert "statusCheckRollup" not in _gh(pipeline, "pr", "list")[-1][-1]


def test_other_pr_list_errors_still_stop_the_run(tmp_path):
    class Broken(FakePipeline):
        def github(self, *args):
            if args[:2] == ("pr", "list"):
                raise PipelineError("HTTP 502")
            return super().github(*args)

    with pytest.raises(PipelineError, match="502"):
        runner._maintain_worker_prs(Broken([]), IssueLedger(tmp_path / "l.json"), merge=True)


def test_retired_pr_counts_an_attempt_without_deleting_the_branch_through_gh(tmp_path):
    ledger = IssueLedger(tmp_path / "l.json")
    ledger.start_attempt(90, "contract-a")
    pr = {"baseRefName": "platform-main", "createdAt": "2026-10-12T10:00:00Z", "author": {"login": WORKER},
          "number": 7, "headRefName": "codex/issue-90-qwen", "mergeStateStatus": "DIRTY"}
    pipeline = FakePipeline([], [pr])
    assert runner._maintain_worker_prs(pipeline, ledger, merge=True, now=1_791_800_000.0) == set()
    close = _gh(pipeline, "pr", "close")
    assert close and "--delete-branch" not in close[0]
    assert ledger.errors(90)


def test_self_update_says_why_it_skips_a_dirty_checkout(capsys):
    class Dirty(FakePipeline):
        def command(self, *args):
            return {("git", "rev-parse", "HEAD"): "a" * 40,
                    ("git", "rev-parse", "origin/platform-main"): "b" * 40,
                    ("git", "status", "--porcelain", "--untracked-files=no"): " M CLAUDE.md"}.get(args, "")

    assert runner.self_update(Dirty([])) is None
    assert "local changes: M CLAUDE.md" in capsys.readouterr().err


REAL_CI_JOB_RUNNING = runner.ci_job_running


def _big_file_answer(tmp_path, chars):
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "big.py").write_text("x" * chars, encoding="utf-8")
    return json.dumps({"decision": "ready", "reason": "groß", "objective": "Fix",
                       "allowed_paths": ["src/big.py", "tests/test_big_new.py"],
                       "tests": ["tests/test_big_new.py"]})


def test_triage_routes_files_only_the_server_model_can_see_to_agent_qwen_hard(tmp_path):
    answer = _big_file_answer(tmp_path, 40_000)
    hard = issue_triage.parse_triage(answer, _issue(80), tmp_path, allow_hard=True)
    assert hard["decision"] == "ready" and hard["hard"] is True
    assert issue_triage.ready_label(hard) == "agent:qwen-hard"
    assert "Server-Modell" in issue_triage.ready_comment(hard)
    assert issue_triage.parse_triage(answer, _issue(80), tmp_path)["decision"] == "skip"
    huge = _big_file_answer(tmp_path, 120_000)
    result = issue_triage.parse_triage(huge, _issue(80), tmp_path, allow_hard=True)
    assert result["decision"] == "skip" and "96000" in result["reason"]
    small = issue_triage.parse_triage(_big_file_answer(tmp_path, 1_000), _issue(80), tmp_path, allow_hard=True)
    assert small["hard"] is False and issue_triage.ready_label(small) == "agent:qwen-ready"
    assert "96000" in issue_triage.triage_prompt(_issue(80), allow_hard=True)
    assert "32000" in issue_triage.triage_prompt(_issue(80))


def test_triage_labels_large_file_issue_for_the_server_while_the_tunnel_answers(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    answer = _big_file_answer(repo, 40_000)
    monkeypatch.setattr(issue_triage, "ask_claude", lambda prompt, root: answer)
    monkeypatch.setattr(runner, "_hard_backend", lambda: ("http://127.0.0.1:11435", "qwen3-coder:30b"))
    pipeline = FakePipeline([_issue(81, body="groß")], repository=repo)
    assert "#81 prepared" in runner.process_one(pipeline, tmp_path / "state", pilot_issue=None,
                                                codex_fallback=False, merge=True, triage=True)
    assert _gh(pipeline, "issue", "edit")[0][-1] == "agent:qwen-hard,status:ready,priority:p1"


def test_hard_issue_waits_for_the_server_instead_of_spending_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_hard_backend", lambda: None)
    monkeypatch.setattr(runner, "_run_local_task", lambda *a, **k: pytest.fail("ran without server"))
    pipeline = FakePipeline([_issue(82, HARD, _contract(82))])
    assert runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False,
                              merge=True) == "No eligible Qwen issue (lane all)."
    assert not IssueLedger(tmp_path / "issue-ledger.json").entry(82).get("attempts")
    assert not _gh(pipeline, "issue", "edit")


@pytest.mark.parametrize("prior_attempt", [False, True])
def test_server_disappearing_after_selection_preserves_retry_budget(tmp_path, monkeypatch, prior_attempt):
    backend = iter([("http://127.0.0.1:11435", "qwen3-coder:30b"), None])
    monkeypatch.setattr(runner, "_hard_backend", lambda: next(backend))
    monkeypatch.setattr(runner, "_run_task_group", lambda *a, **k: pytest.fail("started Mac fallback"))
    monkeypatch.setattr(runner, "_clear_leftovers", lambda *a, **k: None)
    issue = _issue(82, HARD, _contract(82))
    ledger = IssueLedger(tmp_path / "issue-ledger.json")
    if prior_attempt:
        digest = issue_triage.contract_hash(build_task(issue))
        ledger.start_attempt(82, digest)
        ledger.record_failure(82, digest, "previous genuine model failure")
    before = dict(ledger.entry(82))
    pipeline = FakePipeline([issue])
    message = runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False, merge=False)
    assert "waiting for server model" in message
    assert IssueLedger(tmp_path / "issue-ledger.json").entry(82) == before
    assert not _gh(pipeline, "issue", "edit")
    assert not _gh(pipeline, "issue", "comment")
    assert not _gh(pipeline, "pr", "create")


def test_no_issue_job_starts_while_a_ci_job_runs_but_prs_are_still_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ci_job_running", lambda: True)
    monkeypatch.setattr(runner, "_run_local_task", lambda *a, **k: pytest.fail("ran during CI"))
    monkeypatch.setattr(issue_triage, "ask_claude", lambda *a: pytest.fail("triaged during CI"))
    pipeline = FakePipeline([_issue(83, READY, _contract(83)), _issue(84)])
    assert "paused" in runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False,
                                          merge=True, triage=True)
    assert _gh(pipeline, "pr", "list")
    assert "#83" in runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False,
                                       merge=True, dry_run=True)


def test_ci_job_detection(monkeypatch):
    class Done:
        def __init__(self, code):
            self.returncode = code

    monkeypatch.delenv("TIM_WORKER_CI_PAUSE", raising=False)
    monkeypatch.setattr(runner.subprocess, "run", lambda args, **kw: Done(0 if "Runner.Worker" in args else 1))
    assert REAL_CI_JOB_RUNNING() is True
    monkeypatch.setenv("TIM_WORKER_CI_PAUSE", "0")
    assert REAL_CI_JOB_RUNNING() is False
    monkeypatch.delenv("TIM_WORKER_CI_PAUSE")
    monkeypatch.setattr(runner.subprocess, "run", lambda args, **kw: Done(1))
    assert REAL_CI_JOB_RUNNING() is False

    def missing(*_a, **_k):
        raise FileNotFoundError("pgrep")

    monkeypatch.setattr(runner.subprocess, "run", missing)
    assert REAL_CI_JOB_RUNNING() is False


def test_hard_run_widens_file_limit_and_model_context(monkeypatch):
    from scripts import run_local_qwen_developer as developer
    from src.local_first import qwen_tool_loop

    monkeypatch.delenv("TIM_QWEN_HARD_RUN", raising=False)
    assert developer._writable_limit() == 32_000
    assert qwen_tool_loop.chat_options()["num_ctx"] == 32768
    monkeypatch.setenv("TIM_QWEN_HARD_RUN", "1")
    assert developer._writable_limit() == issue_triage.MAX_HARD_CONTEXT_FILE_CHARS
    assert qwen_tool_loop.chat_options()["num_ctx"] == 65536
    assert qwen_tool_loop.CHAT_OPTIONS["num_ctx"] == 32768


def test_failed_attempt_names_its_cause_for_the_blocked_comment(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_hard_backend", lambda: None)
    task = build_task(_issue(83, READY, _contract(83)))
    state = tmp_path / ".tim/local-first"

    def developer(*_args, **_kwargs):
        (state / "developer-results").mkdir(parents=True)
        (state / "developer-results" / "github-issue-83.json").write_text(json.dumps({
            "reason": "QWEN_REPAIR_EXHAUSTED:tool loop ended without a patch (budget) password=hunter2",
            "codex_fallback_error": "ProposalError", "codex_fallback_detail": "codex exited 1: usage limit",
            "claude_fallback_error": "ProposalError",
            "tool_loop": {"ended": "budget"}}), encoding="utf-8")
        return 2

    monkeypatch.setattr(runner, "_run_task_group", developer)
    with pytest.raises(PipelineError) as raised:
        runner._run_local_task(tmp_path, task, codex_fallback=True, claude_fallback=True)
    message = str(raised.value)
    assert message.startswith("acceptance gate not passed: exit=2")
    assert "codex=codex exited 1: usage limit" in message and "claude=ProposalError" in message
    assert "tool_loop=budget" in message and "hunter2" not in message


def test_failed_attempt_without_any_result_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_hard_backend", lambda: None)
    monkeypatch.setattr(runner, "_run_task_group", lambda *a, **k: 1)
    with pytest.raises(PipelineError, match="exit=1; no developer result"):
        runner._run_local_task(tmp_path, build_task(_issue(84, READY, _contract(84))), codex_fallback=False)


@pytest.mark.parametrize("field", ["codex_fallback_detail", "claude_fallback_detail", "reason"])
@pytest.mark.parametrize("message", [
    "Authorization: Bearer synthetic-credential-value-123456",
    "Authorization: Basic synthetic-credential-value-123456",
    '\"Authorization\": \"Bearer synthetic-credential-value-123456\"',
    'password="synthetic-credential-value-123456 with spaces"',
])
def test_failure_detail_scrubs_complete_credentials(tmp_path, field, message):
    result = tmp_path / "result.json"
    result.write_text(json.dumps({field: message}))
    detail = runner._failure_detail(2, result, tmp_path / "missing.json")
    assert "synthetic-credential" not in detail and "with spaces" not in detail
    assert "<REDACTED>" in detail


def test_failure_detail_scrubs_known_tokens_before_truncation(tmp_path):
    result = tmp_path / "result.json"
    result.write_text(json.dumps({"codex_fallback_detail": "x" * 65 + " ghp_" + "a" * 32}))
    detail = runner._failure_detail(2, result, tmp_path / "missing.json")
    assert "ghp_" not in detail


def test_worker_lane_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("TIM_WORKER_LANE", raising=False)
    assert runner.worker_lane() == "all"
    monkeypatch.setenv("TIM_WORKER_LANE", " Hard ")
    assert runner.worker_lane() == "hard"
    assert runner.worker_branch(12, "hard") == "codex/issue-12-qwen-hard"
    assert runner.worker_branch(12, "easy") == runner.worker_branch(12, "all") == "codex/issue-12-qwen"
    monkeypatch.setenv("TIM_WORKER_LANE", "fast")
    with pytest.raises(PipelineError):
        runner.worker_lane()


def test_each_lane_maintains_only_its_own_prs_but_respects_the_others(tmp_path):
    base = {"baseRefName": "platform-main", "createdAt": "2026-10-12T10:00:00Z",
            "author": {"login": WORKER}, "mergeStateStatus": "CLEAN"}
    prs = [{**base, "number": 1, "headRefName": "codex/issue-80-qwen"},
           {**base, "number": 2, "headRefName": "codex/issue-81-qwen-hard"}]
    now = 1_791_800_000.0
    for lane, mine in (("hard", "2"), ("easy", "1")):
        pipeline = FakePipeline([], prs)
        covered = runner._maintain_worker_prs(pipeline, IssueLedger(tmp_path / f"{lane}.json"),
                                              merge=True, now=now, lane=lane)
        assert covered == {80, 81}
        assert [call[3] for call in _gh(pipeline, "pr", "merge")] == [mine]


def test_hard_lane_takes_only_hard_issues_and_never_triages(tmp_path, monkeypatch):
    monkeypatch.setenv("TIM_WORKER_LANE", "hard")
    monkeypatch.setattr(issue_triage, "ask_claude", lambda prompt, root: pytest.fail("triaged"))
    pipeline = FakePipeline([_issue(90, READY, _contract(90)), _issue(91, body="offen")])
    assert runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False, merge=True,
                              triage=True) == "No eligible Qwen issue (lane hard)."
    pipeline = FakePipeline([_issue(90, READY, _contract(90)), _issue(92, HARD, _contract(92))])
    assert "#92 (lane hard)" in runner.process_one(pipeline, tmp_path, pilot_issue=None,
                                                    codex_fallback=False, merge=True, dry_run=True)


def test_easy_lane_skips_hard_issues_and_still_labels_them_in_triage(tmp_path, monkeypatch):
    monkeypatch.setenv("TIM_WORKER_LANE", "easy")
    pipeline = FakePipeline([_issue(93, HARD, _contract(93))])
    assert runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False,
                              merge=True, dry_run=True) == "No eligible Qwen issue (lane easy)."
    repo = tmp_path / "repo"
    repo.mkdir()
    answer = _big_file_answer(repo, 40_000)
    monkeypatch.setattr(issue_triage, "ask_claude", lambda prompt, root: answer)
    monkeypatch.setattr(runner, "_hard_backend", lambda: None)  # this Mac has no server tunnel
    pipeline = FakePipeline([_issue(94, body="groß")], repository=repo)
    assert "#94 prepared" in runner.process_one(pipeline, tmp_path / "state", pilot_issue=None,
                                                codex_fallback=False, merge=True, triage=True)
    assert _gh(pipeline, "issue", "edit")[0][-1] == "agent:qwen-hard,status:ready,priority:p1"
