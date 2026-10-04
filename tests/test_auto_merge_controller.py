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
    "required_statuses": [{"context": "pr-gate/head", "creator": "github-actions[bot]",
                           "workflow_path": ".github/workflows/pr-gate.yml", "event": "pull_request_target"}],
    "check_app_slugs": ["github-actions"], "allowed_conclusions": ["success"], "merge_method": "squash",
    "max_merges_per_run": 1, "require_rulesets": True, "require_app_token": True,
    "merger_app_id": 4242, "check_integration_id": 15368,
    "required_rulesets": [
        {"name": "platform-main merge conditions", "rules": ["deletion", "non_fast_forward", "pull_request",
                                                             "required_status_checks"], "bypass": "none"},
        {"name": "platform-main restrict updates", "rules": ["update"], "bypass": "merger_only"}],
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
    # pull_request_target runs carry the BASE commit, so only path and event of this run are compared
    104: {"path": ".github/workflows/pr-gate.yml", "event": "pull_request_target", "head_sha": BASE_SHA,
          "head_repository": {"full_name": REPO}},
}
GOOD_CHECKS = [run_ok("test"), run_ok("TIM full suite"), {**run_ok("codeql"), "app": {"slug": "github-advanced-security"}}]
def status_entry(context="pr-gate/head", state="success", creator="github-actions[bot]", run_id=104, url="auto"):
    url = f"https://github.com/{REPO}/actions/runs/{run_id}" if url == "auto" else url
    return {"context": context, "state": state, "creator": {"login": creator}, "target_url": url}


def status_of(*entries, state="success"):
    return {"state": state, "total_count": len(entries), "statuses": list(entries)}


GOOD_STATUS = status_of(status_entry())


def good_world():
    """(listing, details, effective rules) of a correctly configured pair of rulesets."""
    conditions = {"ref_name": {"include": ["refs/heads/platform-main"], "exclude": []}}
    merge = {"id": 11, "name": "platform-main merge conditions", "target": "branch", "source_type": "Repository",
             "enforcement": "active", "conditions": conditions, "bypass_actors": [],
             "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                       {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
                       {"type": "required_status_checks", "parameters": {
                           "strict_required_status_checks_policy": True,
                           "required_status_checks": [{"context": "test", "integration_id": 15368},
                                                      {"context": "TIM full suite", "integration_id": 15368},
                                                      {"context": "pr-gate/head", "integration_id": 15368}]}}]}
    update = {"id": 12, "name": "platform-main restrict updates", "target": "branch", "source_type": "Repository",
              "enforcement": "active", "conditions": copy.deepcopy(conditions),
              "bypass_actors": [{"actor_id": 4242, "actor_type": "Integration", "bypass_mode": "always"}],
              "rules": [{"type": "update"}]}
    listing = [{"id": ruleset["id"], "name": ruleset["name"]} for ruleset in (merge, update)]
    effective = [{**rule, "ruleset_id": ruleset["id"]} for ruleset in (merge, update) for rule in ruleset["rules"]]
    return listing, {11: merge, 12: update}, effective


GOOD_COMPARE = {"behind_by": 0, "ahead_by": 1, "merge_base_commit": {"sha": BASE_SHA}}


class FakeApi:
    def __init__(self, prs=None, checks=None, status=None, fail=None, fresh=None, behind=None, runs=None):
        self.runs = copy.deepcopy(GOOD_RUNS) if runs is None else runs
        self.behind = GOOD_COMPARE if behind is None else behind
        self.listing, self.details, self.effective = good_world()
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

    def rulesets(self):
        self._maybe_fail("rulesets")
        return self.listing

    def ruleset(self, ruleset_id):
        self._maybe_fail("ruleset")
        return self.details[ruleset_id]

    def branch_rules(self, base):
        self._maybe_fail("branch_rules")
        return self.effective

    def compare(self, base, sha):
        self._maybe_fail("compare")
        if isinstance(self.behind, list):  # successive answers: evaluation, then the check right before the merge
            return self.behind.pop(0) if len(self.behind) > 1 else self.behind[0]
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


