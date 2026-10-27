from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
import plistlib
from pathlib import Path

import pytest

from src.operational import dashboard_refresh as dr

ROOT = Path(__file__).resolve().parents[1]
LIVE_POLICY = dr.load_policy(ROOT / "ops/dashboard_refresh/policy.json")
# The restart-interval logic is tested with distinct values (60 min, 20 min display-only);
# the live values are checked separately in test_live_policy_intervals.
POLICY = {**LIVE_POLICY, "min_minutes_between_runtime_restarts": 60, "min_minutes_between_runtime_restarts_display_only": 20}
# The S-K study as it held deploys before Uzi released it (24.10.): the hold mechanism stays tested.
STUDY_POLICY = {**POLICY, "studies": [{key: value for key, value in POLICY["studies"][0].items()
                                       if not key.startswith("released")}]}
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
GREEN = {"status": "completed", "conclusion": "success", "completed_at_utc": "2026-10-24T11:00:00Z", "url": "u", "id": 7}


def decide(**overrides):
    values = dict(deployed="a", target="b", is_fast_forward=True, ci=GREEN, busy=[], dirty=[], campaign_active=False,
                  last_restart_at=None, now=NOW, min_minutes_between_restarts=60, blockers={}, failed_targets=[],
                  paused=False)
    values.update(overrides)
    return dr.decide(**values)


def test_green_fast_forward_deploys():
    decision = decide()
    assert (decision.action, decision.details) == ("DEPLOY", {"from": "a", "to": "b"})


@pytest.mark.parametrize("overrides,action,reason", [
    ({"paused": True, "campaign_active": True}, "HOLD", "paused"),
    ({"target": None}, "HOLD", "fetch_failed"),
    ({"campaign_active": True, "target": "a"}, "HOLD", "campaign_active"),
    ({"target": "a"}, "UP_TO_DATE", "up_to_date"),
    ({"is_fast_forward": False}, "HOLD", "not_fast_forward"),
    ({"failed_targets": ["b"]}, "HOLD", "previous_attempt_failed"),
    ({"ci": None}, "WAIT", "ci_pending"),
    ({"ci": {**GREEN, "status": "in_progress", "conclusion": None}}, "WAIT", "ci_pending"),
    ({"ci": {**GREEN, "conclusion": "failure"}}, "HOLD", "ci_failed"),
    ({"blockers": {"S": ["src/orderflow/observations.py"]}}, "HOLD", "study_protected_paths"),
    ({"dirty": ["main.py"]}, "HOLD", "local_changes"),
    ({"busy": ["ci_test_job"]}, "WAIT", "busy"),
    ({"last_restart_at": NOW - timedelta(minutes=59)}, "WAIT", "restart_interval"),
])
def test_every_stop_blocks_the_deploy(overrides, action, reason):
    decision = decide(**overrides)
    assert (decision.action, decision.reason) == (action, reason)
    assert decision.to_dict()["text"]


def test_restart_interval_allows_after_the_limit():
    assert decide(last_restart_at=NOW - timedelta(minutes=61)).action == "DEPLOY"


def test_ci_job_only_defers_the_restart_for_a_bounded_time():
    first = decide(deferred=["ci_test_job"], deferred_since=None, max_defer_minutes=20)
    assert (first.action, first.reason) == ("WAIT", "busy_deferred")
    assert first.details["deferred_since_utc"] == dr.iso(NOW)
    assert first.details["deploy_at_latest_utc"] == dr.iso(NOW + timedelta(minutes=20))
    expected = (NOW + timedelta(minutes=20)).astimezone().strftime("%H:%M")  # Mac local time, not UTC
    assert f"Spätestens {expected} Uhr." in first.to_dict()["text"]
    still = decide(deferred=["ci_test_job"], deferred_since=NOW - timedelta(minutes=19), max_defer_minutes=20)
    assert still.reason == "busy_deferred"
    overdue = decide(deferred=["ci_test_job"], deferred_since=NOW - timedelta(minutes=20), max_defer_minutes=20)
    assert overdue.action == "DEPLOY"
    # a backup is never deferred, it blocks
    assert decide(busy=["db_backup"], deferred=["ci_test_job"], deferred_since=NOW - timedelta(hours=1),
                  max_defer_minutes=20).reason == "busy"


def test_study_hold_names_the_files_and_wins_over_pending_ci():
    hold = decide(ci=None, blockers={"S": ["main.py", "src/a.py", "src/b.py", "src/c.py"]})
    assert hold.reason == "study_protected_paths"
    assert hold.to_dict()["text"].endswith("Hält zurück: main.py, src/a.py, src/b.py (+1).")
    partial = decide(held_back={"target": "d", "commits": 2, "blocked_files": {"S": ["main.py"]}})
    assert partial.action == "DEPLOY"
    assert "2 neuere Commits warten wegen main.py" in partial.to_dict()["text"]


def test_display_only_and_default_rules_are_shared_by_studies():
    assert dr.display_only(POLICY, ["src/dashboard/x.py", "docs/a.md", "tests/t.py"])
    assert not dr.display_only(POLICY, ["src/dashboard/x.py", "main.py"])
    assert dr.display_only(POLICY, [])  # empty diff counts as display-only
    own = {"id": "X", "display_safe_prefixes": ["only/"]}
    assert dr.display_rules(POLICY, own)["display_safe_prefixes"] == ["only/"]
    assert dr.display_rules(POLICY, own)["display_safe_files"] == []
    assert dr.display_rules(STUDY_POLICY, STUDY_POLICY["studies"][0]) == dr.display_rules(POLICY)


