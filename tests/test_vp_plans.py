from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.dashboard.vp_plans import RULE, bar_delta, build_vp_plans, volume_vs_hour, vp_plan

T0 = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
PREV = {"vah": 101.0, "poc": 100.0, "val": 99.0}


def _candle(i: int, low: float, high: float, close: float, volume: float = 10.0) -> dict:
    opened = T0 + timedelta(minutes=30 * i)
    return {"timeframe": "30m", "open_time": opened, "close_time": opened + timedelta(minutes=30),
            "open": (low + high) / 2, "high": high, "low": low, "close": close, "volume": volume}


def _long_item(target: float | None = 104.0) -> dict:
    return {"direction": "LONG", "entry": [{"label": "Vortag VAH", "price": 101.0}, {"label": "Vortag POC", "price": 100.0}],
            "invalid": {"label": "Vortag VAL", "price": 99.0},
            "target": {"label": "naked POC 30.10.", "price": target} if target else None, "picky": False}


def test_long_in_higher_after_a_touch_of_the_previous_vah() -> None:
    candle = _candle(10, 100.6, 101.5, 101.3)
    plan, reason = vp_plan(_long_item(), "HIGHER", candle, -12.0, 1.4)
    assert reason is None and plan["rule"] == RULE and plan["direction"] == "LONG"
    assert plan["entry"] == 101.3 and plan["stop"] == round(99.0 * (1 - 0.0005), 2)  # behind the previous VAL (reel: invalid)
    assert plan["targets"] == [104.0] * 3 and plan["invalidation_level"] == 99.0 and plan["invalidation_side"] == "<"
    assert plan["touch"]["level"] == "Vortag VAH" and plan["absorption"] is True and plan["volume_vs_hour"] == 1.4


def test_the_deeper_touched_level_counts_and_no_touch_gives_nothing() -> None:
    deep = _candle(10, 99.8, 101.2, 100.4)  # through the VAH down to the POC, closed between them
    plan, _ = vp_plan(_long_item(), "HIGHER", deep, None, None)
    assert plan["touch"]["level"] == "Vortag POC" and plan["absorption"] is None
    assert vp_plan(_long_item(), "HIGHER", _candle(10, 101.2, 102.0, 101.8), None, None) == (None, None)
    # Closed below the level: no reaction, no plan.
    assert vp_plan(_long_item(), "HIGHER", _candle(10, 100.6, 101.5, 100.9), None, None) == (None, None)


def test_overlap_needs_absorption_and_a_target_at_enough_r() -> None:
    candle = _candle(10, 100.6, 101.5, 101.3)
    assert "ohne Absorption" in vp_plan(_long_item(), "OVERLAP_HIGHER", candle, 5.0, None)[1]
    assert "ohne Absorption" in vp_plan(_long_item(), "OVERLAP_HIGHER", candle, None, None)[1]
    assert vp_plan(_long_item(), "OVERLAP_HIGHER", candle, -5.0, None)[0] is not None
    assert "kein Ziel" in vp_plan(_long_item(None), "HIGHER", candle, None, None)[1]
    assert "nur" in vp_plan(_long_item(103.0), "HIGHER", candle, None, None)[1]  # 1.7 to target, 2.35 to the stop


