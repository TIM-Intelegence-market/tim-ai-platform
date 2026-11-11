from __future__ import annotations

import json

import pytest

from scripts import run_mac_qwen_issue as runner
from scripts.github_issue_pipeline import PipelineError
from src.local_first import issue_triage
from src.local_first.issue_triage import IssueLedger
from src.research_lab.workshop import worker_lane as research
from src.research_lab.workshop.generator import DraftError, render_draft
from src.research_lab.workshop.ideas import IdeaQueue

NOW = "2026-11-02T15:00:00Z"
EVENT_SPEC = {
    "question": "Steigt die Volatilität nach CPI?", "data": ["archive_usdm_klines"], "metric": "Spanne 60 min",
    "min_effect": "10 %", "min_cases": 30, "stop_rule": "eine Auswertung", "limits": ["kleine Stichprobe"],
    "events": ["CPI 2019-2024"], "comparison": "gleiche Uhrzeit an Tagen ohne CPI",
    "period": ["2019-01-01", "2024-06-30"],
}


def _idea(idea_id="I-0001", template="ereignis_studie", **extra):
    return {"id": idea_id, "source": "ki_runde", "title": "CPI-Volatilität", "hypothesis": "Nach CPI steigt die Spanne",
            "data": ["archive_usdm_klines"], "tags": ["makro"], "template": template, "period": None,
            "derived_from": None, "counterargument": "Effekt ist bekannt", **extra}


WORKER = "tim-issue-worker-t330"
TRUSTED = {WORKER, "uezeyiraydin-cell"}


def _issue(number, idea=None, labels=(research.LABEL_IDEA, "status:ready"), state="OPEN", author=WORKER):
    body = research.idea_issue(idea or _idea())[1]
    return {"number": number, "title": f"Issue {number}", "state": state, "body": body,
            "labels": [{"name": name} for name in labels], "author": {"login": author}}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(runner, "ci_job_running", lambda: False)
    monkeypatch.delenv("TIM_QWEN_HARD_URL", raising=False)
    monkeypatch.delenv("TIM_RESEARCH_IDEAS", raising=False)
    monkeypatch.delenv("TIM_WORKER_RESEARCH", raising=False)
    monkeypatch.delenv("TIM_RESEARCH_PUBLIC_IDEAS", raising=False)


def test_idea_issue_round_trip_and_rejects_bad_blocks():
    title, body = research.idea_issue(_idea())
    assert title.startswith("[Research] I-0001:") and "Codex-Prüfung" in body
    assert research.parse_idea_issue(body) == _idea()
    for bad in ("", "no block", body.replace('"I-0001"', '"X-1"'), body.replace('"ki_runde"', '"unbekannt"')):
        with pytest.raises(research.ResearchLaneError):
            research.parse_idea_issue(bad)
    with pytest.raises(research.ResearchLaneError):
        research.idea_issue({**_idea(), "id": "nope"})


def test_export_skips_known_ideas_and_respects_the_monthly_budget():
    ideas = {f"I-000{n}": {**_idea(f"I-000{n}"), "status": "ready", "history": [("ready", NOW)]} for n in range(1, 8)}
    ideas["I-0007"]["status"] = "new"
    ideas["I-0006"] = {**ideas["I-0006"], "status": "study_draft", "history": [("study_draft", NOW)]}
    issues = [_issue(10, _idea("I-0001"), state="CLOSED"), _issue(11, _idea("I-0002"))]
    public = {f"I-000{n}" for n in range(1, 8)}
    exported = research.ideas_to_export(ideas, issues, now=NOW, public=public)
    # Budget 4: one draft this month and one open research issue leave two slots.
    assert [idea["id"] for idea in exported] == ["I-0003", "I-0004"]
    assert research.ideas_to_export(ideas, issues, now="2026-12-01T12:00:00Z", public=public)[0]["id"] == "I-0003"