def test_furthest_unblocked_picks_the_newest_clean_ancestor():
    studies = dr.active_studies(STUDY_POLICY, NOW, lambda path: False)
    diffs = {"b": ["docs/a.md"], "c": ["docs/a.md", "main.py"], "d": ["docs/a.md", "main.py", "src/dashboard/x.py"]}
    assert dr.furthest_unblocked(["b", "c", "d"], diffs.__getitem__, studies) == ("b", {"V2_SK_CONTROL_REGIME_V1": ["main.py"]})
    assert dr.furthest_unblocked(["c", "d"], diffs.__getitem__, studies) == (None, {"V2_SK_CONTROL_REGIME_V1": ["main.py"]})
    assert dr.furthest_unblocked(["b"], diffs.__getitem__, studies) == ("b", {})
    assert dr.same_tree("t1", {"x": "t1", "y": "t2", "z": None}) == ["x"]


def test_campaign_beats_ci_and_up_to_date_is_not_a_hold_reason():
    assert decide(campaign_active=True, ci=None).reason == "campaign_active"


def test_sk_study_lets_only_display_changes_through():
    studies = dr.active_studies(STUDY_POLICY, NOW, lambda path: False)
    assert [study["id"] for study in studies] == ["V2_SK_CONTROL_REGIME_V1"]
    safe = ["src/dashboard/operations.py", "docs/x.md", "tests/test_x.py", "tools/mac-worker-dashboard/src/main.rs",
            "src/orderflow/README.md", "artifacts/v2_completion/sk_t0_record.json", "scripts/dashboard_refresh.py",
            "src/v2_completion/sk_report.py", "src/v2_completion/control_regime_study.py", "scripts/sk_study.py",
            "ops/launchd/com.tim.dashboard-refresh.plist", "LICENSE", "NOTICE"]
    assert dr.study_blockers(studies, safe) == {}
    unsafe = ["src/orderflow/observations.py", "main.py", "config/settings.py", "scripts/tim_history_recovery.py",
              "requirements.txt", "ops/launchd/com.tim.runtime.plist", "src/v2_completion/mac_live.py",
              "src/sources/goathub_discord.py", "LICENSE.py", "docs_LICENSE"]
    assert dr.study_blockers(studies, safe + unsafe) == {"V2_SK_CONTROL_REGIME_V1": sorted(unsafe)}


def test_study_ends_with_marker_and_does_not_start_early():
    assert dr.active_studies(STUDY_POLICY, NOW, lambda path: path.endswith("sk_end_record.json")) == []
    assert dr.active_studies(STUDY_POLICY, datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc), lambda path: False) == []


def test_released_study_no_longer_holds_deploys():
    released = datetime(2026, 10, 24, 23, 30, 5, tzinfo=timezone.utc)
    assert [study["id"] for study in dr.active_studies(POLICY, released - timedelta(seconds=1), lambda path: False)] == [
        "V2_SK_CONTROL_REGIME_V1"]
    assert dr.active_studies(POLICY, released, lambda path: False) == []
    assert POLICY["studies"][0]["released_by"] == "Uzi"


def test_pytest_counts_reads_last_summary_line():
    log = "2026 ... 3 passed in 1.0s\nnoise\n2026 = 6114 passed, 49 skipped, 2 warnings in 1934.20s (0:32:14) =\n"
    assert dr.pytest_counts(log) == {"passed": 6114, "failed": 0, "skipped": 49}
    assert dr.pytest_counts("2 failed, 10 passed, 1 error in 3s") == {"passed": 10, "failed": 3, "skipped": 0}
    assert dr.pytest_counts("no summary") == {}


def test_pick_check_run_takes_newest_named_run():
    payload = {"check_runs": [
        {"name": "codeql", "status": "completed", "conclusion": "skipped", "started_at": "2026-10-24T10:00:00Z"},
        {"id": 1, "name": "test", "status": "completed", "conclusion": "failure", "started_at": "2026-10-24T09:00:00Z"},
        {"id": 2, "name": "test", "status": "completed", "conclusion": "success", "started_at": "2026-10-24T10:00:00Z",
         "completed_at": "2026-10-24T10:30:00Z", "html_url": "h"},
    ]}
    assert dr.pick_check_run(payload, "test") == {"id": 2, "status": "completed", "conclusion": "success",
                                                  "completed_at_utc": "2026-10-24T10:30:00Z", "url": "h"}
    assert dr.pick_check_run({"check_runs": []}, "test") is None


def test_skipped_scheduled_run_does_not_hide_the_green_push_run():
    payload = {"check_runs": [
        {"id": 1, "name": "test", "status": "completed", "conclusion": "success", "started_at": "2026-10-26T00:40:00Z",
         "completed_at": "2026-10-26T00:44:00Z", "html_url": "push"},
        {"id": 2, "name": "test", "status": "completed", "conclusion": "skipped", "started_at": "2026-10-26T07:58:00Z",
         "completed_at": "2026-10-26T07:58:00Z", "html_url": "schedule"},
    ]}
    assert dr.pick_check_run(payload, "test")["url"] == "push"
    only_skipped = {"check_runs": [payload["check_runs"][1]]}
    assert dr.pick_check_run(only_skipped, "test")["conclusion"] == "skipped"  # still not green


