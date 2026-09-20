from __future__ import annotations

from src.dashboard.app import DashboardState, render


def _case(index: int, status: str) -> dict:
    return {
        "case_id": f"case-{index:02d}",
        "status": status,
        "opened_at": "2026-09-10T12:00:00+00:00",
        "updated_at": "2026-09-10T12:05:00+00:00",
        "observation_ids": [f"obs-{index:02d}"],
        "evidence": [
            {
                "observation_id": f"obs-{index:02d}",
                "kind": "BOS_BEARISH",
                "observed_at": "2026-09-10T12:01:00+00:00",
            }
        ],
        "missing_evidence": ["continuation_context"] if status != "CONFIRMED" else [],
        "outcome": None,
        "rule_versions": {"bos": "1.0.0"},
    }


def test_explorer_is_honest_when_zero_confirmed_but_cases_collect_evidence() -> None:
    state = DashboardState(research_cases=[_case(index, "OPEN") for index in range(15)])

    snapshot = state.snapshot()
    page = render(state, "Research Cases")

    assert snapshot["case_counts"]["confirmed"] == 0
    assert snapshot["case_counts"]["collecting_evidence"] == 15
    assert snapshot["case_counts"]["total"] == 15
    assert "0 confirmed, aber 15 collecting evidence" in page
    assert "Alle aktiven / alle Status" in page
    assert "case-14" in page
    assert "No research cases yet" not in page


def test_explorer_shows_real_confirmed_cases_without_inventing_progress() -> None:
    state = DashboardState(
        research_cases=[
            _case(1, "CONFIRMED"),
            _case(2, "COLLECTING_EVIDENCE"),
        ]
    )

    snapshot = state.snapshot()
    page = render(state, "Research Cases")

    assert snapshot["case_counts"]["confirmed"] == 1
    assert snapshot["case_counts"]["collecting_evidence"] == 1
    assert snapshot["case_counts"]["by_status"] == {
        "COLLECTING_EVIDENCE": 1,
        "CONFIRMED": 1,
    }
    assert "1 confirmed · 1 collecting evidence · 2 total" in page
    assert "case-01" in page
    assert "case-02" in page
    assert "COLLECTING_EVIDENCE" in page
    assert "CONFIRMED" in page


def test_explorer_empty_state_reports_zero_without_fake_cases() -> None:
    state = DashboardState(research_cases=[])

    page = render(state, "Research Cases")

    assert "0 confirmed, 0 collecting evidence" in page
    assert "keine materialisierten Research Cases vorhanden" in page
    assert "No research cases yet" not in page
