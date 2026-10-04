import copy
import json
import subprocess
from pathlib import Path

import pytest

from scripts import auto_merge_controller as amc

ROOT = Path(__file__).resolve().parents[1]
REPO = "owner/repo"
SHA = "a" * 40
BASE_SHA = "b" * 40
POLICY = {
    "version": 1, "enabled": True, "dry_run": False, "base_branch": "platform-main", "worker_logins": ["tim-worker"],
    "head_branch_regex": "^claude/issue-[0-9]+-[a-z0-9-]+$",
    "required_checks": [{"name": "test", "workflow_path": ".github/workflows/ci.yml", "event": "pull_request"},
                        {"name": "TIM full suite", "workflow_path": ".github/workflows/tim-full-suite.yml",
                         "event": "pull_request"}],
    "check_app_slugs": ["github-actions"], "allowed_conclusions": ["success"], "merge_method": "squash",
    "max_merges_per_run": 1,
}


def make_pr(number=7, **over):
    pr = {"number": number, "node_id": "PR_abc", "state": "open", "merged": False, "draft": False, "mergeable": True,
          "mergeable_state": "clean", "user": {"login": "tim-worker"},
          "head": {"ref": f"claude/issue-{number}-fix", "sha": SHA, "repo": {"full_name": REPO}},
          "base": {"ref": "platform-main", "sha": BASE_SHA},
          "title": "ignored", "body": "ignored", "labels": []}
    pr.update(over)
    return pr


RUN_IDS = {"test": 101, "TIM full suite": 102, "codeql": 103, "PR gate": 104}


def run_ok(name, app="github-actions", run_id=None):
    run_id = RUN_IDS.get(name, 900) if run_id is None else run_id
    return {"name": name, "status": "completed", "conclusion": "success", "app": {"slug": app},
            "details_url": f"https://github.com/{REPO}/actions/runs/{run_id}/job/1"}


GOOD_RUNS = {
    101: {"path": ".github/workflows/ci.yml", "event": "pull_request", "head_sha": SHA, "head_repository": {"full_name": REPO}},
    102: {"path": ".github/workflows/tim-full-suite.yml", "event": "pull_request", "head_sha": SHA,
          "head_repository": {"full_name": REPO}},
}
GOOD_CHECKS = [run_ok("test"), run_ok("TIM full suite"), {**run_ok("codeql"), "app": {"slug": "github-advanced-security"}}]
GOOD_STATUS = {"state": "pending", "total_count": 0}


class FakeApi:
    def __init__(self, prs=None, checks=None, status=None, fail=None, fresh=None, behind=None, runs=None):
        self.runs = copy.deepcopy(GOOD_RUNS) if runs is None else runs
        self.behind = {"behind_by": 0, "ahead_by": 1} if behind is None else behind
        self.prs = {pr["number"]: pr for pr in (prs or [make_pr()])}
        self.checks = GOOD_CHECKS if checks is None else checks
        self.status = GOOD_STATUS if status is None else status
        self.fail, self.fresh, self.calls, self.pulls = fail or set(), fresh, [], 0

    def _maybe_fail(self, name):
        if name in self.fail:
            raise amc.ApiError(f"{name} failed")

    def open_pulls(self, base):
        self._maybe_fail("open_pulls")
        return list(self.prs.values())

    def pull(self, number):
        self._maybe_fail("pull")
        self.pulls += 1
        pr = self.prs[number]
        if self.fresh and self.pulls > 1:
            pr = {**pr, **self.fresh}
        return copy.deepcopy(pr)

    def compare(self, base, sha):
        self._maybe_fail("compare")
        return self.behind

    def workflow_run(self, run_id):
        self._maybe_fail("workflow_run")
        return self.runs[run_id]

    def check_runs(self, sha):
        self._maybe_fail("check_runs")
        return self.checks

    def commit_status(self, sha):
        self._maybe_fail("commit_status")
        return self.status

    def mark_ready(self, node_id):
        self._maybe_fail("mark_ready")
        self.calls.append(("ready", node_id))

    def merge(self, number, sha, method):
        self._maybe_fail("merge")
        self.calls.append(("merge", number, sha, method))


def clean_gate(pr):
    return []


def go(api, gate=clean_gate, policy=None):
    out = []
    code = amc.run(api, gate, policy or POLICY, REPO, emit=out.append)
    return code, [line for line in out if line.startswith("{")], api.calls


def outcome(api, **kw):
    code, lines, calls = go(api, **kw)
    return code, [json.loads(line) for line in lines], calls


