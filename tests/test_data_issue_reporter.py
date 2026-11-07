import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.operational import data_issue_reporter as dir_mod
from src.operational.data_issue_reporter import Reporter, ReporterError, agent_env, detect, redact

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def gap_status(**overrides):
    status = {"state": "IDLE", "checked_at_utc": NOW.isoformat(), "open_gaps": 0, "missing_trades": 0,
              "too_large_gaps": 0, "waiting_gaps": 0, "last_error": None, "candle_error": None}
    status.update(overrides)
    return status


def recovery_status(**overrides):
    status = {"status": "PASS", "checked_at": NOW.isoformat(), "errors": []}
    status.update(overrides)
    return status


class FakeGitHub:
    def __init__(self, issues=None, fail_codex=False, claude_logged_in=False):
        self.issues = list(issues or [])
        self.comments = []
        self.calls = []
        self.fail_codex = fail_codex
        self.claude_logged_in = claude_logged_in
        self.agent_envs = []

    def __call__(self, args, cwd, timeout, env):
        args = list(args)
        self.calls.append(args)
        if args[0] == "gh":
            if args[1:3] == ["issue", "list"]:
                return json.dumps([{"number": n, "body": b} for n, b in self.issues])
            if args[1:3] == ["issue", "create"]:
                number = 200 + len(self.issues)
                self.issues.append((number, args[args.index("--body") + 1]))
                return f"https://github.com/x/y/issues/{number}\n"
            if args[1:3] == ["issue", "comment"]:
                self.comments.append((int(args[3]), args[args.index("--body") + 1]))
                return ""
            return ""
        if args[0] == "git":
            return ""
        if args[0] == "codex":
            self.agent_envs.append(env)
            if self.fail_codex:
                raise ReporterError("codex exit 1")
            output = Path(args[args.index("--output-last-message") + 1])
            output.write_text("Ursache: Testantwort", encoding="utf-8")
            return ""
        if args[0] == "claude":
            if args[1:3] == ["auth", "status"]:
                return json.dumps({"loggedIn": self.claude_logged_in})
            return json.dumps({"result": "Claude-Antwort"})
        raise AssertionError(args)


def make(tmp_path, gap=None, recovery=None, runner=None, now=NOW, dry_run=False, repo="clone"):
    operational = tmp_path / "operational"
    operational.mkdir(exist_ok=True)
    if gap is not None:
        (operational / "gap_filler.json").write_text(json.dumps(gap))
    if recovery is not None:
        (operational / "history_recovery.json").write_text(json.dumps(recovery))
    return Reporter(operational_dir=operational, state_path=tmp_path / "state.json",
                    repo_dir=tmp_path / repo, github_repo="x/y", runner=runner or FakeGitHub(),
                    dry_run=dry_run, now=now)


def test_healthy_status_reports_nothing():
    assert detect(gap_status(), recovery_status(), NOW) == []


def test_detects_each_problem():
    old = (NOW - timedelta(hours=1)).isoformat()
    keys = {f.key for f in detect(gap_status(state="ERROR", last_error="boom", too_large_gaps=1, open_gaps=3,
                                             candle_error="x", checked_at_utc=old),
                                  recovery_status(status="ATTENTION_REQUIRED", checked_at=(NOW - timedelta(hours=4)).isoformat()),
                                  NOW)}
    assert keys == {"gap_filler_stale", "gap_filler_error", "gap_too_large", "gap_stuck", "candle_rebuild_error",
                    "history_recovery_attention", "history_recovery_stale"}
    assert {f.key for f in detect(None, None, NOW)} == {"gap_filler_missing"}


def test_filling_gap_is_not_stuck_and_too_large_is_not_counted_twice():
    assert detect(gap_status(state="FILLING", open_gaps=2), recovery_status(), NOW) == []
    keys = {f.key for f in detect(gap_status(state="BACKING_OFF", open_gaps=1, too_large_gaps=1), recovery_status(), NOW)}
    assert keys == {"gap_too_large"}


def test_redaction_strips_credentials():
    text = redact("connect postgresql://tim:geheim@127.0.0.1/tim failed password=abc token: xyz")
    assert "geheim" not in text and "abc" not in text and "xyz" not in text
    assert len(redact("x" * 1000)) <= dir_mod.FIELD_LIMIT


def test_agent_env_drops_secrets():
    env = agent_env({"PATH": "/bin", "HOME": "/h", "GH_TOKEN": "t", "TIM_DATABASE_SECRET_FILE": "f",
                     "TIM_KI_MARKET_DSN": "d", "GIT_DIR": "g", "ANTHROPIC_API_KEY": "k"})
    assert env == {"PATH": "/bin", "HOME": "/h"}


def test_grace_time_then_one_issue_with_analysis(tmp_path):
    fake = FakeGitHub()
    gap = gap_status(state="ERROR", last_error="TimeoutError")
    first = make(tmp_path, gap, recovery_status(), fake).run()
    assert first["active"] == ["gap_filler_error"] and first["created"] == []
    later = make(tmp_path, gap, recovery_status(), fake, now=NOW + timedelta(minutes=61)).run()
    assert later["created"] == [{"key": "gap_filler_error", "issue": 200}]
    assert later["analysed"] == [{"key": "gap_filler_error", "provider": "codex"}]
    assert "TIM_DATA_ISSUE key=gap_filler_error" in fake.issues[0][1]
    assert fake.comments[-1][0] == 200 and "Testantwort" in fake.comments[-1][1]
    again = make(tmp_path, gap, recovery_status(), fake, now=NOW + timedelta(minutes=90)).run()
    assert again["created"] == [] and again["analysed"] == [] and len(fake.issues) == 1
    assert all("GH_TOKEN" not in (env or {}) for env in fake.agent_envs)