def test_small_parsers():
    assert dr.parse_porcelain(" M docs/TIM_V1_LIVE_STATUS.md\n M main.py\n", ["docs/TIM_V1_LIVE_STATUS.md"]) == ["main.py"]
    ps = "/Users/timrunner/actions-runner/bin/Runner.Worker spawnclient 1 2\npython scripts/dashboard_refresh.py pg_dump\n"
    assert dr.busy_processes(ps, POLICY["busy_process_patterns"]) == []
    assert dr.busy_processes(ps, POLICY["deferrable_process_patterns"]) == ["ci_test_job"]
    assert dr.busy_processes(ps + "/usr/bin/pg_dump tim\n", POLICY["busy_process_patterns"]) == ["db_backup"]
    assert dr.launchd_pid("state = running\n\tpid = 4242\n") == 4242
    assert dr.launchd_pid("state = not running\n") is None


# ---------- end to end against a real git repository, everything else faked ----------

def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class Mac:
    """Fake gh, ps, launchctl, timctl and helper scripts; git runs for real."""

    def __init__(self, root: Path):
        self.root = root
        self.ci = {"status": "completed", "conclusion": "success"}
        self.ci_by_sha: dict[str, dict | None] = {}  # sha prefix -> check-run fields, None = no run at all
        self.pulls_by_sha: dict[str, list[str]] = {}  # merge/squash sha -> PR head shas
        self.ps = ""
        self.pid = 100
        self.restart_ok = True
        self.health_ok = True
        self.calls: list[list[str]] = []
        self.issues: list[dict] = []  # gh issue create/comment calls with the body file's text

    def __call__(self, command, *, cwd=None, timeout=120, env=None):
        command = [str(part) for part in command]
        self.calls.append(command)
        done = lambda out="", code=0: subprocess.CompletedProcess(command, code, out, "")  # noqa: E731
        if command[0] == "git":
            return subprocess.run(command, capture_output=True, text=True, check=False)
        if command[0].endswith("gh") and command[1] == "issue":
            body = Path(command[command.index("--body-file") + 1]).read_text()
            self.issues.append({"command": command[2], "args": command[3:], "body": body})
            if command[2] == "create":
                return done(f"https://github.com/o/r/issues/{500 + len(self.issues)}\n")
            return done()
        if command[0].endswith("gh"):
            endpoint = command[2]
            if endpoint.endswith("/logs"):
                return done("== 10 passed, 2 skipped in 5.0s ==")
            sha = endpoint.split("/commits/")[1].split("/")[0] if "/commits/" in endpoint else ""
            if "/git/commits/" in endpoint:  # GitHub knows every pushed commit, the live clone does not
                tree = git(getattr(self, "origin", self.root), "rev-parse", f"{sha}^{{tree}}")
                return done(json.dumps({"sha": sha, "tree": {"sha": tree}}))
            if endpoint.endswith("/pulls?per_page=10"):
                heads = next((v for k, v in self.pulls_by_sha.items() if sha.startswith(k)), [])
                return done(json.dumps([{"number": i + 1, "head": {"sha": head}} for i, head in enumerate(heads)]))
            ci = next((v for k, v in self.ci_by_sha.items() if sha.startswith(k)), self.ci)
            if ci is None:
                return done(json.dumps({"check_runs": []}))
            return done(json.dumps({"check_runs": [{"id": 9, "name": "test", "started_at": "2026-10-24T10:00:00Z",
                                                    "completed_at": "2026-10-24T10:30:00Z", "html_url": "ci", **ci}]}))
        if command[0] == "ps":
            return done(self.ps)
        if command[:2] == ["launchctl", "print"]:
            return done(f"pid = {self.pid}\n")
        if command[:2] == ["launchctl", "kickstart"]:
            return done()
        script = command[1] if len(command) > 1 else ""
        if script.endswith("timctl"):
            if command[2] in {"restart", "start"} and self.restart_ok:
                self.pid += 1
            return done(code=0 if self.restart_ok else 1)
        if script.endswith("record_deployment.py"):
            target = self.root / "data/operational/deployment.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"commit": command[command.index("--commit") + 1], "args": command[2:]}))
            return done()
        if script.endswith("mac_live_install.py"):
            return done('{"drift": []}')
        raise AssertionError(f"unexpected command {command}")

    def probe(self, url, timeout):
        return {"url": url, "ok": self.health_ok, "http_status": 200 if self.health_ok else 500}


@pytest.fixture
def live(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "platform-main")
    git(origin, "config", "user.email", "t@example.invalid")
    git(origin, "config", "user.name", "t")
    (origin / "docs").mkdir()
    (origin / "docs/TIM_V1_LIVE_STATUS.md").write_text("v1\n")
    (origin / "main.py").write_text("print(1)\n")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "one")
    root = tmp_path / "TIM-live"
    subprocess.run(["git", "clone", "-q", str(origin), str(root)], check=True)
    git(root, "checkout", "-q", "--detach")
    home = tmp_path / "home"
    policy = {**POLICY, "repository": "o/r", "gh": "gh", "studies": [], "health_checks": POLICY["health_checks"][:1]}
    mac = Mac(root)
    mac.asked = []
    agent = dr.DashboardRefresh(root, home, policy, runner=mac, probe=mac.probe, clock=lambda: NOW,
                                sleep=lambda seconds: None, uid=501, ask=lambda text, timeout: mac.asked.append(text) or "Ursache: X")
    return origin, root, mac, agent


def new_commit(origin: Path, path: str, text: str) -> str:
    file = origin / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", path)
    return git(origin, "rev-parse", "HEAD")