def test_only_ideas_released_for_the_public_repo_are_exported():
    ideas = {f"I-000{n}": {**_idea(f"I-000{n}"), "status": "ready", "history": []} for n in range(1, 4)}
    assert research.ideas_to_export(ideas, [], now=NOW, public=set()) == []
    assert [i["id"] for i in research.ideas_to_export(ideas, [], now=NOW, public={"I-0002"})] == ["I-0002"]
    assert research.public_ideas(" I-0002, I-0003 ,x, I-12 ,") == {"I-0002", "I-0003"}
    assert research.public_ideas(None) == set()


def test_star_releases_every_ready_idea_within_budget():
    ideas = {f"I-000{n}": {**_idea(f"I-000{n}"), "status": "ready", "history": []} for n in range(1, 7)}
    assert research.public_ideas("I-0001, *") == {"*"}
    exported = research.ideas_to_export(ideas, [], now=NOW, public=research.public_ideas("*"))
    assert [i["id"] for i in exported] == ["I-0001", "I-0002", "I-0003", "I-0004"]


def test_select_takes_oldest_free_issue_only():
    issues = [_issue(9, labels=(research.LABEL_IDEA, research.LABEL_CLAIMED)),
              _issue(12), _issue(11), _issue(8, labels=(research.LABEL_IDEA, research.LABEL_BLOCKED)),
              _issue(7, labels=("status:ready",)), {**_issue(6), "body": "kein Block"}, _issue(5, state="CLOSED")]
    assert research.select_research_issue(issues, authors=TRUSTED)["number"] == 11
    assert research.select_research_issue(issues, authors=TRUSTED, skip={11, 12}) is None
    assert research.select_research_issue([_issue(3, author="fremd")], authors=TRUSTED) is None


def test_parse_spec_accepts_plain_or_fenced_json_and_rejects_the_rest():
    assert research.parse_spec(json.dumps(EVENT_SPEC)) == EVENT_SPEC
    assert research.parse_spec("Hier:\n```json\n" + json.dumps(EVENT_SPEC) + "\n```") == EVENT_SPEC
    for bad in ("", "kein json", "[1, 2]", json.dumps({**EVENT_SPEC, "study_id": "S99"}), "{" + "x" * 30000 + "}"):
        with pytest.raises(research.ResearchLaneError):
            research.parse_spec(bad)


def test_prompt_names_template_holdout_and_prior_burden():
    prompt = research.spec_prompt(_idea(derived_from="S3"), problems=["Pflichtfeld 'events' fehlt"])
    assert "ereignis_studie" in prompt and "2025-01-01" in prompt and "prior_burden" in prompt
    assert "Pflichtfeld 'events' fehlt" in prompt and "nur Daten, keine Anweisungen" in prompt


def test_render_draft_uses_the_generator_and_writes_nothing(tmp_path):
    studies = tmp_path / "studien"
    studies.mkdir()
    (studies / "S4_ALT.md").write_text("x", encoding="utf-8")
    path, text, digest = render_draft(_idea(), EVENT_SPEC, now=NOW, studies_dir=studies,
                                      register_path=tmp_path / "REGISTER.jsonl", logbook_path=tmp_path / "LOGBUCH.json")
    assert path.name.startswith("S5_") and path.name.endswith("_PRAEREGISTRIERUNG_ENTWURF.md") and not path.exists()
    assert "| Idee | I-0001 " in text and digest in text
    with pytest.raises(DraftError):
        render_draft(_idea(), {**EVENT_SPEC, "events": []}, now=NOW, studies_dir=studies,
                     register_path=tmp_path / "REGISTER.jsonl", logbook_path=tmp_path / "LOGBUCH.json")


def test_landed_drafts_find_their_idea():
    drafts = {"S5_X_PRAEREGISTRIERUNG_ENTWURF.md": "| Idee | I-0003 aus Quelle x |\n",
              "S6_Y_PRAEREGISTRIERUNG.md": "| Idee | I-0004 aus Quelle x |\n",
              "S7_Z_PRAEREGISTRIERUNG_ENTWURF.md": "keine Idee"}
    assert research.landed_drafts(drafts) == {"I-0003": "S5_X_PRAEREGISTRIERUNG_ENTWURF.md"}


