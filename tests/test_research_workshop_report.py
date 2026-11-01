"""Research workshop F5: report and logbook from a verified bundle, monthly reflection."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_lab.workshop.ideas import IdeaQueue
from src.research_lab.workshop.report import ReportError, _local, monthly_reflection, render_reflection, report_from_bundle
from src.research_lab.workshop.runner import JobQueue, RunResult, run_job

AT = "2026-10-31T15:00:00Z"


def _bundle(tmp_path: Path, result: dict | None, *, exit_code: int = 0) -> Path:
    queue = JobQueue(tmp_path / "jobs.jsonl")
    queue.approve("S12", by="uzi", reference="Uzi 31.10.", at=AT)
    job = queue.submit("S12", ["scripts/research_lab_s12.py"], at=AT)

    def executor(command, workdir, outdir):
        if result is not None:
            (outdir / "result.json").write_text(json.dumps(result))
        return RunResult(exit_code, "ok\n", "", host="mac")
    return Path(run_job(queue, job, workdir=tmp_path, bundles_dir=tmp_path / "b", executor=executor)["bundle_dir"])


def _finished_date(bundle: Path) -> str:
    # run_job stempelt finished_at mit der echten Uhrzeit; das Berichtsdatum folgt der lokalen Zeitzone.
    finished = json.loads((bundle / "manifest.json").read_text())["finished_at"]
    return _local(finished).date().isoformat()


@pytest.fixture()
def logbook(tmp_path: Path) -> Path:
    path = tmp_path / "LOGBUCH.json"
    path.write_text(json.dumps({"schema": "tim_research_logbook/1", "updated": "2026-10-29",
                                "entries": [{"id": "S1", "status": "confirmed", "title": "CPI"}]}))
    return path


def test_report_and_logbook_entry_from_bundle(tmp_path: Path, logbook: Path) -> None:
    bundle = _bundle(tmp_path, {"status": "not_testable", "result": "241 von 500 Signalen", "lesson": "Filter zu streng",
                                "metrics": {"signale": 241}})
    report = report_from_bundle(bundle, title="POC-Retest London", draft="docs/x.md", logbook=logbook,
                                reports_dir=tmp_path / "reports")
    text = report.read_text()
    assert "**nicht testbar**" in text and "Filter zu streng" in text and "| signale | 241 |" in text
    data = json.loads(logbook.read_text())
    assert data["entries"][0]["id"] == "S12" and data["entries"][0]["status"] == "not_testable"
    assert data["entries"][0]["doc"] == report.as_posix() and data["updated"] == _finished_date(bundle)
    assert any(e["id"] == "S1" for e in data["entries"])
    with pytest.raises(ReportError, match="gibt es schon"):
        report_from_bundle(bundle, title="x", logbook=logbook, reports_dir=tmp_path / "reports")


@pytest.mark.parametrize("result, match", [
    (None, "result.json fehlt"),
    ({"status": "great", "result": "r", "lesson": "l"}, "unbekannt"),
    ({"status": "failed", "result": "r", "lesson": " "}, "lesson"),
    ({"status": "candidate", "result": "r", "lesson": "l", "edge": True}, "edge"),
])
def test_bad_results_are_refused(tmp_path: Path, logbook: Path, result, match) -> None:
    before = logbook.read_text()
    with pytest.raises(ReportError, match=match):
        report_from_bundle(_bundle(tmp_path, result), title="x", logbook=logbook, reports_dir=tmp_path / "r")
    assert logbook.read_text() == before


def test_failed_run_and_tampered_bundle_give_no_verdict(tmp_path: Path, logbook: Path) -> None:
    with pytest.raises(ReportError, match="Exit 3"):
        report_from_bundle(_bundle(tmp_path / "a", {"status": "failed", "result": "r", "lesson": "l"}, exit_code=3),
                           title="x", logbook=logbook, reports_dir=tmp_path / "r")
    bundle = _bundle(tmp_path / "b", {"status": "confirmed", "result": "r", "lesson": "l"})
    (bundle / "out" / "result.json").write_text(json.dumps({"status": "confirmed", "result": "besser", "lesson": "l", "edge": True}))
    with pytest.raises(ReportError, match="Ausgaben"):
        report_from_bundle(bundle, title="x", logbook=logbook, reports_dir=tmp_path / "r")


def test_monthly_reflection_counts_and_proposals(tmp_path: Path) -> None:
    queue = IdeaQueue(tmp_path / "IDEEN.jsonl")
    for i in range(3):
        idea = queue.add(source="community", title=f"Goat {i}", hypothesis=f"h{i}", data=["archive_spot_klines"], at=AT)
        queue.set_status(idea, "already_tested", ["ähnlich S9"], at=AT)
    perp = queue.add(source="uzi", title="Perp CVD", hypothesis="hp", data=["perp_live"], at=AT)
    queue.set_status(perp, "waiting_data", ["F5"], at=AT)
    draft = queue.add(source="uzi", title="POC", hypothesis="hq", data=["archive_spot_klines"], at=AT)
    queue.set_status(draft, "study_draft", ["S12: docs/x.md"], at=AT)
    logbook = [{"id": "S1", "status": "confirmed"}, {"id": "S12", "status": "failed"}]
    trades = [{"lessons": ["COSTS_ATE_PROFIT"]}, {"lessons": ["COSTS_ATE_PROFIT"]}, {"lessons": ["FULL_TARGET"]}]
    data = monthly_reflection("2026-10", queue=queue, logbook=logbook, trade_records=trades)
    assert data["ideas_new"] == 5 and data["drafts"] == 1 and data["edges_after_costs"] == []
    assert data["source_outcomes"] == {"uzi": {"failed": 1}}
    assert len(data["proposals"]) == 3 and "Perp" in data["proposals"][0] and "GoatHub" in data["proposals"][1]
    assert "2 von 3 Trades" in data["proposals"][2]
    text = render_reflection(data)
    assert "Handelsvorteile nach Kosten belegt: **0**" in text and "Bestätigte Ergebnisse" in text
    assert monthly_reflection("2026-11", queue=queue, logbook=logbook)["ideas_new"] == 0


def test_repository_logbook_has_no_edge_yet() -> None:
    from src.research_lab.workshop.check import load_logbook
    data = monthly_reflection("2026-10", queue=IdeaQueue(Path("/nonexistent/IDEEN.jsonl")), logbook=load_logbook())
    assert data["edges_after_costs"] == [] and "S1" in data["confirmed"]