def test_deploys_records_ci_and_restarts(live):
    origin, root, mac, agent = live
    (root / "docs/TIM_V1_LIVE_STATUS.md").write_text("regenerated\n")  # generated file must not block
    target = new_commit(origin, "src/dashboard/page.py", "x\n")
    status = agent.run_once()
    assert status["decision"]["action"] == "DEPLOY"
    assert status["deploy"]["result"] == "DEPLOYED"
    assert git(root, "rev-parse", "HEAD") == target == status["deployed_commit"]
    deployment = json.loads((root / "data/operational/deployment.json").read_text())
    assert deployment["commit"] == target
    assert deployment["args"][-6:] == ["--passed", "10", "--failed", "0", "--skipped", "2"]
    assert status["deploy"]["generated_files_saved"] == ["docs/TIM_V1_LIVE_STATUS.md"]
    assert status["deploy"]["restart"]["pid_after"] != status["deploy"]["restart"]["pid_before"]
    saved = json.loads((root / "data/operational/dashboard_refresh.json").read_text())
    assert saved["decision"]["reason"] == "deploy" and saved["health_ok"] is True
    assert agent.run_once()["decision"]["action"] == "UP_TO_DATE"


def test_acceptance_report_written_live_survives_the_deploy(live):
    origin, root, mac, agent = live
    report = "docs/TIM_72H_ACCEPTANCE_REPORT.md"
    first = new_commit(origin, report, "old report\n")
    assert agent.run_once()["deploy"]["result"] == "DEPLOYED"
    assert git(root, "rev-parse", "HEAD") == first
    (root / report).write_text("NO-GO 75%\n")  # the 72h monitor writes its result into the tracked file
    target = new_commit(origin, "src/dashboard/page.py", "x\n")
    later = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe,
                                clock=lambda: NOW + timedelta(hours=2), sleep=lambda seconds: None, uid=501)
    status = later.run_once()
    assert status["deploy"]["result"] == "DEPLOYED"
    assert git(root, "rev-parse", "HEAD") == target
    assert (root / report).read_text() == "NO-GO 75%\n"
    assert status["deploy"]["preserved_files_restored"] == [report]
    backups = list((later.state_dir / "generated-backup").rglob("TIM_72H_ACCEPTANCE_REPORT.md"))
    assert [path.read_text() for path in backups] == ["NO-GO 75%\n"]


def test_failed_restart_rolls_back_and_blocks_that_commit(live):
    origin, root, mac, agent = live
    previous = git(root, "rev-parse", "HEAD")
    (root / "data/operational").mkdir(parents=True)
    (root / "data/operational/deployment.json").write_text('{"commit": "old"}')
    target = new_commit(origin, "src/dashboard/page.py", "broken\n")
    mac.health_ok = False
    status = agent.run_once()
    assert status["deploy"]["result"] == "ROLLED_BACK"
    assert git(root, "rev-parse", "HEAD") == previous
    assert json.loads((root / "data/operational/deployment.json").read_text()) == {"commit": "old"}
    mac.health_ok = True
    again = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe,
                                clock=lambda: NOW + timedelta(hours=2), sleep=lambda seconds: None, uid=501)
    assert again.run_once()["decision"]["reason"] == "previous_attempt_failed"
    assert target in json.loads(agent.state_path.read_text())["failed_targets"]


def test_waits_for_ci_job_and_red_ci(live):
    origin, root, mac, agent = live
    before = git(root, "rev-parse", "HEAD")
    new_commit(origin, "src/dashboard/page.py", "x\n")
    mac.ps = "/Users/timrunner/actions-runner/bin/Runner.Worker spawnclient\n"
    assert agent.run_once()["decision"]["reason"] == "busy_deferred"
    mac.ps = "/usr/bin/pg_dump tim\n"
    assert agent.run_once()["decision"]["reason"] == "busy"
    mac.ps = ""
    mac.ci = {"status": "completed", "conclusion": "failure"}
    assert agent.run_once()["decision"]["reason"] == "ci_failed"
    assert git(root, "rev-parse", "HEAD") == before
    assert not any(call[1:3] == ["scripts/timctl", "restart"] or call[-1] == "restart" for call in mac.calls)


def test_study_holds_detector_change(live):
    origin, root, mac, agent = live
    agent.policy = {**agent.policy, "studies": STUDY_POLICY["studies"]}
    new_commit(origin, "src/orderflow/observations.py", "changed\n")
    status = agent.run_once()
    assert status["decision"]["reason"] == "study_protected_paths"
    assert status["decision"]["details"]["blocked_files"] == {"V2_SK_CONTROL_REGIME_V1": ["src/orderflow/observations.py"]}


def merge_pr(origin: Path, branch: str, path: str, text: str) -> tuple[str, str]:
    """A PR merged the way GitHub does it: feature commit, then a merge commit on platform-main."""
    git(origin, "checkout", "-q", "-b", branch)
    head = new_commit(origin, path, text)
    git(origin, "checkout", "-q", "platform-main")
    git(origin, "merge", "-q", "--no-ff", "-m", f"Merge pull request from {branch}", branch)
    return head, git(origin, "rev-parse", "HEAD")


def test_green_pr_head_counts_for_the_merge_commit_with_the_same_tree(live):
    origin, root, mac, agent = live
    head, merge = merge_pr(origin, "feature/a", "src/dashboard/page.py", "x\n")
    mac.ci_by_sha = {merge: None, head: {"status": "completed", "conclusion": "success"}}
    status = agent.run_once()
    assert status["decision"]["action"] == "DEPLOY"
    assert status["ci"]["tested_commit"] == head and status["ci"]["same_tree_as"] == merge
    assert git(root, "rev-parse", "HEAD") == merge
    assert json.loads((root / "data/operational/deployment.json").read_text())["commit"] == merge