def test_existing_open_issue_is_reused(tmp_path):
    fake = FakeGitHub(issues=[(77, "<!-- TIM_DATA_ISSUE key=gap_too_large -->\nalt")])
    gap = gap_status(too_large_gaps=1, open_gaps=1, state="BACKING_OFF")
    make(tmp_path, gap, recovery_status(), fake).run()
    result = make(tmp_path, gap, recovery_status(), fake, now=NOW + timedelta(minutes=31)).run()
    assert result["created"] == [] and len(fake.issues) == 1 and fake.comments == []


def test_clearing_comments_once(tmp_path):
    fake = FakeGitHub()
    bad = gap_status(state="ERROR", last_error="x")
    make(tmp_path, bad, recovery_status(), fake).run()
    make(tmp_path, bad, recovery_status(), fake, now=NOW + timedelta(minutes=61)).run()
    healthy = gap_status(checked_at_utc=(NOW + timedelta(minutes=70)).isoformat())
    result = make(tmp_path, healthy, recovery_status(checked_at=(NOW + timedelta(minutes=70)).isoformat()), fake,
                  now=NOW + timedelta(minutes=70)).run()
    assert result["cleared"] == ["gap_filler_error"]
    assert "Nicht mehr beobachtet" in fake.comments[-1][1]
    count = len(fake.comments)
    make(tmp_path, healthy, recovery_status(checked_at=(NOW + timedelta(minutes=70)).isoformat()), fake,
         now=NOW + timedelta(minutes=71)).run()
    assert len(fake.comments) == count


def test_daily_limit(tmp_path):
    fake = FakeGitHub()
    gap = gap_status(state="ERROR", too_large_gaps=1, open_gaps=1, candle_error="c",
                     checked_at_utc=(NOW - timedelta(hours=1)).isoformat())
    recovery = recovery_status(status="PAUSED")
    make(tmp_path, gap, recovery, fake).run()
    result = make(tmp_path, gap, recovery, fake, now=NOW + timedelta(hours=7)).run()
    assert len(result["created"]) == dir_mod.MAX_NEW_PER_DAY
    assert any("Tagesgrenze" in error for error in result["errors"])


def test_codex_failure_falls_back_to_claude_only_when_logged_in(tmp_path):
    gap = gap_status(state="ERROR", last_error="x")
    fake = FakeGitHub(fail_codex=True, claude_logged_in=True)
    make(tmp_path, gap, recovery_status(), fake).run()
    result = make(tmp_path, gap, recovery_status(), fake, now=NOW + timedelta(minutes=61)).run()
    assert result["analysed"] == [{"key": "gap_filler_error", "provider": "claude"}]

    other = tmp_path / "other"
    other.mkdir()
    fake2 = FakeGitHub(fail_codex=True, claude_logged_in=False)
    make(other, gap, recovery_status(), fake2).run()
    for minutes in (61, 62, 63):
        result = make(other, gap, recovery_status(), fake2, now=NOW + timedelta(minutes=minutes)).run()
    assert "nicht möglich" in fake2.comments[-1][1]
    make(other, gap, recovery_status(), fake2, now=NOW + timedelta(minutes=64)).run()
    assert sum("nicht möglich" in c[1] for c in fake2.comments) == 1


def test_dry_run_writes_nothing(tmp_path):
    fake = FakeGitHub()
    gap = gap_status(state="ERROR", last_error="x")
    make(tmp_path, gap, recovery_status(), fake).run()
    result = make(tmp_path, gap, recovery_status(), fake, now=NOW + timedelta(minutes=61), dry_run=True).run()
    assert result["created"] == [{"key": "gap_filler_error", "issue": None}]
    assert fake.issues == [] and fake.comments == []
    assert not any(call[:3] == ["gh", "issue", "create"] for call in fake.calls)


def test_refuses_tim_live_clone(tmp_path):
    reporter = make(tmp_path, repo="TIM-live")
    with pytest.raises(ReporterError):
        reporter.refresh_repo()


def test_analysis_answer_is_scrubbed(tmp_path):
    class Leaky(FakeGitHub):
        def __call__(self, args, cwd, timeout, env):
            if list(args)[0] == "codex":
                output = Path(list(args)[list(args).index("--output-last-message") + 1])
                output.write_text("DSN postgresql://tim:geheim@db/tim und password=hunter2", encoding="utf-8")
                return ""
            return super().__call__(args, cwd, timeout, env)

    fake = Leaky()
    gap = gap_status(state="ERROR", last_error="x")
    make(tmp_path, gap, recovery_status(), fake).run()
    make(tmp_path, gap, recovery_status(), fake, now=NOW + timedelta(minutes=61)).run()
    posted = fake.comments[-1][1]
    assert "geheim" not in posted and "hunter2" not in posted
