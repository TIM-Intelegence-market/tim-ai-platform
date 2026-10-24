"""Cost check of plan-journal plans (0.25 R limit, display only)."""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

import pytest

from src.dashboard import plan_cost_check as cc
from src.dashboard import plan_journal as pj
from src.dashboard.pages.plan_journal import _plan_journal_page
from src.dashboard.server import DashboardServer
from src.dashboard.state import DashboardState

T0 = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)


def _plan(direction: str = "LONG", entry: float = 100.0, stop: float = 99.0) -> dict:
    risk = abs(entry - stop)
    sign = 1 if direction == "LONG" else -1
    return {
        "scenario_id": "B", "scenario_type": "LIQUIDITY_SWEEP_REVERSAL", "direction": direction, "entry_model": "RECLAIM",
        "plan_text": f"PLAN B {direction}", "entry_low": entry, "entry_high": entry + sign * 0.5, "entry": entry, "stop": stop,
        "targets": [entry + sign * risk * r for r in (1.5, 2.0, 3.0)], "invalidation_level": stop + sign * risk / 2,
        "invalidation_side": "<" if direction == "LONG" else ">", "scenario_state": "WATCH", "score": 0.5,
        "missing_confirmations": [], "pipeline_decision": "NO_TRADE", "pipeline_decision_reasons": [], "market_state": "RANGE",
        "grade": {"setup_grade": "C", "grade_reasons": [], "grade_ruleset_version": "grade/1.0.0", "graded_state": "WATCHING"},
        "symbol": "BTCUSDT", "venue": "BINANCE", "market_type": "SPOT", "data_quality": "PASS",
    }


def _expected_cost_r(entry: float, stop: float) -> float:
    """Protocol 1.1 by hand: fee + slippage at entry, fee + stop slippage at the stop."""
    cost = (pj.FEE_PER_SIDE + pj.SLIPPAGE_PER_SIDE) * entry + (pj.FEE_PER_SIDE + pj.STOP_SLIPPAGE) * stop
    return cost / abs(entry - stop)


# --- calculation -----------------------------------------------------------------------------

def test_long_cost_matches_protocol_formula() -> None:
    check = cc.cost_check({"direction": "LONG", "entry": 80000.0, "stop": 79200.0})
    assert check["cost_r"] == pytest.approx(_expected_cost_r(80000.0, 79200.0), abs=1e-4)
    assert check["cost_r"] == 0.179
    assert check["cost_bps"] == pytest.approx(17.9, abs=0.01)
    assert check["cost_status"] == cc.COST_WITHIN_LIMIT


def test_short_uses_its_own_prices_as_fee_basis() -> None:
    check = cc.cost_check({"direction": "SHORT", "entry": 80000.0, "stop": 80800.0})
    assert check["cost_r"] == pytest.approx(_expected_cost_r(80000.0, 80800.0), abs=1e-4)
    # The stop of a short lies above the entry, so its fee basis is larger than for the mirrored long.
    long_check = cc.cost_check({"direction": "LONG", "entry": 80000.0, "stop": 79200.0})
    assert check["cost_r"] > long_check["cost_r"]
    assert check["cost_status"] == cc.COST_WITHIN_LIMIT


def test_estimate_equals_booked_costs_of_a_stop_out() -> None:
    """Regression: no second cost model. The estimate is what the journal books when the plan is stopped out."""
    entry = {"direction": "LONG", "entry": 79912.833, "stop": 79793.08, "fill_price": 79912.833, "tp_hits": [], "targets": []}
    fee_r, slippage_r = pj.costs_r(entry, entry["stop"], "STOP")
    assert cc.cost_check(entry)["cost_r"] == round(fee_r + slippage_r, 4)


def test_struct_trade_of_2026_10_24_is_not_tradable() -> None:
    """Live example from the struct journal: stop 0.15 % away, booked fee 0.6668 R + slippage 0.5334 R."""
    check = cc.cost_check({"direction": "LONG", "entry": 79912.833, "stop": 79793.08})
    assert check["cost_r"] == pytest.approx(1.2002, abs=1e-4)
    assert check["cost_status"] == cc.NOT_TRADABLE_COST


def test_tim_trade_of_2026_10_24_is_within_limit() -> None:
    check = cc.cost_check({"direction": "LONG", "entry": 80593.513, "stop": 79787.57787})
    assert check["cost_r"] == pytest.approx(0.1790, abs=1e-4)
    assert check["cost_status"] == cc.COST_WITHIN_LIMIT


# --- threshold -------------------------------------------------------------------------------

def test_exactly_the_limit_is_within() -> None:
    # entry 25100, stop 24920: costs 45.00 in price over a risk of 180 = 0.25 R exactly.
    check = cc.cost_check({"direction": "LONG", "entry": 25100.0, "stop": 24920.0})
    assert check["cost_r"] == 0.25
    assert check["cost_status"] == cc.COST_WITHIN_LIMIT
    assert cc.classify(0.25) == cc.COST_WITHIN_LIMIT


def test_just_above_the_limit_is_not_tradable() -> None:
    assert cc.classify(0.2501) == cc.NOT_TRADABLE_COST
    check = cc.cost_check({"direction": "LONG", "entry": 25100.0, "stop": 24921.0})
    assert check["cost_r"] > 0.25 and check["cost_status"] == cc.NOT_TRADABLE_COST


@pytest.mark.parametrize("value", [None, "0.1", float("nan"), float("inf"), -0.1, True])
def test_classify_never_passes_invalid_costs(value) -> None:
    assert cc.classify(value) == cc.COST_UNKNOWN