def test_pr_head_with_a_different_tree_does_not_count(live):
    origin, root, mac, agent = live
    head, _ = merge_pr(origin, "feature/a", "src/dashboard/page.py", "x\n")
    # platform-main moved on after the PR head was tested: the merge tree differs from the head tree
    merge = new_commit(origin, "docs/later.md", "later\n")
    mac.ci_by_sha = {merge: None, head: {"status": "completed", "conclusion": "success"}}
    mac.pulls_by_sha = {merge: [head]}
    status = agent.run_once()
    assert (status["decision"]["action"], status["decision"]["reason"]) == ("WAIT", "ci_pending")
    assert status["ci"] is None


def test_squash_merge_found_through_the_pull_request_api(live):
    origin, root, mac, agent = live
    git(origin, "checkout", "-q", "-b", "feature/s")
    head = new_commit(origin, "src/dashboard/page.py", "x\n")
    git(origin, "checkout", "-q", "platform-main")
    git(origin, "merge", "-q", "--squash", "feature/s")
    git(origin, "commit", "-q", "-m", "squash")
    squash = git(origin, "rev-parse", "HEAD")
    mac.origin = origin
    mac.ci_by_sha = {squash: None, head: {"status": "completed", "conclusion": "success"}}
    mac.pulls_by_sha = {squash: [head]}
    status = agent.run_once()
    assert status["decision"]["action"] == "DEPLOY" and status["ci"]["tested_commit"] == head


def test_mixed_commit_no_longer_holds_the_display_fixes_before_it(live):
    origin, root, mac, agent = live
    agent.policy = {**agent.policy, "studies": STUDY_POLICY["studies"]}
    display_fix = new_commit(origin, "src/dashboard/page.py", "fix\n")
    mixed = new_commit(origin, "main.py", "print(2)\n")
    later_display = new_commit(origin, "docs/x.md", "doc\n")
    status = agent.run_once()
    assert status["decision"]["action"] == "DEPLOY"
    assert status["deploy"]["result"] == "DEPLOYED"
    assert git(root, "rev-parse", "HEAD") == display_fix
    assert status["target_commit"] == later_display and status["deploy_target"] == display_fix
    assert status["held_back"] == {"target": later_display, "commits": 2,
                                   "blocked_files": {"V2_SK_CONTROL_REGIME_V1": ["main.py"]}}
    assert "2 neuere Commits warten wegen main.py" in status["decision"]["text"]
    # next round: nothing more can go live, and the Control Center text names the file
    again = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe,
                                clock=lambda: NOW + timedelta(hours=2), sleep=lambda seconds: None, uid=501)
    status = again.run_once()
    assert (status["decision"]["action"], status["decision"]["reason"]) == ("HOLD", "study_protected_paths")
    assert "Hält zurück: main.py" in status["decision"]["text"]
    assert git(root, "rev-parse", "HEAD") == display_fix
    assert mixed not in git(root, "rev-parse", "HEAD")


def test_new_merges_do_not_restart_the_defer_clock(live):
    origin, root, mac, agent = live
    new_commit(origin, "src/dashboard/page.py", "a\n")
    mac.ps = "/Users/timrunner/actions-runner/bin/Runner.Worker spawnclient\n"
    assert agent.run_once()["decision"]["reason"] == "busy_deferred"
    newer = new_commit(origin, "src/dashboard/page.py", "b\n")  # another merge, another CI job
    at_15 = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe,
                                clock=lambda: NOW + timedelta(minutes=15), sleep=lambda seconds: None, uid=501)
    waiting = at_15.run_once()
    assert waiting["decision"]["reason"] == "busy_deferred"
    assert waiting["decision"]["details"]["deferred_since_utc"] == dr.iso(NOW)
    at_21 = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe,
                                clock=lambda: NOW + timedelta(minutes=21), sleep=lambda seconds: None, uid=501)
    status = at_21.run_once()
    assert status["decision"]["action"] == "DEPLOY" and status["deploy"]["result"] == "DEPLOYED"
    assert git(root, "rev-parse", "HEAD") == newer


def test_ci_job_defers_then_deploys_and_display_only_shortens_the_interval(live):
    origin, root, mac, agent = live
    new_commit(origin, "src/dashboard/page.py", "x\n")
    mac.ps = "/Users/timrunner/actions-runner/bin/Runner.Worker spawnclient\n"
    first = agent.run_once()
    assert (first["decision"]["action"], first["decision"]["reason"]) == ("WAIT", "busy_deferred")
    assert first["restart_interval_minutes"] == 20
    assert json.loads(agent.state_path.read_text())["deferral"]["since_utc"] == dr.iso(NOW)
    later = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe,
                                clock=lambda: NOW + timedelta(minutes=21), sleep=lambda seconds: None, uid=501)
    status = later.run_once()
    assert status["decision"]["action"] == "DEPLOY" and status["deploy"]["result"] == "DEPLOYED"
    assert "deferral" not in json.loads(agent.state_path.read_text())
    # a second display-only commit may restart after 20 min, a mixed one must wait 60
    new_commit(origin, "src/dashboard/page.py", "y\n")
    mac.ps = ""
    at_25 = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe,
                                clock=lambda: NOW + timedelta(minutes=21 + 25), sleep=lambda seconds: None, uid=501)
    assert at_25.run_once()["decision"]["action"] == "DEPLOY"
    new_commit(origin, "main.py", "print(3)\n")
    mixed_at_25 = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe,
                                      clock=lambda: NOW + timedelta(minutes=21 + 25 + 25), sleep=lambda seconds: None, uid=501)
    status = mixed_at_25.run_once()
    assert (status["decision"]["reason"], status["restart_interval_minutes"]) == ("restart_interval", 60)


