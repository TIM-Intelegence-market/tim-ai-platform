"""Learning proposals from the plan journal: clusters, cluster bootstrap, verdicts, no mutation, no adoption."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.research_lab import journal_review as jr

T0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)


def _case(i: int, net: float, *, minutes: int, direction: str = "LONG", scenario_type: str = "LIQUIDITY_SWEEP_REVERSAL", grade: str = "B", status: str = "CLOSED") -> dict:
    created = T0 + timedelta(minutes=minutes)
    return {"id": f"c{i:04d}", "created_at": created.isoformat(), "status": status, "direction": direction, "scenario_type": scenario_type,
            "setup_grade": grade, "grade_ruleset_version": "grade/1.0.0", "evidence_ref": {"mapping_version": "setup-evidence-mapping/0"},
            "cost_model_version": "protocol/1.1", "gross_r": net + 0.05, "fee_r": 0.03, "slippage_r": 0.02, "net_r": net,
            "exit_reason": "TP3" if net > 0 else "STOP", "journal_decision": "NO_TRADE"}


def _journal(cases: list[dict]) -> dict:
    return {"schema": "tim_plan_journal/2", "source": "Setup-Pfad 15m (80 Kerzen), TIM-Regeln, nur Papier", "entries": cases, "log_head": "h", "log_seq": len(cases)}


def test_clusters_follow_the_chart_window_per_family_and_direction() -> None:
    cases = [_case(0, 1.0, minutes=0), _case(1, 1.0, minutes=15), _case(2, 1.0, minutes=15 * 79),
             _case(3, 1.0, minutes=15 * 80), _case(4, 1.0, minutes=30, direction="SHORT"), _case(5, 1.0, minutes=30, scenario_type="BREAKOUT_ACCEPTANCE")]
    clusters = jr.assign_clusters(cases)
    assert clusters["c0000"] == clusters["c0001"] == clusters["c0002"] != clusters["c0003"]
    assert len({clusters["c0000"], clusters["c0004"], clusters["c0005"]}) == 3


def test_only_closed_cases_with_net_result_count_and_journal_is_not_modified() -> None:
    cases = [_case(0, 1.0, minutes=0), _case(1, 0.5, minutes=15, status="FILLED"), {**_case(2, 0.0, minutes=30), "net_r": None}]
    journal = _journal(cases)
    before = deepcopy(journal)
    proposal = jr.propose(journal, now=T0)
    assert journal == before and proposal["cases_closed"] == 1 and proposal["status"] == "PROPOSED"
    assert proposal["champion"]["changed_by_this_proposal"] is False and proposal["holdout_untouched"] is True


def test_few_clusters_are_insufficient_even_when_every_case_wins() -> None:
    cases = [_case(i, 2.0, minutes=15 * i) for i in range(40)]  # 40 cases, but all inside one chart window
    proposal = jr.propose(_journal(cases), now=T0)
    family = proposal["families"][0]
    assert family["cases"] == 40 and family["clusters"] == 1 and family["verdict"] == "INSUFFICIENT_CASES"
    assert proposal["candidates_for_registration"] == []


def test_enough_clusters_with_positive_interval_become_a_registration_candidate_only() -> None:
    cases = [_case(i, 1.0 if i % 4 else -1.0, minutes=15 * 80 * i) for i in range(40)]  # 40 clusters, mean +0.5
    proposal = jr.propose(_journal(cases), now=T0)
    family = proposal["families"][0]
    assert family["clusters"] == 40 and family["verdict"] == "CANDIDATE_FOR_REGISTRATION"
    low, high = family["net_mean_ci95_cluster_bootstrap"]
    assert 0 < low < 0.5 < high
    assert proposal["candidates_for_registration"] == [family]
    assert "REGISTER.jsonl" in proposal["adoption"] and proposal["champion"]["grade_ruleset_version"] == ["grade/1.0.0"]


def test_negative_or_mixed_families_find_no_edge() -> None:
    cases = [_case(i, 1.0 if i % 2 else -1.2, minutes=15 * 80 * i) for i in range(40)]
    family = jr.propose(_journal(cases), now=T0)["families"][0]
    assert family["verdict"] == "NO_POSITIVE_EDGE_FOUND" and family["mean_net_r"] < 0
    assert family["exit_reasons"] == {"STOP": 20, "TP3": 20} and family["mean_cost_r"] == 0.05


def test_proposal_is_deterministic_and_written_once(tmp_path: Path) -> None:
    cases = [_case(i, 0.3, minutes=15 * 80 * i) for i in range(5)]
    first = jr.propose(_journal(cases), now=T0)
    second = jr.propose(_journal(cases), now=T0 + timedelta(hours=1))
    assert first["proposal_id"] == second["proposal_id"] and first["generated_at"] != second["generated_at"]
    path = jr.write_proposal(first, tmp_path / "review")
    written = json.loads(path.read_text())
    assert written["proposal_id"] == first["proposal_id"]
    assert jr.write_proposal(second, tmp_path / "review") == path and json.loads(path.read_text())["generated_at"] == first["generated_at"]


def test_empty_journal_gives_an_empty_proposal() -> None:
    proposal = jr.propose(_journal([]), now=T0)
    assert proposal["families"] == [] and proposal["cases_closed"] == 0 and proposal["clusters"] == 0


def test_bootstrap_needs_blocks() -> None:
    with pytest.raises(ValueError):
        jr.cluster_block_bootstrap([], seed=1)
    low, high = jr.cluster_block_bootstrap([[1.0], [1.0], [1.0]], seed=1)
    assert low == high == 1.0