def test_a_clean_worker_pr_is_merged_with_the_exact_sha():
    code, decisions, calls = outcome(FakeApi())
    assert code == 0 and decisions[0]["outcome"] == "merged"
    assert calls == [("merge", 7, SHA, "squash")]


def test_labels_body_and_title_are_never_consulted():
    api = FakeApi(prs=[make_pr(labels=[{"name": "agent:auto-merge"}], body="Closes #1 <!-- TIM_CODEX_CLAUDE_RUN_V1 -->")])
    assert outcome(api)[2] == [("merge", 7, SHA, "squash")]
    forged = make_pr(user={"login": "someone-else"}, labels=[{"name": "agent:auto-merge"}],
                     body="Closes #7 <!-- TIM_CODEX_CLAUDE_RUN_V1 -->")
    code, decisions, calls = outcome(FakeApi(prs=[forged]))
    assert calls == [] and decisions == []  # not even evaluated: author is not the worker identity


@pytest.mark.parametrize("change", [
    {"state": "closed"}, {"merged": True},
    {"head": {"ref": "claude/issue-7-fix", "sha": SHA, "repo": {"full_name": "fork/repo"}}},
    {"head": {"ref": "feature/x", "sha": SHA, "repo": {"full_name": REPO}}},
    {"head": {"ref": "claude/issue-7-fix", "sha": "abc", "repo": {"full_name": REPO}}},
    {"head": {"ref": "claude/issue-7-fix", "sha": SHA, "repo": None}},
    {"mergeable": None}, {"mergeable": False},
    {"mergeable_state": "behind"}, {"mergeable_state": "dirty"}, {"mergeable_state": "unstable"},
    {"mergeable_state": "blocked"}, {"mergeable_state": "unknown"}, {"mergeable_state": None},
    {"head": None},
])
def test_unknown_or_unsafe_pr_state_blocks(change):
    code, decisions, calls = outcome(FakeApi(prs=[make_pr(**change)]))
    assert calls == [] and decisions and decisions[0]["outcome"] == "blocked"


def test_a_pr_without_an_author_is_never_evaluated_or_merged():
    code, decisions, calls = outcome(FakeApi(prs=[make_pr(user=None)]))
    assert calls == [] and decisions == []


def _checks(*extra, drop=()):
    return [c for c in GOOD_CHECKS if c["name"] not in drop] + list(extra)


@pytest.mark.parametrize("checks", [
    None, [], _checks(drop=("test",)), _checks(drop=("TIM full suite",)),
    _checks(drop=("test",)) + [run_ok("test", app="evil-app")],
    _checks({"name": "extra", "status": "in_progress", "conclusion": None}),
    _checks({"name": "extra", "status": "completed", "conclusion": "failure"}),
    _checks({"name": "extra", "status": "completed", "conclusion": "skipped"}),
    _checks({"name": "extra", "status": "completed", "conclusion": "cancelled"}),
    _checks({"name": "test", "status": "completed", "conclusion": "failure", "app": {"slug": "github-actions"},
             "details_url": f"https://github.com/{REPO}/actions/runs/101/job/2"}),
    _checks({"name": "test", "status": "queued", "conclusion": None, "app": {"slug": "github-actions"},
             "details_url": f"https://github.com/{REPO}/actions/runs/101/job/2"}),
])
def test_missing_pending_failed_or_spoofed_checks_block(checks):
    api = FakeApi(checks=checks)
    if checks is None:
        api.check_runs = lambda sha: None
    code, decisions, calls = outcome(api)
    assert calls == [] and decisions[0]["outcome"] == "blocked"


def _blocked_with(api):
    code, decisions, calls = outcome(api)
    assert calls == [] and decisions[0]["outcome"] == "blocked"
    return " ".join(decisions[0]["reasons"])


def test_a_job_named_test_from_another_workflow_is_ambiguous_and_blocks():
    runs = copy.deepcopy(GOOD_RUNS)
    runs[777] = {"path": ".github/workflows/other.yml", "event": "pull_request", "head_sha": SHA,
                 "head_repository": {"full_name": REPO}}
    api = FakeApi(checks=_checks(run_ok("test", run_id=777)), runs=runs)
    assert "ambiguous" in _blocked_with(api)