def test_pause_and_dry_run_change_nothing(live):
    origin, root, mac, agent = live
    before = git(root, "rev-parse", "HEAD")
    new_commit(origin, "src/dashboard/page.py", "x\n")
    dry = agent.run_once(dry_run=True)
    assert dry["decision"]["action"] == "DEPLOY" and dry["deploy"] is None
    assert not (root / "data/operational/dashboard_refresh.json").exists()
    agent.state_dir.mkdir(parents=True, exist_ok=True)
    (agent.state_dir / "PAUSE").touch()
    assert agent.run_once()["decision"]["reason"] == "paused"
    assert git(root, "rev-parse", "HEAD") == before


def test_active_campaign_holds(live):
    origin, root, mac, agent = live
    new_commit(origin, "src/dashboard/page.py", "x\n")
    campaign = root / "data/qualification/qualification_campaign.json"
    campaign.parent.mkdir(parents=True)
    campaign.write_text('{"status": "ACTIVE"}')
    assert agent.run_once()["decision"]["reason"] == "campaign_active"
    (root / "data/qualification/campaign_aborted.json").write_text("{}")
    assert agent.run_once()["decision"]["action"] == "DEPLOY"


def test_worker_dashboard_rebuilds_only_on_source_change(live, tmp_path):
    origin, root, mac, agent = live
    agent.policy = {**agent.policy, "worker_dashboard": POLICY["worker_dashboard"]}
    new_commit(origin, "tools/mac-worker-dashboard/src/main.rs", "v1\n")
    git(root, "fetch", "-q", "origin")
    git(root, "checkout", "-q", "--detach", "origin/platform-main")
    assert agent.run_once()["worker_dashboard"]["result"] == "BASELINE_RECORDED"
    assert agent.run_once()["worker_dashboard"]["result"] == "UP_TO_DATE"

    binary = agent.home / POLICY["worker_dashboard"]["installed_binary"]
    binary.parent.mkdir(parents=True)
    binary.write_text("old")
    built = agent.state_dir / "cargo-target/release/mac-worker-dashboard"
    real = mac.__call__

    def with_cargo(command, **kwargs):
        if str(command[0]).endswith("cargo"):
            built.parent.mkdir(parents=True, exist_ok=True)
            built.write_text("new")
            return subprocess.CompletedProcess(command, 0, "", "")
        return real(command, **kwargs)

    agent.run = with_cargo
    new_commit(origin, "tools/mac-worker-dashboard/src/main.rs", "v2\n")
    status = agent.run_once()
    assert status["deploy"]["result"] == "DEPLOYED"
    assert status["worker_dashboard"]["result"] == "REBUILT"
    assert binary.read_text() == "new"


def test_control_center_summary_of_the_agent(tmp_path):
    from src.dashboard.operations import _dashboard_refresh

    path = tmp_path / "dashboard_refresh.json"
    assert _dashboard_refresh({}, path)["status"] == "UNAVAILABLE"
    fresh = dr.iso(datetime.now(timezone.utc) - timedelta(minutes=3))
    base = {"checked_at_utc": fresh, "deployed_commit": "abcdef1234", "health_ok": True,
            "decision": {"action": "UP_TO_DATE", "reason": "up_to_date", "text": "aktuell"}}
    summary = _dashboard_refresh(base, path)
    assert (summary["status"], summary["value"]) == ("PASS", "abcdef1")
    assert "vor 3 min" in summary["note"] and "aktuell" in summary["note"]
    hold = {**base, "decision": dr.Decision("HOLD", "study_protected_paths",
                                            {"blocked_files": {"S": ["main.py"]}}).to_dict()}
    assert _dashboard_refresh(hold, path)["status"] == "WAITING"
    assert "wartet bis Studienende" in _dashboard_refresh(hold, path)["note"]
    assert "Hält zurück: main.py" in _dashboard_refresh(hold, path)["note"]
    local = {**base, "decision": dr.Decision("HOLD", "local_changes", {"files": ["main.py"]}).to_dict()}
    assert _dashboard_refresh(local, path)["status"] == "BLOCKED"
    deferred = {**base, "decision": dr.Decision("WAIT", "busy_deferred", {"deploy_at_latest_utc": "2026-10-24T12:20:00Z"}).to_dict()}
    assert _dashboard_refresh(deferred, path)["status"] == "WAITING"
    assert _dashboard_refresh({**base, "health_ok": False}, path)["status"] == "DEGRADED"
    assert _dashboard_refresh({**base, "deploy": {"result": "ROLLED_BACK"}}, path)["status"] == "FAIL"
    old = {**base, "checked_at_utc": "2026-10-01T00:00:00Z"}
    assert _dashboard_refresh(old, path)["status"] == "STALE"


