import json
from pathlib import Path

import pytest

from scripts.github_issue_pipeline import Candidate, CommandRunner, EXCLUDED_LABELS, Pipeline, PipelineError, analysis_prompt, choose_candidate, claude_prompt, dependency_numbers


def issue(number, *, labels=(), body="", updated_at="2026-09-27T10:00:00Z", state="open"):
    return {"number": number, "title": f"Issue {number}", "state": state, "labels": [{"name": label} for label in labels], "body": body, "updatedAt": updated_at, "url": f"https://example.test/{number}"}


def test_dependency_parser_only_reads_dependency_lines():
    assert dependency_numbers("Mentions #99\nDepends on: #12 and #13\nBlocked by #14") == frozenset({12, 13, 14})


def test_chooses_p0_before_p1_then_oldest_update():
    selected = choose_candidate([
        issue(2, labels=("priority:p1", "status:ready"), updated_at="2026-09-01T00:00:00Z"),
        issue(3, labels=("priority:p0", "status:ready"), updated_at="2026-09-10T00:00:00Z"),
        issue(4, labels=("priority:p0", "status:ready"), updated_at="2026-09-02T00:00:00Z"),
    ], mode="production")
    assert selected and selected.number == 4


def test_open_dependency_and_epic_are_never_selected():
    selected = choose_candidate([
        issue(11, labels=("status:active",)),
        issue(68, labels=("priority:p0", "status:ready"), body="Blocked by: #11"),
        issue(69, labels=("priority:p0", "status:ready", "type:epic")),
    ], mode="production")
    assert selected is None


def test_blocked_label_is_excluded_but_explicit_retry_can_resume():
    blocked = issue(1, labels=("priority:p0", "status:ready", "agent:blocked"))
    retry = issue(2, labels=("priority:p1", "status:ready", "agent:blocked", "agent:retry"))
    selected = choose_candidate([blocked, retry], mode="production")
    assert selected and selected.number == 2
    assert "agent:blocked" in EXCLUDED_LABELS


def test_retry_never_overrides_a_real_blocker_or_epic():
    selected = choose_candidate([
        issue(1, labels=("priority:p0", "status:ready", "agent:blocked", "agent:retry", "type:epic")),
        issue(2, labels=("priority:p0", "status:ready", "agent:blocked", "agent:retry", "ci-blocked")),
    ], mode="production")
    assert selected is None


def test_pilot_mode_requires_explicit_pilot_label():
    regular = issue(1, labels=("priority:p0", "status:ready"))
    pilot = issue(2, labels=("priority:p1", "status:ready", "agent:pilot"))
    assert choose_candidate([regular, pilot]).number == 2
    assert choose_candidate([regular]) is None


def test_github_uppercase_open_state_is_eligible():
    candidate = issue(1, labels=("priority:p0", "status:ready", "agent:pilot"), state="OPEN")
    assert choose_candidate([candidate]).number == 1