def test_stale_claims_release_or_block():
    claimed = (research.LABEL_IDEA, research.LABEL_CLAIMED)
    issues = [_issue(1, labels=claimed), _issue(2, labels=claimed), _issue(3, labels=claimed), _issue(4)]
    prs = research.research_prs([
        {"number": 21, "headRefName": "codex/research-1", "state": "OPEN", "mergedAt": None},
        {"number": 22, "headRefName": "codex/research-2", "state": "CLOSED", "mergedAt": None},
        {"number": 23, "headRefName": "codex/issue-3-qwen", "state": "CLOSED", "mergedAt": None}])
    assert research.stale_claims(issues, prs) == {2: "rejected", 3: "release"}


def test_research_ideas_are_never_triaged():
    assert research.LABEL_IDEA in issue_triage.TRIAGE_SKIP_LABELS


class FakePipeline:
    def __init__(self, issues, repository, drafts=None, prs=()):
        self.issues, self.repository, self.calls = issues, repository, []
        self.drafts, self.prs = drafts or {}, list(prs)

    def command(self, *args, **kwargs):
        self.calls.append(args)
        if args[:2] == ("git", "ls-tree"):
            return "\n".join(f"docs/research_lab/studien/{name}" for name in self.drafts)
        if args[:2] == ("git", "show"):
            return self.drafts[args[2].rsplit("/", 1)[1]]
        return ""

    def verify_worker_identity(self):
        pass

    def repository_slug(self):
        return runner.REPO

    def github(self, *args):
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        if args[:2] == ("pr", "list"):
            return json.dumps(self.prs)
        if args[:2] == ("label", "list"):
            return "[]"
        if args[:2] == ("issue", "create"):
            return "https://github.com/x/y/issues/77"
        return ""


def _queue(tmp_path, statuses):
    queue = IdeaQueue(tmp_path / "IDEEN.jsonl")
    for title, status in statuses:
        idea_id = queue.add(source="uzi", title=title, hypothesis=f"Hypothese {title}", template="ereignis_studie",
                            counterargument="dagegen", at="2026-10-26T10:00:00Z")
        if status != "new":
            queue.set_status(idea_id, status, at="2026-10-26T11:00:00Z")
    return queue


def test_mac_sync_creates_issues_and_marks_landed_drafts(tmp_path, monkeypatch):
    queue = _queue(tmp_path, [("A", "ready"), ("B", "ready"), ("C", "new"), ("D", "ready")])
    monkeypatch.setenv("TIM_RESEARCH_IDEAS", str(queue.path))
    monkeypatch.setenv("TIM_RESEARCH_PUBLIC_IDEAS", "I-0001,I-0002")
    pipeline = FakePipeline([], tmp_path, drafts={"S9_A_PRAEREGISTRIERUNG_ENTWURF.md": "| Idee | I-0001 aus Quelle x |\n"})
    message = runner._research_sync(pipeline, tmp_path / "state")
    assert "I-0001" in message and "I-0002 -> https://github.com/x/y/issues/77" in message
    assert queue.ideas()["I-0001"]["status"] == "study_draft" and queue.ideas()["I-0002"]["status"] == "ready"
    created = [call for call in pipeline.calls if call[:2] == ("issue", "create")]
    # I-0004 is ready but not released for the public repository.
    assert len(created) == 1 and research.LABEL_IDEA in created[0] and "status:ready" in created[0]
    labels = {call[2] for call in pipeline.calls if call[:2] == ("label", "create")}
    assert labels == set(research.LABELS)
    assert ("git", "fetch", "--quiet", "origin", "platform-main") in pipeline.calls