def go(api, gate=clean_gate, policy=None, token_kind="app"):
    out = []
    code = amc.run(api, gate, policy or POLICY, REPO, emit=out.append, token_kind=token_kind)
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


@pytest.mark.parametrize("status", [
    None,
    status_of(),                                                                     # gate status missing
    status_of(status_entry(state="pending"), state="pending"),                       # still running
    status_of(status_entry(state="failure"), state="failure"),
    status_of(status_entry(state="error"), state="failure"),
    status_of(status_entry(creator="tim-worker")),                                   # spoofed by the worker identity
    status_of(status_entry(creator="github-actions")),                               # wrong login spelling
    status_of(status_entry(context="PR gate")),                                      # wrong context
    status_of(status_entry(), status_entry(state="failure"), state="failure"),       # duplicate context
    status_of(status_entry(), status_entry(creator="tim-worker")),                   # duplicate, one spoofed
    status_of(status_entry(), status_entry(context="other", state="failure"), state="failure"),
    status_of(status_entry(), status_entry(context="other", state="pending"), state="pending"),
    status_of(status_entry(url=None)), status_of(status_entry(url="")),
    status_of(status_entry(url="https://github.com/evil/repo/actions/runs/104")),
    status_of(status_entry(url=f"https://github.com/{REPO}/pull/7")),
    status_of(status_entry(run_id=999)),                                             # run that does not resolve
    {"state": "success", "total_count": 5, "statuses": [status_entry()]},            # truncated list
    {"state": "success", "total_count": 1, "statuses": "nope"},
])
def test_bad_missing_or_spoofed_commit_statuses_block(status):
    api = FakeApi(status=status)
    if status is None:
        api.commit_status = lambda sha: None
    code, decisions, calls = outcome(api)
    assert calls == [] and decisions[0]["outcome"] == "blocked"


@pytest.mark.parametrize("change", [{"path": ".github/workflows/other.yml"}, {"event": "pull_request"},
                                    {"event": "push"}])
def test_the_gate_status_must_come_from_the_gate_workflow(change):
    runs = copy.deepcopy(GOOD_RUNS)
    runs[104].update(change)
    assert "comes from" in _blocked_with(FakeApi(runs=runs))


def test_a_clean_gate_status_from_the_gate_workflow_is_accepted():
    assert outcome(FakeApi(status=status_of(status_entry())))[2] == [("merge", 7, SHA, "squash")]


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
                                    {"behind_by": False}, {"behind_by": 1, "merge_base_commit": {"sha": BASE_SHA}}])
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


def test_at_most_the_configured_number_of_would_merge_decisions_per_dry_run():
    api = FakeApi(prs=[make_pr(7), make_pr(8), make_pr(9)])
    code, decisions, calls = outcome(api, policy={**POLICY, "dry_run": True, "max_merges_per_run": 2})
    assert [d["pr"] for d in decisions] == [7, 8] and calls == []


def test_a_real_run_merges_at_most_one_pull_request():
    api = FakeApi(prs=[make_pr(7), make_pr(8)])
    code, decisions, calls = outcome(api)
    assert [call[1] for call in calls] == [7] and [d["pr"] for d in decisions] == [7]


def test_a_policy_for_real_merges_must_allow_exactly_one_merge_per_run(tmp_path):
    for value in (2, 3, 5):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({**POLICY, "max_merges_per_run": value}))
        with pytest.raises(amc.ControllerError, match="exactly one"):
            amc.load_policy(path)
    path.write_text(json.dumps({**POLICY, "dry_run": True, "max_merges_per_run": 3}))
    assert amc.load_policy(path)["max_merges_per_run"] == 3


def test_the_rulesets_are_read_again_right_before_the_merge():
    api = FakeApi()
    reads = []
    original = api.rulesets
    api.rulesets = lambda: (reads.append(1), original())[1]
    assert outcome(api)[2] == [("merge", 7, SHA, "squash")]
    assert len(reads) == 2, "once at the start of the run and once right before the merge"


