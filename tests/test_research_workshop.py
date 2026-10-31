"""Research workshop F1/F2: idea queue with hash chain, idea check, import adapters."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_lab.workshop import charter
from src.research_lab.workshop.__main__ import main
from src.research_lab.workshop.check import check_ideas, load_logbook, record
from src.research_lab.workshop.ideas import IdeaError, IdeaQueue
from src.research_lab.workshop.sources import import_journal_review, import_reflection

NOW = "2026-10-31T12:00:00Z"
LOGBOOK = [
    {"id": "S9", "title": "CHoCH, Retest-Band, Reaktionsschluss auf 15m (GoatHub-Lernheft)", "status": "not_testable"},
    {"id": "S1", "title": "BTC-Schwankung an CPI-Terminen", "status": "confirmed"},
]


def _queue(tmp_path: Path) -> IdeaQueue:
    return IdeaQueue(tmp_path / "IDEEN.jsonl")


def _add(queue: IdeaQueue, title: str, *, data=("archive_spot_klines",), at=NOW, **extra) -> str:
    return queue.add(source=extra.pop("source", "uzi"), title=title, hypothesis=extra.pop("hypothesis", f"Hypothese zu {title}"),
                     data=data, at=at, **extra)


def test_chain_detects_edit_of_an_old_line(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    _add(queue, "VWAP-Abweichung Asien")
    _add(queue, "Funding-Extrem und Rückkehr")
    lines = queue.path.read_text().splitlines()
    lines[0] = lines[0].replace("Asien", "London")
    queue.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(IdeaError, match="Zeile 1"):
        queue.ideas()


def test_same_hypothesis_twice_is_refused_and_ids_count_up(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    assert _add(queue, "A", hypothesis="Kurs steigt nach X") == "I-0001"
    with pytest.raises(IdeaError, match="I-0001"):
        _add(queue, "B", hypothesis="Kurs  steigt nach x!")
    assert _add(queue, "C", hypothesis="Kurs fällt nach X") == "I-0002"


def test_ai_round_needs_counterargument_and_is_capped_per_week(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    with pytest.raises(IdeaError, match="Gegenargument"):
        _add(queue, "K0", source="ki_runde")
    for i in range(charter.KI_IDEAS_PER_WEEK):
        _add(queue, f"K{i + 1}", source="ki_runde", counterargument="kann Zufall sein")
    with pytest.raises(IdeaError, match="Grenze"):
        _add(queue, "K9", source="ki_runde", counterargument="kann Zufall sein")
    assert _add(queue, "K10", source="ki_runde", counterargument="x", at="2026-11-09T12:00:00Z")


def test_only_uzi_rejects_and_closed_ideas_stay_closed(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    idea = _add(queue, "A")
    with pytest.raises(IdeaError, match="nur Uzi"):
        queue.set_status(idea, "rejected")
    queue.set_status(idea, "rejected", ["Uzi: nein"], by="uzi")
    with pytest.raises(IdeaError, match="abgeschlossen"):
        queue.set_status(idea, "ready")


def test_holdout_period_is_locked_for_archive_data(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    archive = _add(queue, "Archiv bis 2025", period=("2023-01-01", "2025-03-31"))
    live = _add(queue, "Live ab 2026", data=("plan_journal",), period=("2026-10-01", "2026-12-31"))
    verdicts = {v.idea_id: v for v in check_ideas(queue, [], now=NOW)}
    assert verdicts[archive].status == "holdout_locked"
    assert verdicts[live].status == "ready"


def test_known_dead_idea_is_flagged_unless_declared_derived(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    again = _add(queue, "CHoCH Retest auf 15m", tags=["goathub"])
    derived = _add(queue, "CHoCH Retest auf 15m ohne Band", hypothesis="andere", tags=["goathub"], derived_from="S9")
    verdicts = {v.idea_id: v for v in check_ideas(queue, LOGBOOK, now=NOW)}
    assert verdicts[again].status == "already_tested" and "S9" in verdicts[again].reasons[0]
    assert verdicts[derived].status == "ready" and "Ableitung von S9" in verdicts[derived].reasons[0]


def test_rejected_idea_blocks_its_twin(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    first = _add(queue, "IB Ausbruch ohne Filter", hypothesis="h1")
    queue.set_status(first, "rejected", by="uzi")
    twin = _add(queue, "IB Ausbruch ohne Filter New York", hypothesis="h2")
    (verdict,) = check_ideas(queue, [], now=NOW)
    assert verdict.idea_id == twin and verdict.status == "already_tested" and first in verdict.reasons[0]


def test_missing_and_unready_data_wait(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    none = _add(queue, "ohne Daten", data=())
    perp = _add(queue, "Perp CVD", data=("perp_live",))
    early = _add(queue, "Funding 2018", data=("archive_usdm_klines",), period=("2018-01-01", "2019-12-31"))
    verdicts = {v.idea_id: v for v in check_ideas(queue, [], now=NOW)}
    assert {verdicts[i].status for i in (none, perp, early)} == {"waiting_data"}
    assert "F5" in verdicts[perp].reasons[0] and "2020-01-01" in verdicts[early].reasons[0]


def test_monthly_budget_counts_drafts_in_local_month(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    ids = [_add(queue, f"Idee Nummer {i}", hypothesis=f"h{i}") for i in range(6)]
    queue.set_status(ids[0], "study_draft", at="2026-10-31T23:30:00Z")  # 00:30 local on 1 November
    queue.set_status(ids[1], "study_draft", at="2026-10-15T10:00:00Z")
    verdicts = check_ideas(queue, [], now="2026-10-31T12:00:00Z")
    statuses = [v.status for v in verdicts]
    # October local: one draft used (ids[1]); ids[0] fell on 1 November local time.
    assert statuses == ["ready"] * (charter.MONTHLY_STUDY_BUDGET - 1) + ["waiting_budget"]


def test_record_writes_only_changes_and_check_is_repeatable(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    _add(queue, "A")
    first = check_ideas(queue, [], now=NOW)
    assert record(queue, first, now=NOW) == 1
    assert record(queue, check_ideas(queue, [], now=NOW), now=NOW) == 0
    assert queue.ideas()["I-0001"]["status"] == "ready"


def test_import_adapters_are_idempotent_and_read_only(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    family = {"scenario_type": "LIQUIDITY_SWEEP_REVERSAL", "direction": "LONG", "setup_grade": "B", "clusters": 31,
              "mean_net_r": 0.2, "net_mean_ci95_cluster_bootstrap": [0.01, 0.4]}
    proposal = {"proposal_id": "abc", "candidates_for_registration": [family]}
    before = json.dumps(proposal, sort_keys=True)
    assert import_journal_review(queue, proposal) == ["I-0001"]
    assert import_journal_review(queue, proposal) == []
    assert json.dumps(proposal, sort_keys=True) == before
    report = {"week": "2026-W44", "report_hash": "r1",
              "proposal": {"kind": "ABSORPTION", "direction": "above", "text": "t", "question": "q"}}
    assert import_reflection(queue, report) == ["I-0002"]
    assert import_reflection(queue, report) == []
    assert import_reflection(queue, {"week": "2026-W45", "report_hash": "r2", "proposal": None}) == []


def test_cli_add_check_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "IDEEN.jsonl"
    logbook = tmp_path / "LOGBUCH.json"
    logbook.write_text(json.dumps({"entries": LOGBOOK}))
    assert main(["--queue", str(path), "add", "--source", "uzi", "--title", "POC-Retest London",
                 "--hypothesis", "Retest am Vortags-POC hält öfter als Zufall", "--data", "archive_spot_klines"]) == 0
    assert main(["--queue", str(path), "--logbook", str(logbook), "check", "--record"]) == 0
    assert main(["--queue", str(path), "list"]) == 0
    out = capsys.readouterr().out
    assert "I-0001" in out and "bereit für Studien-Entwurf" in out
    assert main(["--queue", str(path), "add", "--source", "uzi", "--title", "x", "--hypothesis",
                 "Retest am Vortags-POC hält öfter als Zufall"]) == 2


def test_repository_logbook_loads_and_charter_is_stage_one() -> None:
    assert any(e["id"] == "S8" for e in load_logbook())
    assert charter.STAGE <= charter.MAX_STAGE_WITHOUT_UZI
    assert charter.MONTHLY_STUDY_BUDGET == 4