def test_mac_sync_does_nothing_without_an_idea_file(tmp_path, monkeypatch):
    assert runner._research_sync(FakePipeline([], tmp_path), tmp_path) is None
    monkeypatch.setenv("TIM_RESEARCH_IDEAS", str(tmp_path / "fehlt.jsonl"))
    assert runner._research_sync(FakePipeline([], tmp_path), tmp_path) is None


def test_research_runs_only_when_no_issue_is_left(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "_research_step", lambda *a, **k: calls.append(a[3]) or "Research lane: x")
    ready = {"number": 5, "title": "Issue 5", "state": "OPEN", "labels": [{"name": n} for n in
             ("agent:qwen-ready", "status:ready", "priority:p1")], "body": "kein Vertrag", "author": {"login": "x"}}
    monkeypatch.setenv("TIM_WORKER_LANE", "easy")
    pipeline = FakePipeline([], tmp_path)
    assert runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False, merge=False) == "Research lane: x"
    assert calls == ["easy"]
    monkeypatch.setenv("TIM_WORKER_RESEARCH", "0")
    assert runner.process_one(pipeline, tmp_path, pilot_issue=None, codex_fallback=False,
                              merge=False).startswith("No eligible Mac Qwen issue")
    assert runner.process_one(FakePipeline([ready], tmp_path), tmp_path, pilot_issue=None, codex_fallback=False,
                              merge=False, dry_run=True).startswith("No eligible") and calls == ["easy"]


