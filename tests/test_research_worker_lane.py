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


def _issue(number, idea=None, labels=(research.LABEL_IDEA, "status:ready"), state="OPEN"):
    body = research.idea_issue(idea or _idea())[1]
    return {"number": number, "title": f"Issue {number}", "state": state, "body": body,
            "labels": [{"name": name} for name in labels]}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(runner, "ci_job_running", lambda: False)
    monkeypatch.delenv("TIM_QWEN_HARD_URL", raising=False)
    monkeypatch.delenv("TIM_RESEARCH_IDEAS", raising=False)
    monkeypatch.delenv("TIM_WORKER_RESEARCH", raising=False)


def test_idea_issue_round_trip_and_rejects_bad_blocks():
    title, body = research.idea_issue(_idea())
    assert title.startswith("[Research] I-0001:") and "Uzis Freigabe" in body
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
    exported = research.ideas_to_export(ideas, issues, now=NOW)
    # Budget 4: one draft this month and one open research issue leave two slots.
    assert [idea["id"] for idea in exported] == ["I-0003", "I-0004"]
    assert research.ideas_to_export(ideas, issues, now="2026-12-01T12:00:00Z")[0]["id"] == "I-0003"


def test_select_takes_oldest_free_issue_only():
    issues = [_issue(9, labels=(research.LABEL_IDEA, research.LABEL_CLAIMED)),
              _issue(12), _issue(11), _issue(8, labels=(research.LABEL_IDEA, research.LABEL_BLOCKED)),
              _issue(7, labels=("status:ready",)), {**_issue(6), "body": "kein Block"}, _issue(5, state="CLOSED")]
    assert research.select_research_issue(issues)["number"] == 11
    assert research.select_research_issue(issues, skip={11, 12}) is None


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


def test_landed_drafts_find_their_idea(tmp_path):
    (tmp_path / "S5_X_PRAEREGISTRIERUNG_ENTWURF.md").write_text("| Idee | I-0003 aus Quelle x |\n", encoding="utf-8")
    (tmp_path / "S6_Y_PRAEREGISTRIERUNG.md").write_text("| Idee | I-0004 aus Quelle x |\n", encoding="utf-8")
    assert research.landed_drafts(tmp_path) == {"I-0003": tmp_path / "S5_X_PRAEREGISTRIERUNG_ENTWURF.md"}


def test_research_ideas_are_never_triaged():
    assert research.LABEL_IDEA in issue_triage.TRIAGE_SKIP_LABELS


class FakePipeline:
    def __init__(self, issues, repository):
        self.issues, self.repository, self.calls = issues, repository, []

    def verify_worker_identity(self):
        pass

    def repository_slug(self):
        return runner.REPO

    def github(self, *args):
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        if args[:2] in {("pr", "list"), ("label", "list")}:
            return "[]"
        if args[:2] == ("issue", "create"):
            return "https://github.com/x/y/issues/77"
        return ""


def _queue(tmp_path, statuses):
    queue = IdeaQueue(tmp_path / "IDEEN.jsonl")
    for title, status in statuses:
        idea_id = queue.add(source="ki_runde", title=title, hypothesis=f"Hypothese {title}", template="ereignis_studie",
                            counterargument="dagegen", at="2026-10-26T10:00:00Z")
        if status != "new":
            queue.set_status(idea_id, status, at="2026-10-26T11:00:00Z")
    return queue


def test_mac_sync_creates_issues_and_marks_landed_drafts(tmp_path, monkeypatch):
    queue = _queue(tmp_path, [("A", "ready"), ("B", "ready"), ("C", "new")])
    repo = tmp_path / "repo"
    studies = repo / "docs/research_lab/studien"
    studies.mkdir(parents=True)
    (studies / "S9_A_PRAEREGISTRIERUNG_ENTWURF.md").write_text("| Idee | I-0001 aus Quelle x |\n", encoding="utf-8")
    monkeypatch.setenv("TIM_RESEARCH_IDEAS", str(queue.path))
    pipeline = FakePipeline([], repo)
    message = runner._research_sync(pipeline, tmp_path / "state")
    assert "I-0001" in message and "I-0002 -> https://github.com/x/y/issues/77" in message
    assert queue.ideas()["I-0001"]["status"] == "study_draft" and queue.ideas()["I-0002"]["status"] == "ready"
    created = [call for call in pipeline.calls if call[:2] == ("issue", "create")]
    assert len(created) == 1 and research.LABEL_IDEA in created[0] and "status:ready" in created[0]
    labels = {call[2] for call in pipeline.calls if call[:2] == ("label", "create")}
    assert labels == set(research.LABELS)


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
    monkeypatch.setattr(pipeline, "command", broken, raising=False)
    monkeypatch.setattr(pipeline, "default_base_ref", lambda: "origin/platform-main", raising=False)
    ledger = IssueLedger(tmp_path / "ledger.json")
    for _ in range(2):
        with pytest.raises(PipelineError):
            runner._research_draft(pipeline, tmp_path, ledger)
    edits = [call for call in pipeline.calls if call[:2] == ("issue", "edit")]
    assert sum(research.LABEL_CLAIMED in call and "--remove-label" in call for call in edits) == 2
    assert any(research.LABEL_BLOCKED in call and "--add-label" in call for call in edits)
    assert any(call[:2] == ("issue", "comment") for call in pipeline.calls)
