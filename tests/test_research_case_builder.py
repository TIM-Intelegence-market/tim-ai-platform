"""Deterministic Research Case builder (Issue #3): IDs, status, evidence, outcome, idempotency."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.dashboard.api import _research_case_detail, _research_cases_collection
from src.dashboard.app import DashboardState, render
from src.models.market_data import Observation, ObservationKind
from src.research.case_builder import (
    BUILDER_VERSION, REASON_GAP, REASON_HORIZON, REASON_OUTCOME_DATA, REASON_QUALITY, REASON_REVIEW,
    REASON_TOO_FEW, Gap, assess, materialize, refresh_case,
)
from src.research.case_engine import ResearchCaseEngine

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
RULES = {ObservationKind.BOS_BULLISH: "bos", ObservationKind.REJECTION: "bronxc", ObservationKind.WEAK_CONTINUATION: "bronxc"}


def obs(n: int, kind: ObservationKind, minute: int, *, symbol: str = "BTCUSDT", timeframe: str = "1m", input_hash: str | None = None) -> Observation:
    return Observation(kind, symbol, timeframe, T0 + timedelta(minutes=minute), "TEST_ONLY", 50, {},
                       provenance="PUBLIC_MARKET_DATA_DETERMINISTIC", rule_id=RULES.get(kind, "bronxc"), rule_version="1.0.0",
                       input_hash=("%064x" % n) if input_hash is None else input_hash,
                       observation_id=UUID(int=n), created_at=T0)


def full_set() -> list[Observation]:
    return [obs(1, ObservationKind.BOS_BULLISH, 1), obs(2, ObservationKind.REJECTION, 5), obs(3, ObservationKind.WEAK_CONTINUATION, 9)]


def closes(start_minute: int, end_minute: int, *, start: float = 100.0, step: float = 0.1, skip: int | None = None) -> list[dict]:
    return [{"close_time": T0 + timedelta(minutes=m), "close": start + step * (m - start_minute)}
            for m in range(start_minute, end_minute + 1) if m != skip]


AFTER = T0 + timedelta(hours=2)


def test_ids_and_hashes_are_stable_and_order_independent() -> None:
    items = full_set() + [obs(4, ObservationKind.REJECTION, 40)]
    first = materialize(items, AFTER)
    shuffled = items[:]
    random.Random(7).shuffle(shuffled)
    second = materialize(shuffled, AFTER)
    assert [c.to_dict() for c in first.cases] == [c.to_dict() for c in second.cases]
    assert first.manifest()["manifest_hash"] == second.manifest()["manifest_hash"]
    assert assess(first.cases[0].to_dict(), AFTER)["case_hash"] == assess(first.cases[0].to_dict(), AFTER + timedelta(days=3))["case_hash"]


def test_grouping_separates_window_timeframe_and_symbol() -> None:
    items = [obs(1, ObservationKind.REJECTION, 1), obs(2, ObservationKind.REJECTION, 2),
             obs(3, ObservationKind.REJECTION, 31), obs(4, ObservationKind.REJECTION, 2, timeframe="5m"),
             obs(5, ObservationKind.REJECTION, 2, symbol="ETHUSDT")]
    result = materialize(items, AFTER)
    assert len(result.cases) == 4
    sizes = sorted(len(c.observation_ids) for c in result.cases)
    assert sizes == [1, 1, 1, 2]


def test_single_observation_stays_open_with_reason() -> None:
    case = materialize([obs(1, ObservationKind.REJECTION, 1)], AFTER).cases[0]
    assert case.status == "OPEN"
    assert REASON_TOO_FEW in case.missing_evidence
    assert case.review_history == []  # OPEN is the starting status, nothing to record


def test_outcome_pending_until_horizon_closes_then_ready_for_review_never_confirmed() -> None:
    early = materialize(full_set(), T0 + timedelta(minutes=35)).cases[0]
    assert early.status == "COLLECTING_EVIDENCE"
    assert REASON_HORIZON in early.missing_evidence and early.outcome is None
    candles = {("BTCUSDT", "1m"): closes(29, 42)}
    mature = materialize(full_set(), AFTER, candles_by_key=candles).cases[0]
    assert mature.status == "READY_FOR_REVIEW"
    assert mature.missing_evidence == [REASON_REVIEW]
    assert mature.outcome == "PRICE_INCREASED"
    assert all(case.status != "CONFIRMED" for case in materialize(full_set(), AFTER, candles_by_key=candles).cases)


def test_hole_in_horizon_candles_never_yields_outcome() -> None:
    case = materialize(full_set(), AFTER, candles_by_key={("BTCUSDT", "1m"): closes(29, 42, skip=36)}).cases[0]
    assert case.outcome is None
    assert REASON_OUTCOME_DATA in case.missing_evidence
    assert case.status == "COLLECTING_EVIDENCE"


def test_sideways_and_decrease_labels() -> None:
    flat = materialize(full_set(), AFTER, candles_by_key={("BTCUSDT", "1m"): closes(29, 42, step=0.0)}).cases[0]
    down = materialize(full_set(), AFTER, candles_by_key={("BTCUSDT", "1m"): closes(29, 42, step=-0.5)}).cases[0]
    assert flat.outcome == "PRICE_SIDEWAYS" and down.outcome == "PRICE_DECREASED"


def test_gap_overlapping_case_blocks_outcome_and_review() -> None:
    gap = Gap("g" * 64, "BTCUSDT", T0 + timedelta(minutes=33), T0 + timedelta(minutes=34))
    case = materialize(full_set(), AFTER, gaps=[gap], candles_by_key={("BTCUSDT", "1m"): closes(29, 42)}).cases[0]
    assert case.outcome is None and REASON_GAP in case.missing_evidence
    assert case.status == "COLLECTING_EVIDENCE"
    assert assess(case.to_dict(), AFTER, gaps=[gap])["data_quality_status"] == "GAP_EXPOSED"
    other_symbol = Gap("h" * 64, "ETHUSDT", T0, None)
    assert materialize(full_set(), AFTER, gaps=[other_symbol], candles_by_key={("BTCUSDT", "1m"): closes(29, 42)}).cases[0].status == "READY_FOR_REVIEW"


def test_defective_observation_is_quarantined_not_dropped() -> None:
    items = full_set()[:2] + [obs(9, ObservationKind.WEAK_CONTINUATION, 9, input_hash="")]
    case = materialize(items, AFTER).cases[0]
    assert case.status == "QUARANTINED"
    assert materialize(items, AFTER, candles_by_key={("BTCUSDT", "1m"): closes(29, 42)}).cases[0].outcome is None
    assert REASON_QUALITY in case.missing_evidence
    assert len(case.observation_ids) == 3
    assert "input_hash fehlt" in case.review_history[-1]["reason"]


def test_observations_after_as_of_are_excluded_no_look_ahead() -> None:
    late = obs(9, ObservationKind.REJECTION, 300)
    result = materialize(full_set() + [late], T0 + timedelta(minutes=60))
    assert {"observation_id": str(late.observation_id), "reason": "observed_after_as_of"} in result.excluded
    assert all(str(late.observation_id) not in c.observation_ids for c in result.cases)


def test_second_run_is_idempotent_and_refresh_reports_no_change() -> None:
    candles = {("BTCUSDT", "1m"): closes(29, 42)}
    first = materialize(full_set(), AFTER, candles_by_key=candles)
    second = materialize(full_set(), AFTER, existing=first.cases, candles_by_key=candles)
    assert [c.to_dict() for c in first.cases] == [c.to_dict() for c in second.cases]
    assert refresh_case(second.cases[0], AFTER, candles=candles[("BTCUSDT", "1m")]) is False


def test_review_locked_status_survives_rebuild_and_confirm_needs_review() -> None:
    candles = {("BTCUSDT", "1m"): closes(29, 42)}
    ready = materialize(full_set(), AFTER, candles_by_key=candles).cases[0]
    engine = ResearchCaseEngine()
    engine.cases[ready.case_id] = ready
    engine.confirm(ready.case_id, AFTER + timedelta(minutes=1), reviewer="uzi")
    assert ready.status == "CONFIRMED" and ready.missing_evidence == []
    rebuilt = materialize(full_set(), AFTER + timedelta(days=1), existing=[ready], candles_by_key=candles).cases[0]
    assert rebuilt.status == "CONFIRMED" and rebuilt.outcome == "PRICE_INCREASED"
    collecting = materialize(full_set(), T0 + timedelta(minutes=35)).cases[0]
    engine.cases[collecting.case_id] = collecting
    with pytest.raises(ValueError, match="Cannot confirm"):
        engine.confirm(collecting.case_id, AFTER, reviewer="uzi")


def test_status_moves_are_recorded_with_builder_version() -> None:
    early = materialize(full_set(), T0 + timedelta(minutes=35)).cases[0]
    later = materialize(full_set(), AFTER, existing=[early], candles_by_key={("BTCUSDT", "1m"): closes(29, 42)}).cases[0]
    assert [entry["to"] for entry in later.review_history] == ["COLLECTING_EVIDENCE", "READY_FOR_REVIEW"]
    assert all(entry["reason"].startswith(BUILDER_VERSION) for entry in later.review_history)


def _snapshot() -> dict:
    candles = {("BTCUSDT", "1m"): closes(29, 42)}
    ready = materialize(full_set(), AFTER, candles_by_key=candles).cases
    single = materialize([obs(20, ObservationKind.REJECTION, 70)], AFTER).cases
    broken = materialize([obs(30, ObservationKind.REJECTION, 100), obs(31, ObservationKind.BOS_BULLISH, 101, input_hash="")], AFTER).cases
    return {"research_cases": [c.to_dict() for c in ready + single + broken]}


def test_api_filters_stats_and_detail_from_materialized_cases() -> None:
    snap = _snapshot()
    payload = _research_cases_collection(snap, {}, as_of=AFTER)
    stats = payload["stats"]
    assert stats["total"] == 3 and stats["by_status"] == {"OPEN": 1, "QUARANTINED": 1, "READY_FOR_REVIEW": 1}
    assert stats["confirmed"] == 0 and stats["active"] == 2
    assert stats["by_data_quality"]["DEFECT"] == 1
    assert stats["by_review_status"] == {"BLOCKED": 1, "NOT_READY": 1, "PENDING": 1}
    active = _research_cases_collection(snap, {"status": ["ACTIVE"]}, as_of=AFTER)
    assert {c["status"] for c in active["cases"]} == {"OPEN", "READY_FOR_REVIEW"}
    assert [c["status"] for c in _research_cases_collection(snap, {"review_status": ["pending"]}, as_of=AFTER)["cases"]] == ["READY_FOR_REVIEW"]
    assert [c["status"] for c in _research_cases_collection(snap, {"data_quality_status": ["DEFECT"]}, as_of=AFTER)["cases"]] == ["QUARANTINED"]
    assert _research_cases_collection(snap, {"status": ["CONFIRMED"]}, as_of=AFTER)["cases"] == []
    detail = _research_case_detail(snap["research_cases"][0], AFTER)
    assert detail["assessment"]["maturity"] == "MATURE"
    assert [ev["kind"] for ev in detail["timeline"]] == ["BOS_BULLISH", "REJECTION", "WEAK_CONTINUATION"]
    assert detail["mode"] == "OBSERVE / READ-ONLY" and detail["lifecycle"]


def test_explorer_shows_status_cards_active_action_and_detail() -> None:
    snap = _snapshot()
    state = DashboardState(research_cases=snap["research_cases"])
    page = render(state, "Research Cases")
    for label in ("Fälle gesamt", "Open", "Sammelt Belege", "Review bereit", "Bestätigt", "Verworfen", "In Quarantäne"):
        assert f"<div class='card__label'>{label}</div>" in page
    assert "Alle aktiven Cases anzeigen" in page and "ALL ACTIVE" in page
    assert BUILDER_VERSION in page and "OBSERVE / READ-ONLY" in page
    detail = render(state, "Research Cases", snap["research_cases"][0]["case_id"])
    for label in ("Outcome / Reife", "Data Quality", "Gaps", "Review", "Provenienz", "Manual Review pending"):
        assert label in detail


class _RefreshRepository:
    def __init__(self) -> None:
        self.saved: list = []

    async def research_case_gaps(self, _symbol):
        return []

    async def upsert_research_case(self, case) -> None:
        self.saved.append(case.to_dict())


@pytest.mark.asyncio
async def test_runtime_refreshes_active_cases_at_candle_close_only_when_changed() -> None:
    from main import TIMApplication
    from src.models.market_data import Candle

    engine = ResearchCaseEngine()
    for item in full_set():
        engine.ingest(item)
    case = next(iter(engine.cases.values()))
    app = TIMApplication.__new__(TIMApplication)
    app.repository, app.cases, app.dashboard_state = _RefreshRepository(), engine, DashboardState()
    app.history = {"1m": [Candle("BTCUSDT", "1m", T0 + timedelta(minutes=m - 1), T0 + timedelta(minutes=m), 100.0, 110.0, 90.0, 100.0 + 0.1 * m, 1.0, 1) for m in range(1, 43)]}
    early, last = app.history["1m"][34], app.history["1m"][-1]
    await app._refresh_research_cases(early)
    assert case.status == "COLLECTING_EVIDENCE" and REASON_HORIZON in case.missing_evidence
    await app._refresh_research_cases(last)
    assert case.status == "READY_FOR_REVIEW" and case.outcome == "PRICE_INCREASED"
    assert len(app.repository.saved) == 2
    await app._refresh_research_cases(last)
    assert len(app.repository.saved) == 2
    assert app.dashboard_state.research_cases[0]["status"] == "READY_FOR_REVIEW"