@pytest.mark.parametrize("change, expected", [
    ({"path": ".github/workflows/other.yml"}, "expected"),
    ({"event": "push"}, "expected"),
    ({"event": "pull_request_target"}, "expected"),
    ({"head_sha": "c" * 40}, "another commit"),
    ({"head_repository": {"full_name": "fork/repo"}}, "different repository"),
    ({"head_repository": None}, "different repository"),
])
def test_required_checks_must_come_from_the_expected_workflow_for_this_head(change, expected):
    runs = copy.deepcopy(GOOD_RUNS)
    runs[101].update(change)
    assert expected in _blocked_with(FakeApi(runs=runs))


def test_a_check_that_cannot_be_attributed_to_a_run_of_this_repo_blocks():
    for url in ("", None, "https://github.com/evil/repo/actions/runs/101/job/1", "https://example.com/actions/runs/101/job/1",
                f"https://github.com/{REPO}/actions/runs/101"):
        checks = _checks({**run_ok("test"), "details_url": url}, drop=("test",))
        assert "attributed" in _blocked_with(FakeApi(checks=checks))


def test_an_unknown_workflow_run_or_an_api_error_while_resolving_runs_blocks():
    code, decisions, calls = outcome(FakeApi(runs={102: GOOD_RUNS[102]}))  # run 101 cannot be resolved
    assert calls == [] and decisions[0]["outcome"] == "blocked"
    api = FakeApi()
    api.workflow_run = lambda run_id: (_ for _ in ()).throw(amc.ApiError("boom"))
    code, decisions, calls = outcome(api)
    assert calls == [] and decisions[0]["outcome"] == "blocked"


def test_the_same_check_twice_from_the_expected_workflow_is_fine_but_one_failure_blocks():
    both = _checks(run_ok("test"))
    assert outcome(FakeApi(checks=both))[2] == [("merge", 7, SHA, "squash")]
    failing = _checks({**run_ok("test"), "conclusion": "failure"})
    assert outcome(FakeApi(checks=failing))[2] == []


@pytest.mark.parametrize("status", [None, {"state": "failure", "total_count": 1}, {"state": "pending", "total_count": 2}])
def test_bad_legacy_commit_statuses_block(status):
    api = FakeApi(status=status)
    if status is None:
        api.commit_status = lambda sha: None
    assert outcome(api)[2] == []


def test_gate_violations_and_gate_crashes_block():
    assert outcome(FakeApi(), gate=lambda pr: [".github/x: protected path"])[2] == []

    def boom(pr):
        raise RuntimeError("git exploded")

    code, decisions, calls = outcome(FakeApi(), gate=boom)
    assert calls == [] and decisions[0]["outcome"] == "blocked"


def test_head_moving_between_evaluation_and_merge_blocks():
    api = FakeApi(fresh={"head": {"ref": "claude/issue-7-fix", "sha": "c" * 40, "repo": {"full_name": REPO}}})
    code, decisions, calls = outcome(api)
    assert calls == [] and "changed during evaluation" in decisions[0]["reasons"][0]


def test_state_change_between_evaluation_and_merge_blocks():
    assert outcome(FakeApi(fresh={"mergeable_state": "behind"}))[2] == []
    assert outcome(FakeApi(fresh={"state": "closed"}))[2] == []


def test_merge_api_refusal_is_recorded_and_never_raises():
    code, decisions, calls = outcome(FakeApi(fail={"merge"}))
    assert code == 0 and decisions[0]["outcome"] == "blocked" and "ApiError" in decisions[0]["reasons"][0]


@pytest.mark.parametrize("behind", [{"behind_by": 1}, {"behind_by": 40}, {}, {"behind_by": None}, {"behind_by": "0"},
                                    {"behind_by": False}])
def test_a_head_that_is_behind_the_base_or_unknown_is_never_merged(behind):
    code, decisions, calls = outcome(FakeApi(behind=behind))
    assert calls == [] and "up to date" in decisions[0]["reasons"][0]


@pytest.mark.parametrize("name", ["pull", "compare", "check_runs", "commit_status"])
def test_api_errors_while_evaluating_block(name):
    code, decisions, calls = outcome(FakeApi(fail={name}))
    assert calls == [] and decisions[0]["outcome"] == "blocked"


def test_listing_failure_fails_the_run_and_merges_nothing():
    api = FakeApi(fail={"open_pulls"})
    out = []
    assert amc.run(api, clean_gate, POLICY, REPO, emit=out.append) == 1 and api.calls == []


def test_draft_is_marked_ready_first_and_merged_only_on_a_later_run():
    api = FakeApi(prs=[make_pr(draft=True, mergeable_state="draft")])
    code, decisions, calls = outcome(api)
    assert decisions[0]["outcome"] == "marked-ready" and calls == [("ready", "PR_abc")]
    assert not any(call[0] == "merge" for call in calls)


