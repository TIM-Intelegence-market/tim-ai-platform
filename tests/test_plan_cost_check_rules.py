"""Validation of the cost check (PR #408) across directions, rounding, invalid data and all three plan rules."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from src.dashboard import plan_journal as pj
from src.dashboard.plan_cost_check import COST_UNKNOWN, COST_WITHIN_LIMIT, NOT_TRADABLE_COST, cost_check, with_cost_check
from src.research_lab.protocol import BASE_COSTS


def _expected(entry: float, stop: float) -> float:
    """Protocol 1.1 written out independently: fill at entry, stop execution at stop."""
    m = BASE_COSTS
    return (m.fee * entry + m.slippage * entry + m.fee * stop + m.stop_slippage * stop) / abs(entry - stop)


def _plan(direction: str, entry: float, distance: float) -> dict:
    stop = entry * (1 - distance) if direction == "LONG" else entry * (1 + distance)
    return {"direction": direction, "entry": entry, "stop": stop}


def test_journal_rates_are_the_protocol_rates() -> None:
    assert (pj.FEE_PER_SIDE, pj.SLIPPAGE_PER_SIDE, pj.STOP_SLIPPAGE) == (BASE_COSTS.fee, BASE_COSTS.slippage, BASE_COSTS.stop_slippage)
    assert pj.COST_MODEL_VERSION == "protocol/1.1"


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("entry", [1.2345, 100.0, 80593.513])
@pytest.mark.parametrize("distance", [0.0005, 0.0015, 0.005, 0.0072, 0.01, 0.02, 0.05])
def test_cost_r_and_bps_match_the_independent_formula(direction, entry, distance) -> None:
    plan = _plan(direction, entry, distance)
    result = cost_check(plan)
    expected = _expected(entry, plan["stop"])
    # fee_r and slippage_r are each rounded to 4 decimals, then the sum again: at most 0.00015 R apart.
    assert abs(result["cost_r"] - expected) <= 0.00015
    expected_bps = expected * abs(entry - plan["stop"]) / entry * 10_000
    assert abs(result["cost_bps"] - expected_bps) <= 0.01 + 0.00015 * distance * 10_000
    assert result["cost_status"] == (COST_WITHIN_LIMIT if result["cost_r"] <= 0.25 else NOT_TRADABLE_COST)


def test_short_costs_more_than_long_at_the_same_distance() -> None:
    # The SHORT stop lies above entry, so its exit side is charged on a higher price.
    long, short = cost_check(_plan("LONG", 80000.0, 0.01)), cost_check(_plan("SHORT", 80000.0, 0.01))
    assert short["cost_r"] > long["cost_r"]
    assert short["fee_r_estimate"] > long["fee_r_estimate"] and short["slippage_r_estimate"] > long["slippage_r_estimate"]


@pytest.mark.parametrize("direction, within, above", [("LONG", 0.0072, 0.0071), ("SHORT", 0.0073, 0.0072)])
def test_minimum_stop_distance_for_the_limit(direction, within, above) -> None:
    # About 0.72 % for LONG, a little more for SHORT (exit side on the higher stop price).
    assert cost_check(_plan(direction, 80000.0, within))["cost_status"] == COST_WITHIN_LIMIT
    assert cost_check(_plan(direction, 80000.0, above))["cost_status"] == NOT_TRADABLE_COST


def test_tiny_stop_distance_is_not_tradable_and_finite() -> None:
    result = cost_check({"direction": "LONG", "entry": 80000.0, "stop": 79999.99})
    assert result["cost_status"] == NOT_TRADABLE_COST and math.isfinite(result["cost_r"]) and result["cost_r"] > 1000


def test_estimate_is_the_same_for_every_rule() -> None:
    plan = _plan("SHORT", 80000.0, 0.004)
    results = [cost_check({**plan, "rule": rule}) for rule in (pj.RULE_TIM, pj.RULE_STRUCT, pj.RULE_LEVEL)]
    assert results[0] == results[1] == results[2]


def test_estimate_uses_the_plan_entry_not_a_later_fill() -> None:
    plan = {**_plan("LONG", 80000.0, 0.01), "fill_price": 79950.0}
    assert cost_check(plan) == cost_check(_plan("LONG", 80000.0, 0.01))


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("field, value", [
    ("entry", None), ("entry", 0), ("entry", -1.0), ("entry", float("nan")), ("entry", float("inf")), ("entry", True), ("entry", "abc"), ("entry", [1]),
    ("stop", None), ("stop", 0), ("stop", -1.0), ("stop", float("nan")), ("stop", float("-inf")), ("stop", False), ("stop", "abc"), ("stop", {}),
])
def test_invalid_prices_are_unknown_for_both_directions(direction, field, value) -> None:
    plan = {**_plan(direction, 80000.0, 0.01), field: value}
    result = cost_check(plan)
    assert result["cost_status"] == COST_UNKNOWN and result["cost_r"] is None and result["cost_bps"] is None


@pytest.mark.parametrize("plan", [{"direction": "LONG", "entry": 80000.0}, {"direction": "SHORT", "entry": 80000.0},
                                  {"direction": "LONG", "stop": 79000.0}, {"direction": None, "entry": 80000.0, "stop": 79000.0}, {}])
def test_missing_fields_are_unknown(plan) -> None:
    assert cost_check(plan)["cost_status"] == COST_UNKNOWN


def test_numeric_strings_are_read_as_numbers() -> None:
    # The journal stores floats; a numeric string from a hand-edited view is read, not rejected.
    assert cost_check({"direction": "LONG", "entry": "80000", "stop": "79000"}) == cost_check({"direction": "LONG", "entry": 80000.0, "stop": 79000.0})


# --- all three plan rules, through the journal's own recording -----------------------------------

T0 = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)


def _check_entries(journal: dict) -> list[dict]:
    before = {e["id"]: {k: e.get(k) for k in pj.DECISION_FIELDS} for e in journal["entries"]}
    view = with_cost_check(journal)
    assert "cost_check" not in journal["entries"][0] if journal["entries"] else True
    for entry in view["entries"]:
        check = entry["cost_check"]
        assert check["informational_only"] is True
        assert check["cost_r"] == pytest.approx(_expected(entry["entry"], entry["stop"]), abs=0.00015)
        assert {k: entry.get(k) for k in pj.DECISION_FIELDS} == before[entry["id"]]
    assert view["cost_check_summary"]["plans"] == len(journal["entries"])
    return view["entries"]


def test_tim_rule_entries_get_a_cost_check(tmp_path) -> None:
    from tests.test_structure_plan import _runtime_series

    journal = pj.update(tmp_path / "tim.json", _runtime_series(), now=datetime(2026, 10, 24, 14, 0, 30, tzinfo=timezone.utc), rule=pj.RULE_TIM)
    entries = _check_entries(journal)
    assert entries and {e["direction"] for e in entries} == {"LONG", "SHORT"}


def test_struct_rule_entries_get_a_cost_check_and_tight_stops_are_marked() -> None:
    from src.dashboard.structure_plan import structural_plan
    from tests.test_structure_plan import _places, _plan as struct_plan

    journal = pj.empty_journal()
    wide, _ = structural_plan(struct_plan(), highs=[], lows=[97.0], places=_places(106, 108, 112))
    tight, _ = structural_plan(struct_plan("SHORT", entry=100.0, low=99.0, high=100.1), highs=[100.15], lows=[], places=_places(99.0, 98.0, 97.0))
    assert wide is not None and tight is not None
    pj.record_plans(journal, [wide, tight], T0)
    by_direction = {e["direction"]: e for e in _check_entries(journal)}
    assert all(e["rule"] == pj.RULE_STRUCT for e in by_direction.values())
    assert by_direction["LONG"]["cost_check"]["cost_status"] == COST_WITHIN_LIMIT
    assert by_direction["SHORT"]["cost_check"]["cost_status"] == NOT_TRADABLE_COST


def test_level_rule_entries_get_a_cost_check(monkeypatch) -> None:
    from src.dashboard import session_map
    from tests.test_level_plans import _candles, _prep

    candles = _candles(96)
    series = {"30m": [{**c, "open_time": c["open_time"].isoformat(), "close_time": c["close_time"].isoformat()} for c in candles]}
    monkeypatch.setattr(session_map, "build_session_map", lambda closed, at: _prep())
    plans, dropped = pj._level(series, candles[-1]["close_time"], {"analysis": {}})
    assert plans, dropped
    journal = pj.empty_journal()
    pj.record_plans(journal, plans, candles[-1]["close_time"])
    entries = _check_entries(journal)
    assert entries and all(e["rule"] == pj.RULE_LEVEL for e in entries)
    assert all(e["cost_check"]["cost_status"] in {COST_WITHIN_LIMIT, NOT_TRADABLE_COST} for e in entries)


@pytest.mark.parametrize("rule", [pj.RULE_TIM, pj.RULE_STRUCT, pj.RULE_LEVEL])
def test_entry_without_stop_is_unknown_in_every_rule(rule) -> None:
    journal = {**pj.empty_journal(), "rule": rule, "entries": [{"id": "x", "rule": rule, "direction": "LONG", "entry": 100.0, "stop": None}]}
    view = with_cost_check(journal)
    assert view["entries"][0]["cost_check"]["cost_status"] == COST_UNKNOWN
    assert view["cost_check_summary"]["cost_unknown"] == 1 and view["cost_check_summary"]["cost_within_limit"] == 0