def test_short_fade_in_inside_and_contexts_without_plans() -> None:
    item = {"direction": "SHORT", "entry": [{"label": "Vortag VAH", "price": 101.0}], "invalid": {"label": "über Vortag VAH angenommen", "price": 101.0},
            "target": {"label": "Vortag POC", "price": 100.0}}
    candle = _candle(10, 100.7, 101.2, 100.8)
    plan, _ = vp_plan(item, "INSIDE", candle, 3.0, None)
    assert plan["direction"] == "SHORT" and plan["stop"] == round(101.2 * 1.0005, 2) and plan["absorption"] is True
    assert plan["invalidation_level"] == 101.2 and plan["invalidation_side"] == ">"
    candles = [_candle(i, 100.0, 100.5, 100.2) for i in range(10)] + [candle]
    now = candle["close_time"]
    for state in ("WIDER", "EARLY", "UNKNOWN"):
        assert build_vp_plans({"value_context": {"state": state, "playbook": [item]}}, candles, now)["plans"] == []
    result = build_vp_plans({"value_context": {"state": "INSIDE", "playbook": [item]}}, candles, now)
    assert len(result["plans"]) == 1
    assert build_vp_plans({"value_context": {"state": "INSIDE", "playbook": [item]}}, candles, now + timedelta(hours=2))["plans"] == []


def test_volume_against_the_same_half_hour_and_delta_from_the_store() -> None:
    candles = [_candle(48 * d + 20, 99, 101, 100, volume=10.0) for d in range(3)]
    last = _candle(48 * 3 + 20, 99, 101, 100, volume=25.0)
    assert volume_vs_hour([*candles, _candle(5, 99, 101, 100, 99.0), last], last) == 2.5
    assert volume_vs_hour([last], last) is None
    start = int(last["open_time"].timestamp())
    store = {"bucket_seconds": 300, "days": {"2026-11-06": [[start, 100.0, 7.0, 2.0], [start + 600, 100.0, 1.0, 3.0], [start + 1800, 100.0, 50.0, 0.0]]}}
    assert bar_delta(store, last) == -3.0 and bar_delta(None, last) is None and bar_delta({"days": {}}, last) is None


def test_update_with_vp_rule_writes_its_own_journal(tmp_path, monkeypatch) -> None:
    from src.dashboard import session_map
    from src.dashboard.plan_journal import RULE_VP, load, update
    from tests.test_structure_plan import _runtime_series

    series = _runtime_series()
    now = datetime(2026, 10, 24, 14, 0, 30, tzinfo=timezone.utc)
    original = session_map.build_session_map

    def with_context(closed, at):
        prep = original(closed, at)
        last = closed["30m"][-1]
        level = (last["low"] + last["close"]) / 2
        prep["value_context"] = {"state": "HIGHER", "playbook": [{
            "direction": "LONG", "entry": [{"label": "Vortag VAH", "price": level}], "invalid": {"label": "Vortag VAL", "price": level * 0.99},
            "target": {"label": "naked POC 20.10.", "price": last["close"] + last["close"] * 0.03}}]}
        return prep

    monkeypatch.setattr(session_map, "build_session_map", with_context)
    journal = update(tmp_path / "vp.json", series, now=now, rule=RULE_VP)
    assert journal["rule"] == RULE_VP and journal["last_plan_candle"] == "2026-10-24T14:00:00Z"
    stored = load(tmp_path / "vp.json")
    assert stored["entries"], stored.get("last_skips")
    for entry in stored["entries"]:
        assert entry["rule"] == RULE_VP and entry["scenario_type"] == "VP_CONTEXT" and entry["value_context"] == "HIGHER"
        assert entry["journal_decision"] == "NO_TRADE" and "absorption" in entry and "volume_vs_hour" in entry


def test_vp_journal_is_listed_for_the_public_page_and_runs_in_main(tmp_path) -> None:
    from pathlib import Path
    from types import SimpleNamespace

    from src.dashboard.public_en import JOURNAL_KEYS, journal_page
    from src.dashboard.state import plan_journal_paths

    state = SimpleNamespace(plan_journal_path=tmp_path / "t.json", plan_journal_vp_path=tmp_path / "v.json")
    assert plan_journal_paths(state)["vp"] == tmp_path / "v.json" and "vp" in JOURNAL_KEYS
    page = journal_page({"tim": {"entries": []}, "vp/1": {"entries": []}}, "vp")
    assert "Volume profile rule 30m" in page
    main_source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "rule=RULE_VP, footprint=footprint" in main_source