# --- missing or invalid data -----------------------------------------------------------------

@pytest.mark.parametrize("plan, reason", [
    ({"direction": "LONG", "stop": 99.0}, "entry_invalid"),
    ({"direction": "LONG", "entry": 100.0}, "stop_invalid"),
    ({"direction": "LONG", "entry": "abc", "stop": 99.0}, "entry_invalid"),
    ({"direction": "LONG", "entry": float("nan"), "stop": 99.0}, "entry_invalid"),
    ({"direction": "LONG", "entry": 100.0, "stop": float("inf")}, "stop_invalid"),
    ({"direction": "LONG", "entry": 0.0, "stop": -1.0}, "entry_invalid"),
    ({"direction": "LONG", "entry": 100.0, "stop": 100.0}, "stop_distance_zero"),
    ({"direction": "LONG", "entry": 100.0, "stop": 101.0}, "stop_on_wrong_side"),
    ({"direction": "SHORT", "entry": 100.0, "stop": 99.0}, "stop_on_wrong_side"),
    ({"direction": "FLAT", "entry": 100.0, "stop": 99.0}, "direction_unknown"),
    ({"entry": 100.0, "stop": 99.0}, "direction_unknown"),
    ({"direction": "LONG", "entry": True, "stop": 99.0}, "entry_invalid"),
])
def test_missing_or_invalid_data_is_unknown_never_within(plan, reason) -> None:
    check = cc.cost_check(plan)
    assert check["cost_status"] == cc.COST_UNKNOWN
    assert check["cost_reason"] == reason
    assert check["cost_r"] is None and check["cost_bps"] is None


def test_every_result_is_marked_informational() -> None:
    for plan in ({"direction": "LONG", "entry": 100.0, "stop": 99.0}, {"direction": "LONG"}):
        check = cc.cost_check(plan)
        assert check["informational_only"] is True and check["cost_limit_r"] == 0.25


# --- display only: nothing in the journal changes ---------------------------------------------

def _journal(*plans: dict) -> dict:
    journal = pj.empty_journal()
    pj.record_plans(journal, list(plans), T0)
    return journal


def test_with_cost_check_does_not_change_the_journal() -> None:
    journal = _journal(_plan("LONG", 100.0, 99.9), _plan("SHORT", 100.0, 101.0))
    before = copy.deepcopy(journal)
    view = cc.with_cost_check(journal)
    assert journal == before
    assert [e["cost_check"]["cost_status"] for e in view["entries"]] == [cc.NOT_TRADABLE_COST, cc.COST_WITHIN_LIMIT]
    assert view["cost_check_summary"] == {"limit_r": 0.25, "basis": cc.COST_BASIS, "version": cc.COST_CHECK_VERSION,
                                          "informational_only": True, "plans": 2, "cost_within_limit": 1,
                                          "not_tradable_cost": 1, "cost_unknown": 0}


def test_not_tradable_cost_changes_no_decision_or_level() -> None:
    """A plan with costs far above the limit is recorded and followed exactly like any other."""
    expensive = _plan("LONG", 100.0, 99.95)
    assert cc.cost_check(expensive)["cost_status"] == cc.NOT_TRADABLE_COST
    entry = _journal(expensive)["entries"][0]
    assert "cost_status" not in entry and "cost_check" not in entry
    assert (entry["entry"], entry["stop"]) == (100.0, 99.95)
    assert entry["journal_decision"] == pj.decision_fields(expensive)["journal_decision"]
    assert entry["status"] == pj.OPEN


def test_event_log_carries_no_cost_fields(tmp_path) -> None:
    path = tmp_path / "journal.json"
    journal = _journal(_plan("LONG", 100.0, 99.95))
    pj.save(journal, path)
    events = pj.diff_events(pj.empty_journal(), journal, recorded_at=T0, source_hash="x", source_range={})
    assert events and all("cost_status" not in json.dumps(e) and "cost_check" not in json.dumps(e) for e in events)
    assert "cost_check" not in path.read_text(encoding="utf-8")


# --- page and API ----------------------------------------------------------------------------

def test_page_shows_cost_column_status_and_tile() -> None:
    page = _plan_journal_page({}, _journal(_plan("LONG", 100.0, 99.95), _plan("SHORT", 100.0, 101.0)))
    assert "Kosten (Schätzung)" in page
    assert "NOT_TRADABLE_COST" in page and "COST_WITHIN_LIMIT" in page
    assert "Kosten über 0,25 R" in page
    assert "nur Anzeige" in page


def test_page_shows_unknown_for_invalid_stop() -> None:
    journal = _journal(_plan())
    journal["entries"][0]["stop"] = 101.0  # stop above a long entry: no valid risk
    page = _plan_journal_page({}, journal)
    assert "COST_UNKNOWN" in page and "nie automatisch eingehalten" in page


def test_api_serves_cost_fields(tmp_path) -> None:
    state = DashboardState()
    state.plan_journal_path = tmp_path / "tim.json"
    state.plan_journal_struct_path = tmp_path / "struct.json"
    journal = _journal(_plan("LONG", 100.0, 99.95))
    pj.save(journal, state.plan_journal_path)
    server = DashboardServer(state, port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/plan-journal", timeout=5) as response:
            data = json.loads(response.read())
    finally:
        server.stop()
    check = data["entries"][0]["cost_check"]
    assert set(check) >= {"cost_r", "cost_bps", "cost_status"}
    assert check["cost_status"] == cc.NOT_TRADABLE_COST
    assert data["cost_check_summary"]["not_tradable_cost"] == 1
    assert math.isfinite(check["cost_r"])