def test_dry_run_changes_nothing():
    code, decisions, calls = outcome(FakeApi(), policy={**POLICY, "dry_run": True})
    assert decisions[0]["outcome"] == "would-merge" and calls == []
    draft = FakeApi(prs=[make_pr(draft=True, mergeable_state="draft")])
    assert outcome(draft, policy={**POLICY, "dry_run": True})[1][0]["outcome"] == "would-mark-ready"


def test_disabled_policy_touches_nothing_at_all():
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"API used while disabled: {name}")

    out = []
    assert amc.run(Untouchable(), clean_gate, {**POLICY, "enabled": False}, REPO, emit=out.append) == 0
    assert "disabled" in out[0]


def test_empty_worker_list_means_no_pr_is_eligible():
    assert outcome(FakeApi(), policy={**POLICY, "worker_logins": []})[1] == []


def test_at_most_the_configured_number_of_merges_per_run():
    api = FakeApi(prs=[make_pr(7), make_pr(8)])
    code, decisions, calls = outcome(api)
    assert [call[1] for call in calls] == [7]


def test_other_authors_and_other_bases_are_not_evaluated():
    prs = [make_pr(7, user={"login": "human"}), make_pr(8, base={"ref": "main", "sha": BASE_SHA})]
    code, decisions, calls = outcome(FakeApi(prs=prs))
    assert decisions == [] and calls == []


def test_worker_login_comparison_ignores_case_only():
    assert outcome(FakeApi(prs=[make_pr(user={"login": "Tim-Worker"})]))[2] == [("merge", 7, SHA, "squash")]
    assert outcome(FakeApi(prs=[make_pr(user={"login": "tim-worker2"})]))[1] == []


# --- policy -------------------------------------------------------------------------------------------

def test_the_shipped_policy_is_inert():
    policy = amc.load_policy(ROOT / ".github" / "auto-merge-policy.json")
    assert policy["enabled"] is False and policy["dry_run"] is True and policy["worker_logins"] == []


@pytest.mark.parametrize("change", [
    {"enabled": "yes"}, {"dry_run": 1}, {"merge_method": "fast-forward"}, {"worker_logins": "bot"},
    {"required_checks": []}, {"required_checks": ["test"]}, {"required_checks": [{"name": "test"}]},
    {"required_checks": [{"name": "t", "workflow_path": "w", "event": "e"}, {"name": "t", "workflow_path": "x", "event": "e"}]},
    {"required_checks": [{"name": "t", "workflow_path": "w", "event": "e", "extra": "x"}]},
    {"check_app_slugs": []}, {"allowed_conclusions": []}, {"max_merges_per_run": 0},
    {"max_merges_per_run": 99}, {"max_merges_per_run": True}, {"head_branch_regex": "("}, {"base_branch": ""},
])
def test_invalid_policy_fails_closed(tmp_path, change):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({**POLICY, **change}))
    with pytest.raises(amc.ControllerError):
        amc.load_policy(path)


def test_missing_policy_key_or_file_fails_closed(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({k: v for k, v in POLICY.items() if k != "required_checks"}))
    with pytest.raises(amc.ControllerError):
        amc.load_policy(path)
    with pytest.raises(amc.ControllerError):
        amc.load_policy(tmp_path / "missing.json")


def test_main_with_disabled_policy_never_builds_an_api(tmp_path, capsys):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({**POLICY, "enabled": False}))
    assert amc.main(["--repo", "not a repo", "--policy", str(path), "--gate-policy", str(path)]) == 0
    assert "disabled" in capsys.readouterr().out
    path.write_text("{}")
    assert amc.main(["--repo", REPO, "--policy", str(path), "--gate-policy", str(path)]) == 1


# --- GhApi --------------------------------------------------------------------------------------------

class Gh:
    def __init__(self, replies):
        self.replies, self.argv = list(replies), []

    def __call__(self, argv, **kwargs):
        self.argv.append(argv)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return subprocess.CompletedProcess(argv, 0, stdout=reply, stderr="")