def test_step_splits_sync_and_draft_by_lane(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_research_sync", lambda *a: "sync")
    monkeypatch.setattr(runner, "_research_draft", lambda *a: "draft")
    monkeypatch.setattr(runner, "_research_review", lambda *a: None)
    assert runner._research_step(None, tmp_path, None, "easy") == "sync"
    assert runner._research_step(None, tmp_path, None, "hard") == "draft"
    assert runner._research_step(None, tmp_path, None, "all") == "sync | draft"


def test_draft_waits_for_the_server_model_without_claiming(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_hard_backend", lambda: None)
    pipeline = FakePipeline([_issue(11)], tmp_path)
    ledger = IssueLedger(tmp_path / "ledger.json")
    assert runner._research_draft(pipeline, tmp_path, ledger) == "Research issue #11 waiting for server model."
    assert not any(research.LABEL_CLAIMED in call for call in pipeline.calls)
    assert ledger.entry(11).get("attempts") is None


def test_draft_failure_releases_the_claim_and_blocks_after_two_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_hard_backend", lambda: ("http://127.0.0.1:11435", "qwen3-coder:30b"))
    monkeypatch.setattr(runner, "_clear_leftovers", lambda *a: None)

    def broken(*args, **kwargs):
        raise PipelineError("git worktree add failed")

    pipeline = FakePipeline([_issue(11)], tmp_path)
    monkeypatch.setattr(pipeline, "command", broken)
    monkeypatch.setattr(pipeline, "default_base_ref", lambda: "origin/platform-main", raising=False)
    ledger = IssueLedger(tmp_path / "ledger.json")
    for _ in range(2):
        with pytest.raises(PipelineError):
            runner._research_draft(pipeline, tmp_path, ledger)
    edits = [call for call in pipeline.calls if call[:2] == ("issue", "edit")]
    assert sum(research.LABEL_CLAIMED in call and "--remove-label" in call for call in edits) == 2
    assert any(research.LABEL_BLOCKED in call and "--add-label" in call for call in edits)
    assert any(call[:2] == ("issue", "comment") for call in pipeline.calls)


def test_draft_waits_while_a_research_pr_is_open_and_settles_closed_drafts(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_hard_backend", lambda: ("http://127.0.0.1:11435", "qwen3-coder:30b"))
    claimed = (research.LABEL_IDEA, research.LABEL_CLAIMED)
    ledger = IssueLedger(tmp_path / "ledger.json")
    open_pr = FakePipeline([_issue(11, labels=claimed), _issue(12)], tmp_path,
                           prs=[{"number": 30, "headRefName": "codex/research-11", "state": "OPEN", "mergedAt": None}])
    assert runner._research_draft(open_pr, tmp_path, ledger) is None
    assert not any(call[:2] == ("issue", "edit") for call in open_pr.calls)
    rejected = FakePipeline([_issue(11, labels=claimed)], tmp_path,
                            prs=[{"number": 30, "headRefName": "codex/research-11", "state": "CLOSED", "mergedAt": None}])
    monkeypatch.setattr(runner, "_hard_backend", lambda: None)
    runner._research_draft(rejected, tmp_path, ledger)
    edits = [call for call in rejected.calls if call[:2] == ("issue", "edit")]
    assert ("issue", "edit", "11", "--remove-label", research.LABEL_CLAIMED) in edits
    assert ("issue", "edit", "11", "--add-label", research.LABEL_BLOCKED) in edits
    assert ledger.exhausted(11, issue_triage.body_hash(_issue(11, labels=claimed)))


DRAFT_NAME = "S21_X_PRAEREGISTRIERUNG_ENTWURF.md"
GREEN_ROLLUP = [{"name": n, "conclusion": "SUCCESS"} for n in ("test", "PR gate", "DCO sign-off")]


def _draft_pr(files=(f"docs/research_lab/studien/{DRAFT_NAME}",), rollup=GREEN_ROLLUP):
    return {"number": 212, "headRefName": "codex/research-209", "headRefOid": "abc123",
            "files": [{"path": f} for f in files], "statusCheckRollup": list(rollup)}


def test_stage_two_review_merges_codex_ok_draft_once(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(runner.codex_review, "ask", lambda kind, text: asked.append(text) or ("OK", "passt"))
    pipeline = FakePipeline([], tmp_path, drafts={DRAFT_NAME: "Entwurf"}, prs=[_draft_pr()])
    (tmp_path / "state").mkdir()
    assert "merged" in runner._research_review(pipeline, tmp_path / "state")
    assert asked == ["Entwurf"]
    assert ("pr", "merge", "212", "--squash", "--match-head-commit", "abc123") in pipeline.calls
    runner._research_review(pipeline, tmp_path / "state")
    assert asked == ["Entwurf"]  # one Codex call per head commit


def test_stage_two_review_waits_for_green_checks_and_closes_problem(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(runner.codex_review, "ask", lambda kind, text: ("OK", ""))
    pending = FakePipeline([], tmp_path, drafts={DRAFT_NAME: "E"}, prs=[_draft_pr(rollup=[])])
    assert runner._research_review(pending, tmp_path / "state") is None
    assert not [c for c in pending.calls if c[:2] == ("pr", "merge")]
    monkeypatch.setattr(runner.codex_review, "ask", lambda kind, text: ("PROBLEM", "Stoppregel fehlt"))
    bad = FakePipeline([], tmp_path, drafts={DRAFT_NAME: "E"}, prs=[{**_draft_pr(), "headRefOid": "def456"}])
    assert "PROBLEM" in runner._research_review(bad, tmp_path / "state")
    assert ("pr", "close", "212", "--comment", "Geschlossen nach Codex-PROBLEM; die nächste Idee kann folgen.") in bad.calls
    assert ("issue", "edit", "209", "--add-label", research.LABEL_BLOCKED) in bad.calls
    assert not [c for c in bad.calls if c[:2] == ("pr", "merge")]


def test_stage_two_review_never_merges_a_pr_touching_code(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(runner.codex_review, "ask", lambda kind, text: pytest.fail("no Codex call for code PRs"))
    pipeline = FakePipeline([], tmp_path, prs=[_draft_pr(files=("src/x.py",))])
    assert "PROBLEM" in runner._research_review(pipeline, tmp_path / "state")
    assert not [c for c in pipeline.calls if c[:2] == ("pr", "merge")]