def test_a_ruleset_that_changes_after_the_start_of_the_run_blocks_the_merge():
    api = FakeApi()
    original = api.rulesets
    state = {"calls": 0}

    def rulesets():
        state["calls"] += 1
        if state["calls"] == 2:  # between the start check and the merge someone adds a bypass to the merge conditions
            api.details[MERGE]["bypass_actors"] = [{"actor_id": 4242, "actor_type": "Integration", "bypass_mode": "always"}]
        return original()

    api.rulesets = rulesets
    code, decisions, calls = outcome(api)
    assert calls == [] and decisions[0]["outcome"] == "blocked" and "rulesets:" in decisions[0]["reasons"][0]


def test_a_ruleset_read_error_right_before_the_merge_blocks_it():
    api = FakeApi()
    original = api.ruleset
    state = {"calls": 0}

    def ruleset(ruleset_id):
        state["calls"] += 1
        if state["calls"] > 2:
            raise amc.ApiError("rate limited")
        return original(ruleset_id)

    api.ruleset = ruleset
    code, decisions, calls = outcome(api)
    assert calls == [] and decisions[0]["outcome"] == "blocked"


def test_the_dry_run_also_applies_the_guard_so_would_merge_means_it_would_pass():
    api = FakeApi()
    original = api.rulesets
    state = {"calls": 0}

    def rulesets():
        state["calls"] += 1
        if state["calls"] == 2:
            api.details[UPDATE]["bypass_actors"] = []
        return original()

    api.rulesets = rulesets
    code, decisions, calls = outcome(api, policy={**POLICY, "dry_run": True})
    assert decisions[0]["outcome"] == "blocked"


def test_other_authors_and_other_bases_are_not_evaluated():
    prs = [make_pr(7, user={"login": "human"}), make_pr(8, base={"ref": "main", "sha": BASE_SHA})]
    code, decisions, calls = outcome(FakeApi(prs=prs))
    assert decisions == [] and calls == []


def test_worker_login_comparison_ignores_case_only():
    assert outcome(FakeApi(prs=[make_pr(user={"login": "Tim-Worker"})]))[2] == [("merge", 7, SHA, "squash")]
    assert outcome(FakeApi(prs=[make_pr(user={"login": "tim-worker2"})]))[1] == []


# --- base race, branch rules, merger token -----------------------------------------------------------

def test_base_moving_between_evaluation_and_merge_blocks_the_merge():
    moved = {"behind_by": 1, "merge_base_commit": {"sha": BASE_SHA}}
    api = FakeApi(behind=[GOOD_COMPARE, moved])
    code, decisions, calls = outcome(api)
    assert calls == [] and "base branch moved" in decisions[0]["reasons"][0]
    other_base = {"behind_by": 0, "merge_base_commit": {"sha": "e" * 40}}
    assert outcome(FakeApi(behind=[GOOD_COMPARE, other_base]))[2] == []
    assert outcome(FakeApi(behind=[GOOD_COMPARE, {}]))[2] == []


def test_the_compare_is_repeated_right_before_the_merge():
    api = FakeApi(behind=[GOOD_COMPARE, GOOD_COMPARE])
    seen = []
    original = api.compare
    api.compare = lambda base, sha: (seen.append(sha), original(base, sha))[1]
    assert outcome(api)[2] == [("merge", 7, SHA, "squash")] and len(seen) == 2


def run_closed(api, policy=POLICY):
    out = []
    code = amc.run(api, clean_gate, policy, REPO, emit=out.append, token_kind="app")
    return code, out


def mutate(api, ruleset_id, fn):
    fn(api.details[ruleset_id])
    return api


MERGE, UPDATE = 11, 12


def status_rule(api):
    return next(rule for rule in api.details[MERGE]["rules"] if rule["type"] == "required_status_checks")["parameters"]