def test_script_writes_a_failure_status_when_the_agent_crashes(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("dashboard_refresh_script", ROOT / "scripts/dashboard_refresh.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script.Path, "home", staticmethod(lambda: tmp_path))
    written = {}

    def boom(self, *, dry_run=False):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(script, "newer_agent", lambda agent: None)  # no fetch or gh against the real repo
    monkeypatch.setattr(script.DashboardRefresh, "run_once", boom)
    monkeypatch.setattr(script.DashboardRefresh, "write_json", lambda self, path, payload: written.update(payload))
    with pytest.raises(RuntimeError):
        script.main([])
    assert written["decision"]["reason"] == "agent_error" and written["health_ok"] is False


# ---------- help requests: ask Claude and open one issue when the agent stays stuck ----------

def agent_at(agent, mac, when):
    return dr.DashboardRefresh(agent.root, agent.home, agent.policy, runner=mac, probe=mac.probe, clock=lambda: when,
                               sleep=lambda seconds: None, uid=501, ask=agent.ask)


def test_stuck_agent_asks_claude_once_and_opens_one_issue(live):
    origin, root, mac, agent = live
    (root / "main.py").write_text("print('local edit')\n")  # someone edits the live checkout
    target = new_commit(origin, "src/dashboard/page.py", "x\n")
    first = agent.run_once()
    assert first["decision"]["reason"] == "local_changes"
    assert first["help"]["result"] == "WATCHING" and first["help"]["ask_at_utc"] == "2026-10-24T14:00:00Z"
    assert mac.issues == [] and mac.asked == []
    assert agent_at(agent, mac, NOW + timedelta(minutes=110)).run_once()["help"]["result"] == "WATCHING"
    later = agent_at(agent, mac, NOW + timedelta(minutes=125)).run_once()
    assert later["help"]["result"] == "REQUESTED" and later["help"]["issue_url"].endswith("/501")
    assert len(mac.asked) == 1 and '"local_changes"' in mac.asked[0] and "main.py" in mac.asked[0]
    created = mac.issues[0]
    assert created["command"] == "create" and "--label" in created["args"]
    assert "lokale Änderungen" in " ".join(created["args"]) and "Ursache: X" in created["body"]
    assert target[:12] in created["body"]
    again = agent_at(agent, mac, NOW + timedelta(hours=3)).run_once()
    assert again["help"]["result"] == "REQUESTED" and len(mac.issues) == 1 and len(mac.asked) == 1
    reminded = agent_at(agent, mac, NOW + timedelta(hours=9)).run_once()
    assert reminded["help"]["result"] == "REMINDED" and mac.issues[-1]["command"] == "comment"
    assert mac.issues[-1]["args"][0] == "501"


def test_normal_waiting_never_asks_and_a_fixed_problem_resets(live):
    origin, root, mac, agent = live
    new_commit(origin, "src/dashboard/page.py", "x\n")
    mac.ci = {"status": "in_progress", "conclusion": None}
    for minutes in (0, 200, 400):
        status = agent_at(agent, mac, NOW + timedelta(minutes=minutes)).run_once()
        assert status["decision"]["reason"] == "ci_pending" and status["help"] is None
    assert mac.issues == [] and "stuck" not in json.loads(agent.state_path.read_text())


def test_rolled_back_deploy_asks_at_once_and_claude_failure_still_opens_the_issue(live):
    origin, root, mac, agent = live
    new_commit(origin, "src/dashboard/page.py", "broken\n")
    mac.health_ok = False

    def no_claude(text, timeout):
        raise FileNotFoundError("Claude Code CLI is unavailable")

    broken = dr.DashboardRefresh(root, agent.home, agent.policy, runner=mac, probe=mac.probe, clock=lambda: NOW,
                                 sleep=lambda seconds: None, uid=501, ask=no_claude)
    status = broken.run_once()
    assert status["deploy"]["result"] == "ROLLED_BACK"
    assert status["help"]["result"] == "REQUESTED" and status["help"]["claude_asked"] is False
    assert "Claude war nicht erreichbar" in mac.issues[0]["body"]
    mac.health_ok = True
    held = agent_at(agent, mac, NOW + timedelta(hours=3)).run_once()
    assert held["decision"]["reason"] == "previous_attempt_failed"
    assert held["help"]["result"] == "REQUESTED" and len(mac.issues) == 1  # same problem, no second issue


def test_missing_label_falls_back_to_an_issue_without_label():
    calls = []

    def gh(argv, body):
        calls.append(argv)
        return (1, "") if "--label" in argv else (0, "https://github.com/o/r/issues/7\n")

    state = {"stuck": {"key": "ci_failed:abc", "reason": "ci_failed", "target": "abc", "since_utc": "2026-10-24T08:00:00Z"}}
    result = dr.dashboard_help.request_help(state=state, status={"decision": {"action": "HOLD"}}, history=[],
                                            config=dr.dashboard_help.settings(POLICY), now=NOW,
                                            ask=lambda text, timeout: "ok", gh=gh, repository="o/r")
    assert result["issue_url"] == "https://github.com/o/r/issues/7" and len(calls) == 2
    assert dr.dashboard_help.problem({"action": "HOLD", "reason": "paused"}, None, "t", dr.dashboard_help.DEFAULTS) is None
    assert dr.dashboard_help.problem({"action": "HOLD", "reason": "study_protected_paths"}, None, "t",
                                     dr.dashboard_help.DEFAULTS) is None


def test_control_center_names_the_help_issue(tmp_path):
    from src.dashboard.operations import _dashboard_refresh

    fresh = dr.iso(datetime.now(timezone.utc) - timedelta(minutes=2))
    status = {"checked_at_utc": fresh, "deployed_commit": "abcdef1234", "health_ok": True,
              "decision": dr.Decision("HOLD", "local_changes", {"files": ["main.py"]}).to_dict(),
              "help": {"result": "REQUESTED", "issue_url": "https://github.com/o/r/issues/501"}}
    summary = _dashboard_refresh(status, tmp_path / "s.json")
    assert "Hilfe bei Claude angefragt (Issue #501)" in summary["note"]
    assert summary["help_issue"].endswith("/501")


# ---------- self-update: the newest green agent code decides, not the old one ----------

def load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("dashboard_refresh_script_selfupdate", ROOT / "scripts/dashboard_refresh.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_newer_green_agent_code_is_loaded_before_the_round(live):
    import sys

    import src.operational as package

    origin, root, mac, agent = live
    for relative in ("src/operational/dashboard_help.py", "src/operational/dashboard_refresh.py",
                     "ops/dashboard_refresh/policy.json"):
        new_commit(origin, relative, (ROOT / relative).read_text())
    agent.git("fetch", "--quiet", "origin", "platform-main")
    git(root, "checkout", "-q", "--detach", "origin/platform-main")
    script = load_script()
    assert script.newer_agent(agent) is None  # same code live: nothing to load
    policy = json.loads((ROOT / "ops/dashboard_refresh/policy.json").read_text())
    policy["max_defer_minutes"] = 7
    target = new_commit(origin, "ops/dashboard_refresh/policy.json", json.dumps(policy))
    mac.ci = {"status": "in_progress", "conclusion": None}
    assert script.newer_agent(agent) is None  # not green yet: the old code keeps deciding
    mac.ci = {"status": "completed", "conclusion": "success"}
    newer = script.newer_agent(agent)
    assert newer["commit"] == target and set(newer["files"]) == set(script.AGENT_FILES)
    saved = {name: sys.modules.get(name) for name in ("src.operational.dashboard_refresh", "src.operational.dashboard_help")}
    saved_attributes = {name: getattr(package, name, None) for name in ("dashboard_refresh", "dashboard_help")}
    try:
        loaded = script.load_agent(newer, agent.home)
        assert loaded.policy["max_defer_minutes"] == 7
        assert loaded.agent_source["commit"] == target
        assert type(loaded).__module__ == "src.operational.dashboard_refresh" and type(loaded) is not dr.DashboardRefresh
    finally:
        for name, module in saved.items():
            sys.modules[name] = module
        for name, module in saved_attributes.items():
            setattr(package, name, module)


def test_red_or_diverged_target_is_not_loaded(live):
    origin, root, mac, agent = live
    new_commit(origin, "src/operational/dashboard_refresh.py", "raise SystemExit('bad')\n")
    mac.ci = {"status": "completed", "conclusion": "failure"}
    assert load_script().newer_agent(agent) is None


def test_live_policy_intervals():
    # Uzi 27.10.2026: the agent checks every 5 minutes and may restart the runtime after 5 minutes.
    assert LIVE_POLICY["min_minutes_between_runtime_restarts"] == 5
    assert LIVE_POLICY["min_minutes_between_runtime_restarts_display_only"] == 5
    plist = plistlib.loads((ROOT / "ops/launchd/com.tim.dashboard-refresh.plist").read_bytes())
    assert plist["StartInterval"] == 300


PUBLIC_FLAG = "Library/Application Support/TIM/public-dashboard.enabled"


def test_public_view_checks_follow_the_flag_file(live):
    _, _, _, agent = live
    agent.policy = {**agent.policy, "health_checks": LIVE_POLICY["health_checks"]}
    names = lambda **kw: [c["name"] for c in agent.enabled_checks(**kw)]  # noqa: E731
    assert "public_journal" not in names() and names(after_restart=True) == []
    flag = agent.home / PUBLIC_FLAG
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("")
    assert {"public_chart", "public_journal"} <= set(names())
    assert names(after_restart=True) == ["public_chart", "public_journal"]


def test_public_view_down_after_restart_rolls_back(live):
    origin, root, mac, agent = live
    agent.policy = {**agent.policy, "health_checks": agent.policy["health_checks"]
                    + [c for c in LIVE_POLICY["health_checks"] if c["name"].startswith("public_")]}
    flag = agent.home / PUBLIC_FLAG
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("")
    previous = git(root, "rev-parse", "HEAD")
    mac.probe = lambda url, timeout: {"url": url, "ok": ":8780/" not in url, "http_status": 200 if ":8780/" not in url else 502}
    agent.probe = mac.probe
    new_commit(origin, "src/dashboard/public_en.py", "x\n")
    status = agent.run_once()
    restart = status["deploy"]["restart"]
    assert [p["name"] for p in restart["pages"]] == ["public_chart", "public_journal"] and not restart["ok"]
    assert status["deploy"]["result"] != "DEPLOYED" and git(root, "rev-parse", "HEAD") == previous
    assert status["health_ok"] is False


def test_public_view_up_after_restart_deploys(live):
    origin, root, mac, agent = live
    agent.policy = {**agent.policy, "health_checks": agent.policy["health_checks"]
                    + [c for c in LIVE_POLICY["health_checks"] if c["name"].startswith("public_")]}
    flag = agent.home / PUBLIC_FLAG
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("")
    target = new_commit(origin, "src/dashboard/public_en.py", "y\n")
    status = agent.run_once()
    assert status["deploy"]["result"] == "DEPLOYED" and git(root, "rev-parse", "HEAD") == target
    assert all(p["ok"] for p in status["deploy"]["restart"]["pages"]) and status["health_ok"] is True