def test_merge_request_carries_the_sha_and_validates_inputs():
    gh = Gh(["{}"])
    amc.GhApi(REPO, gh).merge(7, SHA, "squash")
    assert gh.argv[0] == ["gh", "api", "-X", "PUT", "repos/owner/repo/pulls/7/merge", "-f", f"sha={SHA}",
                          "-f", "merge_method=squash"]
    api = amc.GhApi(REPO, Gh([]))
    for bad in (lambda: api.merge("7", SHA, "squash"), lambda: api.merge(7, "abc", "squash"),
                lambda: api.merge(7, SHA, "ff"), lambda: api.check_runs("../x"), lambda: api.pull(True),
                lambda: api.open_pulls("main; rm -rf /"), lambda: api.mark_ready("x y")):
        with pytest.raises(amc.ControllerError):
            bad()
    with pytest.raises(amc.ControllerError):
        amc.GhApi("not a repo")


def test_compare_request_uses_a_validated_range():
    gh = Gh([json.dumps({"behind_by": 0})])
    assert amc.GhApi(REPO, gh).compare("platform-main", SHA) == {"behind_by": 0}
    assert gh.argv[0] == ["gh", "api", f"repos/owner/repo/compare/platform-main...{SHA}"]
    with pytest.raises(amc.ControllerError):
        amc.GhApi(REPO, Gh([])).compare("a b", SHA)


def test_workflow_run_lookup_is_validated_and_check_runs_ask_for_the_latest():
    gh = Gh([json.dumps({"path": "p"}), json.dumps({"total_count": 0, "check_runs": []})])
    api = amc.GhApi(REPO, gh)
    assert api.workflow_run(101) == {"path": "p"}
    assert gh.argv[0] == ["gh", "api", "repos/owner/repo/actions/runs/101"]
    api.check_runs(SHA)
    assert "filter=latest" in gh.argv[1][2]
    for bad in ("101", 0, -1, True, "../x"):
        with pytest.raises(amc.ControllerError):
            amc.GhApi(REPO, Gh([])).workflow_run(bad)


def test_check_runs_are_paginated_and_incomplete_lists_are_refused():
    page1 = json.dumps({"total_count": 150, "check_runs": [run_ok(f"c{i}") for i in range(100)]})
    page2 = json.dumps({"total_count": 150, "check_runs": [run_ok(f"d{i}") for i in range(50)]})
    assert len(amc.GhApi(REPO, Gh([page1, page2])).check_runs(SHA)) == 150
    short = json.dumps({"total_count": 150, "check_runs": [run_ok("c")]})
    with pytest.raises(amc.ApiError):
        amc.GhApi(REPO, Gh([short])).check_runs(SHA)


def test_gh_failures_and_garbage_become_api_errors():
    with pytest.raises(amc.ApiError):
        amc.GhApi(REPO, Gh([subprocess.CalledProcessError(1, "gh", stderr="HTTP 403")])).pull(7)
    with pytest.raises(amc.ApiError):
        amc.GhApi(REPO, Gh(["not json"])).pull(7)
    with pytest.raises(amc.ApiError):
        amc.GhApi(REPO, Gh([OSError("gh missing")])).pull(7)
    with pytest.raises(amc.ApiError):
        amc.GhApi(REPO, Gh([json.dumps({"check_runs": "nope"})])).check_runs(SHA)


# --- gate integration with real git -------------------------------------------------------------------

def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_make_gate_runs_the_real_path_gate_on_the_fetched_head(tmp_path):
    origin, clone = tmp_path / "origin", tmp_path / "clone"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "platform-main")
    (origin / "src").mkdir()
    (origin / "src" / "a.py").write_text("x = 1\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "base")
    base = git(origin, "rev-parse", "HEAD")
    git(origin, "checkout", "-qb", "work")
    (origin / "src" / "a.py").write_text("x = 2\n")
    (origin / ".github").mkdir()
    (origin / ".github" / "evil.yml").write_text("a: b\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-qm", "work")
    head = git(origin, "rev-parse", "HEAD")
    git(origin, "update-ref", "refs/pull/7/head", head)
    git(origin, "checkout", "-q", "platform-main")
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    gate = amc.make_gate(clone, ROOT / ".github" / "pr-gate-policy.json")
    pr = make_pr(head={"ref": "claude/issue-7-fix", "sha": head, "repo": {"full_name": REPO}}, base={"ref": "platform-main", "sha": base})
    violations = gate(pr)
    assert any("protected path" in item for item in violations)
    wrong = {**pr, "head": {**pr["head"], "sha": "d" * 40}}
    assert gate(wrong) == ["fetched head differs from the evaluated head SHA"]
    assert gate({**pr, "head": {**pr["head"], "sha": "zz"}}) == ["malformed SHA"]