@pytest.mark.parametrize("name, fn", [
    # the reported flaw: a bypass actor on the ruleset that carries the mandatory checks
    ("merger app bypasses the merge conditions", lambda a: mutate(a, MERGE, lambda r: r.update(bypass_actors=[
        {"actor_id": 4242, "actor_type": "Integration", "bypass_mode": "always"}]))),
    ("any bypass on the merge conditions", lambda a: mutate(a, MERGE, lambda r: r.update(bypass_actors=[
        {"actor_id": 1, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]))),
    ("bypass list missing on the merge conditions", lambda a: mutate(a, MERGE, lambda r: r.pop("bypass_actors"))),
    ("bypass list null on the merge conditions", lambda a: mutate(a, MERGE, lambda r: r.update(bypass_actors=None))),
    ("no bypass actor on restrict updates", lambda a: mutate(a, UPDATE, lambda r: r.update(bypass_actors=[]))),
    ("bypass list missing on restrict updates", lambda a: mutate(a, UPDATE, lambda r: r.pop("bypass_actors"))),
    ("two bypass actors on restrict updates", lambda a: mutate(a, UPDATE, lambda r: r["bypass_actors"].append(
        {"actor_id": 9, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}))),
    ("wrong merger app id", lambda a: mutate(a, UPDATE, lambda r: r["bypass_actors"][0].update(actor_id=7))),
    ("merger bypass only for pull requests", lambda a: mutate(a, UPDATE, lambda r: r["bypass_actors"][0].update(
        bypass_mode="pull_request"))),
    ("merger is not an integration", lambda a: mutate(a, UPDATE, lambda r: r["bypass_actors"][0].update(
        actor_type="Team"))),
    ("restrict updates carries a mandatory rule", lambda a: mutate(a, UPDATE, lambda r: r["rules"].append(
        {"type": "pull_request", "parameters": {"required_approving_review_count": 0}}))),
    ("merge conditions lose a rule", lambda a: mutate(a, MERGE, lambda r: r.update(
        rules=[rule for rule in r["rules"] if rule["type"] != "deletion"]))),
    ("merge conditions gain a rule", lambda a: mutate(a, MERGE, lambda r: r["rules"].append({"type": "creation"}))),
    ("merge conditions not active", lambda a: mutate(a, MERGE, lambda r: r.update(enforcement="evaluate"))),
    ("merge conditions disabled", lambda a: mutate(a, MERGE, lambda r: r.update(enforcement="disabled"))),
    ("restrict updates not active", lambda a: mutate(a, UPDATE, lambda r: r.update(enforcement="evaluate"))),
    ("a tag ruleset", lambda a: mutate(a, MERGE, lambda r: r.update(target="tag"))),
    ("an organization ruleset", lambda a: mutate(a, MERGE, lambda r: r.update(source_type="Organization"))),
    ("other branch", lambda a: mutate(a, MERGE, lambda r: r["conditions"]["ref_name"].update(include=["refs/heads/main"]))),
    ("default-branch alias", lambda a: mutate(a, MERGE, lambda r: r["conditions"]["ref_name"].update(include=["~DEFAULT_BRANCH"]))),
    ("base branch excluded", lambda a: mutate(a, MERGE, lambda r: r["conditions"]["ref_name"].update(
        exclude=["refs/heads/platform-main"]))),
    ("two branches", lambda a: mutate(a, MERGE, lambda r: r["conditions"]["ref_name"].update(
        include=["refs/heads/platform-main", "refs/heads/x"]))),
    ("no conditions", lambda a: mutate(a, MERGE, lambda r: r.pop("conditions"))),
    ("not strict", lambda a: status_rule(a).update(strict_required_status_checks_policy=False)),
    ("strict missing", lambda a: status_rule(a).pop("strict_required_status_checks_policy")),
    ("strict as string", lambda a: status_rule(a).update(strict_required_status_checks_policy="true")),
    ("test not required", lambda a: status_rule(a).update(required_status_checks=[
        entry for entry in status_rule(a)["required_status_checks"] if entry["context"] != "test"])),
    ("full suite not required", lambda a: status_rule(a).update(required_status_checks=[
        entry for entry in status_rule(a)["required_status_checks"] if entry["context"] != "TIM full suite"])),
    ("gate status not required", lambda a: status_rule(a).update(required_status_checks=[
        entry for entry in status_rule(a)["required_status_checks"] if entry["context"] != "pr-gate/head"])),
    ("check bound to any app", lambda a: status_rule(a)["required_status_checks"][0].pop("integration_id")),
    ("check bound to another app", lambda a: status_rule(a)["required_status_checks"][0].update(integration_id=1)),
    ("no required checks at all", lambda a: status_rule(a).update(required_status_checks=[])),
    ("human approvals required", lambda a: mutate(a, MERGE, lambda r: next(
        rule for rule in r["rules"] if rule["type"] == "pull_request")["parameters"].update(
        required_approving_review_count=1))),
    ("approvals unknown", lambda a: mutate(a, MERGE, lambda r: next(
        rule for rule in r["rules"] if rule["type"] == "pull_request").pop("parameters"))),
    ("rule not effective on the branch", lambda a: a.effective.__setitem__(slice(None), [
        rule for rule in a.effective if not (rule["type"] == "deletion" and rule["ruleset_id"] == MERGE)])),
    ("effective rules come from another ruleset", lambda a: a.effective.__setitem__(slice(None), [
        {**rule, "ruleset_id": 99} for rule in a.effective])),
    ("ruleset missing from the listing", lambda a: a.listing.__setitem__(slice(None), a.listing[:1])),
    ("ruleset twice in the listing", lambda a: a.listing.append({"id": 13, "name": "platform-main merge conditions"})),
    ("listing empty", lambda a: a.listing.clear()),
    ("details missing", lambda a: a.details.pop(MERGE)),
])
def test_every_deviation_in_the_rulesets_blocks_everything(name, fn):
    api = _built(fn)
    code, out = run_closed(api)
    assert code == 1 and api.calls == [], name
    # either a precise ruleset finding or, when the data cannot even be read, a fail-closed message
    assert json.loads(out[0])["scope"] == "rulesets" if out[0].startswith("{") else "failed closed" in out[0], name


def _built(fn):
    api = FakeApi()
    result = fn(api)  # the lambdas mutate the fake and may return it (mutate helper) or an unrelated value
    return result if isinstance(result, FakeApi) else api


@pytest.mark.parametrize("failing", ["rulesets", "ruleset", "branch_rules"])
def test_the_403_for_missing_rulesets_fails_the_run_closed(failing):
    api = FakeApi(fail={failing})
    code, out = run_closed(api)
    assert code == 1 and api.calls == [] and "failed closed" in out[0]


@pytest.mark.parametrize("bad", [None, {}, "x", 5])
def test_unreadable_ruleset_answers_block_everything(bad):
    for attribute in ("listing", "details", "effective"):
        api = FakeApi()
        setattr(api, attribute, bad)
        if attribute == "details":
            api.ruleset = lambda ruleset_id: bad
        assert run_closed(api)[0] == 1 and api.calls == []


def test_extra_unrelated_rulesets_do_not_hurt_and_the_complete_pair_allows_the_merge():
    api = FakeApi()
    api.listing.append({"id": 50, "name": "something else"})
    api.effective.append({"type": "creation", "ruleset_id": 50})
    assert outcome(api)[2] == [("merge", 7, SHA, "squash")]


def test_the_rulesets_check_can_only_be_skipped_in_a_dry_run():
    api = FakeApi()
    api.listing.clear()
    dry = {**POLICY, "dry_run": True, "require_rulesets": False}
    assert outcome(api, policy=dry)[1][0]["outcome"] == "would-merge"
    code, decisions, calls = outcome(api, policy={**POLICY, "dry_run": True})  # required: stop before any PR
    assert code == 1 and decisions[0]["scope"] == "rulesets" and len(decisions) == 1


def test_the_verify_command_reports_without_touching_anything(tmp_path, capsys, monkeypatch):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({**POLICY, "dry_run": True}))
    good, bad = FakeApi(), FakeApi()
    mutate(bad, MERGE, lambda r: r.update(bypass_actors=[{"actor_id": 4242, "actor_type": "Integration", "bypass_mode": "always"}]))
    monkeypatch.setattr(amc, "GhApi", lambda repo: good)
    assert amc.main(["--repo", REPO, "--policy", str(path), "--gate-policy", str(path), "--verify-rulesets"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    monkeypatch.setattr(amc, "GhApi", lambda repo: bad)
    assert amc.main(["--repo", REPO, "--policy", str(path), "--gate-policy", str(path), "--verify-rulesets"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and "no bypass actors" in report["problems"][0]
    assert good.calls == [] and bad.calls == []


@pytest.mark.parametrize("kind", ["github-token", "unknown", "", "App"])
def test_real_merges_need_the_merger_app_token(kind):
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"API used without an app token: {name}")

    out = []
    assert amc.run(Untouchable(), clean_gate, POLICY, REPO, emit=out.append, token_kind=kind) == 1
    assert "App token" in out[0]
    assert outcome(FakeApi(), policy={**POLICY, "dry_run": True}, token_kind=kind)[1][0]["outcome"] == "would-merge"


def test_ruleset_requests_are_validated():
    gh = Gh([json.dumps([]), json.dumps({"id": 11}), json.dumps([])])
    api = amc.GhApi(REPO, gh)
    assert api.rulesets() == []
    assert gh.argv[0][2].startswith("repos/owner/repo/rulesets?includes_parents=true")
    assert api.ruleset(11) == {"id": 11} and gh.argv[1] == ["gh", "api", "repos/owner/repo/rulesets/11"]
    assert api.branch_rules("platform-main") == []
    assert gh.argv[2] == ["gh", "api", "repos/owner/repo/rules/branches/platform-main"]
    for bad in ("a/b", "x y"):
        with pytest.raises(amc.ControllerError):
            amc.GhApi(REPO, Gh([])).branch_rules(bad)
    for bad in ("11", 0, True, -3):
        with pytest.raises(amc.ControllerError):
            amc.GhApi(REPO, Gh([])).ruleset(bad)
    with pytest.raises(amc.ApiError):
        amc.GhApi(REPO, Gh([subprocess.CalledProcessError(1, "gh", stderr="Upgrade to GitHub Pro")])).rulesets()


def test_the_controller_workflow_is_manual_only_and_distinguishes_the_token_kind():
    text = (ROOT / ".github" / "workflows" / "auto-merge-controller.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "\n  schedule:" not in text and "pull_request" not in text and "push:" not in text
    assert "if: github.ref == 'refs/heads/platform-main'" in text
    assert "TIM_MERGER_TOKEN_KIND" in text and "create-github-app-token" in text
    assert "ref: platform-main" in text and "persist-credentials: false" not in text


# --- policy -------------------------------------------------------------------------------------------

def test_the_shipped_policy_is_inert():
    policy = amc.load_policy(ROOT / ".github" / "auto-merge-policy.json")
    assert policy["enabled"] is False and policy["dry_run"] is True and policy["worker_logins"] == []
    assert policy["require_rulesets"] is True and policy["require_app_token"] is True and policy["merger_app_id"] == 0


@pytest.mark.parametrize("change", [
    {"enabled": "yes"}, {"dry_run": 1}, {"merge_method": "fast-forward"}, {"worker_logins": "bot"},
    {"required_checks": []}, {"required_checks": ["test"]}, {"required_checks": [{"name": "test"}]},
    {"required_checks": [{"name": "t", "workflow_path": "w", "event": "e"}, {"name": "t", "workflow_path": "x", "event": "e"}]},
    {"required_checks": [{"name": "t", "workflow_path": "w", "event": "e", "extra": "x"}]},
    {"required_statuses": []}, {"required_statuses": ["pr-gate/head"]}, {"required_statuses": [{"context": "x"}]},
    {"required_statuses": [{"context": "c", "creator": "u", "workflow_path": "w", "event": "e"},
                           {"context": "c", "creator": "v", "workflow_path": "w", "event": "e"}]},
    {"dry_run": False, "require_rulesets": False}, {"dry_run": False, "require_app_token": False},
    {"dry_run": False, "merger_app_id": 0}, {"merger_app_id": -1}, {"merger_app_id": "4242"},
    {"check_integration_id": 0}, {"check_integration_id": None},
    {"require_rulesets": "yes"}, {"require_app_token": 1}, {"required_rulesets": []}, {"required_rulesets": "update"},
    {"required_rulesets": [{"name": "x", "rules": [], "bypass": "none"}]},
    {"required_rulesets": [{"name": "x", "rules": ["update"], "bypass": "everyone"}]},
    {"required_rulesets": [{"name": "x", "rules": ["update"]}]},
    # the mandatory rules must sit in rulesets without bypass: a merger-bypass ruleset may not carry them
    {"required_rulesets": [{"name": "a", "rules": ["pull_request", "required_status_checks", "non_fast_forward",
                                                   "deletion", "update"], "bypass": "merger_only"}]},
    {"required_rulesets": [{"name": "a", "rules": ["update"], "bypass": "merger_only"}]},
    {"required_rulesets": [{"name": "a", "rules": ["pull_request", "deletion"], "bypass": "none"},
                           {"name": "b", "rules": ["update"], "bypass": "merger_only"}]},
    {"required_rulesets": [{"name": "a", "rules": ["pull_request", "required_status_checks", "non_fast_forward",
                                                   "deletion"], "bypass": "none"},
                           {"name": "a", "rules": ["update"], "bypass": "merger_only"}]},
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


def test_the_documented_rulesets_satisfy_the_controllers_verification():
    policy = {**amc.load_policy(ROOT / ".github" / "auto-merge-policy.json"), "merger_app_id": 4242}
    docs = {}
    for name in ("merge-conditions", "restrict-updates"):
        ruleset = json.loads((ROOT / "docs" / "rulesets" / f"platform-main-{name}.json").read_text(encoding="utf-8"))
        for actor in ruleset["bypass_actors"]:
            assert actor["actor_id"] == 0  # placeholder to be replaced by the merger app id on import
            actor["actor_id"] = 4242
        docs[name] = ruleset
    merge, update = docs["merge-conditions"], docs["restrict-updates"]
    assert merge["bypass_actors"] == [], "the ruleset that makes the checks mandatory must have no bypass actor"
    assert len(update["bypass_actors"]) == 1 and update["bypass_actors"][0]["actor_type"] == "Integration"
    assert [rule["type"] for rule in update["rules"]] == ["update"]
    details, listing, effective = {}, [], []
    for number, ruleset in ((11, merge), (12, update)):
        details[number] = {**ruleset, "id": number, "source_type": "Repository"}
        listing.append({"id": number, "name": ruleset["name"]})
        effective += [{**rule, "ruleset_id": number} for rule in ruleset["rules"]]
    assert amc.rulesets_blockers(listing, details, effective, policy) == []
    checks = next(rule for rule in merge["rules"] if rule["type"] == "required_status_checks")["parameters"]
    assert {entry["context"] for entry in checks["required_status_checks"]} == \
        {spec["name"] for spec in policy["required_checks"]} | {spec["context"] for spec in policy["required_statuses"]}


def test_commit_status_request_asks_for_a_full_page():
    gh = Gh([json.dumps(status_of())])
    amc.GhApi(REPO, gh).commit_status(SHA)
    assert gh.argv[0] == ["gh", "api", f"repos/owner/repo/commits/{SHA}/status?per_page=100"]


def test_the_gate_workflow_reports_exactly_the_status_the_policy_requires():
    policy = amc.load_policy(ROOT / ".github" / "auto-merge-policy.json")
    text = (ROOT / ".github" / "workflows" / "pr-gate.yml").read_text(encoding="utf-8")
    spec = policy["required_statuses"][0]
    assert f"context={spec['context']}" in text and spec["workflow_path"] == ".github/workflows/pr-gate.yml"
    assert "pull_request_target:" in text and spec["event"] == "pull_request_target"
    assert "statuses: write" in text and "state=pending" in text
    assert "if: always()" in text and "continue-on-error: true" in text and "if: steps.gate.outcome != 'success'" in text
    for forbidden in ("github.event.pull_request.title", "github.event.pull_request.body", "head_commit.message"):
        assert forbidden not in text  # no PR-controlled text in status descriptions or commands


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