def test_analysis_command_uses_only_supported_exec_options(tmp_path):
    class Runner(CommandRunner):
        def run(self, args, **_):
            if args[0] == "git":
                return "abc123"
            if args[0] == "codex":
                assert "-a" not in args
                output = Path(args[args.index("--output-last-message") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("## Problem\nTest", encoding="utf-8")
                return ""
            return ""

    pipeline = Pipeline(Path("."), tmp_path, Runner())
    assert pipeline.run_analysis(Candidate(1, "Pilot", "", frozenset(), "", ""), "run", "origin/platform-main") == "## Problem\nTest"


def test_recovery_creates_a_draft_only_for_an_existing_remote_branch(tmp_path):
    class Runner(CommandRunner):
        def __init__(self):
            self.calls = []

        def run(self, args, **_):
            args = list(args)
            self.calls.append(args)
            if args[:3] == ["gh", "pr", "list"]:
                return "[]" if sum(call[:3] == ["gh", "pr", "list"] for call in self.calls) == 1 else '[{"number": 2, "url": "https://example.test/pr/2"}]'
            if args[:3] == ["git", "ls-remote", "--heads"]:
                return "abc refs/heads/claude/issue-1-pilot"
            return ""

    runner = Runner()
    result = Pipeline(Path("."), tmp_path, runner).ensure_draft_pr(Candidate(1, "Pilot", "", frozenset(), "", ""), "claude/issue-1-pilot")
    assert result and result["number"] == 2
    assert ["gh", "pr", "create"] == next(call[:3] for call in runner.calls if call[:3] == ["gh", "pr", "create"])


def test_prompts_contain_strict_handoff_and_no_merge_authority():
    candidate = Candidate(7, "Fix race", "Body", frozenset(), "2026-01-01T00:00:00Z", "")
    analysis = analysis_prompt(candidate, "abc123")
    implementation = claude_prompt(candidate, "## Problem\nRace", "claude/issue-7-fix-race")
    assert "Work read-only" in analysis
    assert "never describe that PR as out of scope" in analysis
    assert "exactly these headings" in analysis
    assert "DRAFT PR" in implementation
    assert "Never merge" in implementation
    assert "TIM_CODEX_CLAUDE_RUN_V1" in implementation


def test_prerequisites_fail_closed_when_claude_is_not_logged_in(monkeypatch, tmp_path):
    class Runner(CommandRunner):
        def run(self, args, **_):
            if list(args[:3]) == ["claude", "auth", "status"]:
                return json.dumps({"loggedIn": False})
            return ""

    monkeypatch.setattr("scripts.github_issue_pipeline.shutil.which", lambda _: "/bin/tool")
    with pytest.raises(PipelineError, match="not logged in"):
        Pipeline(Path("."), tmp_path, Runner()).ensure_prerequisites()


@pytest.mark.parametrize("change", [
    {"statusCheckRollup": []},
    {"statusCheckRollup": [{"name": "TIM full suite", "conclusion": "FAILURE"}]},
    {"baseRefName": "main"},
    {"headRefName": "other/issue-7-fix"},
    {"body": "Closes #7"},
    {"mergeable": "CONFLICTING"},
    {"mergeStateStatus": "BEHIND"},
    {"labels": []},
])
def test_merge_gate_rejects_missing_evidence(tmp_path, change):
    runner = MergeRunner(change)
    assert Pipeline(Path("."), tmp_path, runner).merge_ready_prs() == 0
    assert not any(call[:3] == ["gh", "pr", "merge"] for call in runner.calls)


class MergeRunner(CommandRunner):
    def __init__(self, change=None):
        self.calls = []
        self.change = change or {}

    def run(self, args, **_):
        args = list(args)
        self.calls.append(args)
        if args[:3] == ["gh", "pr", "list"]:
            return '[{"number": 12}]'
        if args[:3] == ["gh", "pr", "view"]:
            pr = {"number": 12, "body": "Closes #7\n<!-- TIM_CODEX_CLAUDE_RUN_V1 -->",
                  "baseRefName": "platform-main", "headRefName": "claude/issue-7-fix",
                  "headRefOid": "abc123", "isDraft": True, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
                  "statusCheckRollup": [{"name": "TIM full suite", "conclusion": "SUCCESS"}],
                  "labels": [{"name": "agent:auto-merge"}]}
            pr.update(self.change)
            return json.dumps(pr)
        if args[:3] == ["gh", "repo", "view"]:
            return '{"defaultBranchRef":{"name":"platform-main"}}'
        return ""


def test_merge_gate_readies_and_merges_matching_head_only(tmp_path):
    runner = MergeRunner()
    assert Pipeline(Path("."), tmp_path, runner).merge_ready_prs() == 1
    assert ["gh", "pr", "ready", "12"] in runner.calls
    assert ["gh", "pr", "merge", "12", "--squash", "--match-head-commit", "abc123"] in runner.calls
