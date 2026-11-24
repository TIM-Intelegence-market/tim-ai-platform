from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.models.market_data import Trade
from src.orderflow import live_state as ls

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
SYMBOL = "BTCUSDT"


def trade(seconds: float, price: float, qty: float, buy: bool, tid: int) -> Trade:
    return Trade(SYMBOL, price, qty, T0 + timedelta(seconds=seconds), tid, buyer_is_maker=not buy)


def quiet_baseline(tracker: ls.LiveOrderflowTracker, minutes: int = 20, price: float = 75000.0) -> int:
    """20 quiet minutes: one small buy and one small sell per minute, price flat."""
    tid = 0
    trades = []
    for minute in range(minutes):
        trades.append(trade(minute * 60 + 10, price, 0.1, True, tid := tid + 1))
        trades.append(trade(minute * 60 + 40, price, 0.1, False, tid := tid + 1))
    tracker.ingest(trades)
    return tid


def test_ingest_tracks_day_cvd_extremes_and_skips_replayed_ids():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    assert tracker.ingest([trade(0, 75000, 1.0, True, 1), trade(1, 75010, 0.5, False, 2)]) == 2
    assert tracker.ingest([trade(1, 75010, 0.5, False, 2), trade(2, 74990, 0.25, True, 3)]) == 1
    assert tracker.day_cvd == pytest.approx(0.75)
    assert (tracker.day_high, tracker.day_low, tracker.last_trade_id) == (75010, 74990, 3)
    assert tracker.ingest([Trade("ETHUSDT", 2000, 1, T0, 9, False)]) == 0


def test_buyer_wave_building_with_strength_and_text():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tid = quiet_baseline(tracker)
    base = 20 * 60
    trades = []
    for minute, (buy_qty, step) in enumerate(((2.0, 5), (4.0, 10), (8.0, 20))):
        for k in range(4):
            trades.append(trade(base + minute * 60 + k * 10, 75000 + step * (minute + 1) + k, buy_qty / 4, True, tid := tid + 1))
        trades.append(trade(base + minute * 60 + 50, 75000 + step * (minute + 1), 0.2, False, tid := tid + 1))
    tracker.ingest(trades)
    now = T0 + timedelta(seconds=base + 180)
    state = tracker.snapshot(now)
    assert state["wave"]["direction"] == "auf"
    assert state["wave"]["phase"] == "aufbauend"
    assert state["wave"]["strength"] == 3 and state["tempo"] > 2.5
    assert state["wave"]["exhaustion"] is False
    assert state["windows"]["5m"]["delta"] > 0 and state["stale"] is False
    assert state["text"].startswith("Preis ") and "Käuferwelle" in state["text"]
    assert json.dumps(state)  # serialisable


def test_fading_wave_flags_exhaustion_when_price_stalls():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tid = quiet_baseline(tracker)
    base = 20 * 60
    trades = []
    # minute 1: strong selling down to 74900, minute 2: half of it, minute 3: almost nothing, price flat
    for minute, (sell_qty, price) in enumerate(((8.0, 74900.0), (4.0, 74890.0), (0.3, 74890.0))):
        for k in range(4):
            trades.append(trade(base + minute * 60 + k * 10, price - k, sell_qty / 4, False, tid := tid + 1))
    tracker.ingest(trades)
    state = tracker.snapshot(T0 + timedelta(seconds=base + 180))
    assert state["wave"]["direction"] == "ab"
    assert state["wave"]["phase"] == "ebbt ab"
    assert state["wave"]["exhaustion"] is True
    assert "Exhaustion" in state["text"]


def test_levels_absorption_imbalance_and_perp_delta():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tid = quiet_baseline(tracker)
    base = 20 * 60
    trades = []
    # heavy selling into 74950 (prior VAL) that never trades below it, price holds above
    for k in range(10):
        trades.append(trade(base + k * 5, 74952.0, 1.0, False, tid := tid + 1))
    trades.append(trade(base + 55, 74960.0, 0.1, True, tid := tid + 1))
    tracker.ingest(trades)
    now = T0 + timedelta(seconds=base + 60)
    perp_store = {"symbol": "BTCUSDT", "bucket_seconds": 300, "updated_at": now.isoformat(),
                  "days": {"2026-11-08": [[now.timestamp() - 300, 74950.0, 3.0, 1.0], [now.timestamp() - 900, 74950.0, 1.0, 5.0],
                                           [now.timestamp() - 7200, 74000.0, 50.0, 0.0]]}}
    levels = [{"name": "Vortag VAL", "price": 74950.0}, {"name": "Vortag VAH", "price": 76000.0}]
    state = tracker.snapshot(now, levels, perp_store)
    rows = {row["name"]: row for row in state["levels"]}
    assert "Vortag VAH" not in rows  # farther than LEVEL_RANGE_PCT
    val = rows["Vortag VAL"]
    assert val["tested_15m"] and not val["broke_through"] and val["absorption"] is True
    assert val["imbalance"] == "Verkäufer" and val["bid"] == pytest.approx(10.0)
    assert state["perp"]["delta_5m"] == pytest.approx(-2.0) and state["perp"]["delta_15m"] == pytest.approx(2.0)
    assert "Absorption" in state["text"] and "Perp-Delta" in state["text"]


def test_stale_without_trades_and_levels_from_profiles(tmp_path):
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    state = tracker.snapshot(T0)
    assert state["stale"] is True and state["wave"]["direction"] == "keine" and "keine frischen" in state["text"]
    profiles = [{"running": False, "vah": 76000.0, "val": 74950.0, "poc": 75400.0, "poc_mid": 75402.5},
                {"running": True, "vah": 75800.0, "val": 75100.0, "poc": 75300.0, "poc_mid": 75302.5}]
    names = [row["name"] for row in ls.levels_from_profiles(profiles)]
    assert names == ["Vortag VAH", "Vortag VAL", "Vortag POC", "Tages-POC"]
    path = ls.save(state, tmp_path / "of" / "lage.json")
    assert ls.load(path)["schema"] == ls.SCHEMA_VERSION and not path.with_suffix(".json.tmp").exists()
    assert ls.load(tmp_path / "missing.json") is None


def test_rejects_bad_parameters():
    with pytest.raises(ValueError):
        ls.LiveOrderflowTracker(SYMBOL, 0)
    with pytest.raises(ValueError):
        ls.LiveOrderflowTracker(SYMBOL, 5.0, keep_seconds=600)


def test_day_values_come_from_the_running_profile():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([trade(0, 75000, 1.0, True, 1), trade(1, 75010, 0.5, False, 2)])
    profile = {"running": True, "step": 50.0, "delta": -120.5, "poc": 74800.0,
               "rows": [{"price": 74000.0, "volume": 3.0}, {"price": 74500.0, "volume": 0.0}, {"price": 75500.0, "volume": 1.0}]}
    state = tracker.snapshot(T0 + timedelta(seconds=2), day_profile=profile)
    assert state["day"]["cvd"] == -120.5 and state["day"]["low"] == 74000.0 and state["day"]["high"] == 75550.0
    assert "Tagesprofil" in state["day"]["source"]
    names = {row["name"] for row in state["levels"]}
    assert "Tages-Tief" not in names  # 1.3 % away, outside LEVEL_RANGE_PCT
    without = tracker.snapshot(T0 + timedelta(seconds=2))
    assert without["day"]["high"] == 75010 and without["day"]["source"] == "seit Start der Runtime"


# Paket B (#372): a trade without a known aggressor side is UNKNOWN, never a buy.
def _raw(seconds: float, qty: float, maker: object, tid: int, price: float = 75000.0) -> Trade:
    return Trade(SYMBOL, price, qty, T0 + timedelta(seconds=seconds), tid, buyer_is_maker=maker)  # type: ignore[arg-type]


@pytest.mark.parametrize("maker", [None, "false", "true", 0, 1])
def test_aggressor_side_only_accepts_real_bools(maker):
    assert ls.aggressor_side(maker) == ls.UNKNOWN
    assert ls.aggressor_side(True) == ls.SELL and ls.aggressor_side(False) == ls.BUY


def test_unknown_side_does_not_raise_buy_delta_or_cvd():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([_raw(0, 2.0, None, 1)])
    state = tracker.snapshot(T0 + timedelta(seconds=5))
    one = state["windows"]["1m"]
    assert one["delta"] == 0 and one["buy_share"] is None
    assert one["volume"] == pytest.approx(2.0) and one["unknown_volume"] == pytest.approx(2.0) and one["unknown_trades"] == 1
    assert tracker.day_cvd == 0 and state["day"]["unknown_volume"] == pytest.approx(2.0) and tracker.unknown_trades == 1
    assert state["wave"]["direction"] == "keine"


def test_buy_share_denominator_is_known_volume_only():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([_raw(0, 1.0, False, 1), _raw(1, 1.0, True, 2), _raw(2, 2.0, None, 3), _raw(3, 4.0, "false", 4)])
    one = tracker.snapshot(T0 + timedelta(seconds=10))["windows"]["1m"]
    assert one["buy_share"] == pytest.approx(0.5)  # 1 of 2 known, the 6 unknown are not in the denominator
    assert one["volume"] == pytest.approx(8.0) and one["delta"] == 0 and one["unknown_volume"] == pytest.approx(6.0)


def test_levels_keep_unknown_out_of_bid_ask_and_delta():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([_raw(0, 1.0, False, 1, 75000), _raw(1, 3.0, None, 2, 75000)])
    state = tracker.snapshot(T0 + timedelta(seconds=10), [{"name": "L", "price": 75000.0}])
    row = state["levels"][0]
    assert (row["bid"], row["ask"], row["unknown"], row["delta"]) == (0.0, 1.0, 3.0, 1.0)
    assert state["schema"] == "orderflow-lage/2"


# Codex #376: the consumer (Orderflow-Schatten) must not read unknown flow as neutral flow.
def test_pure_unknown_flow_is_unbekannt_in_the_shadow_not_neutral():
    from src.dashboard import orderflow_shadow as shadow

    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([_raw(0, 5.0, None, 1)])
    view = shadow.lage_view(tracker.snapshot(T0))
    assert view["known_share"] == 0.0
    assert shadow.gate("LONG", view) == shadow.UNBEKANNT and shadow.gate("SHORT", view) == shadow.UNBEKANNT
    assert shadow.should_exit("LONG", view) is None


def test_mostly_unknown_flow_is_unbekannt_and_mostly_known_is_judged():
    from src.dashboard import orderflow_shadow as shadow

    mostly = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    mostly.ingest([_raw(0, 1.0, False, 1), _raw(1, 9.0, None, 2)])
    view = shadow.lage_view(mostly.snapshot(T0 + timedelta(seconds=2)))
    assert view["known_share"] == pytest.approx(0.1) and shadow.gate("LONG", view) == shadow.UNBEKANNT
    known = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    known.ingest([_raw(0, 99.0, False, 1), _raw(1, 1.0, None, 2)])
    view = shadow.lage_view(known.snapshot(T0 + timedelta(seconds=2)))
    assert view["known_share"] == pytest.approx(0.99) and shadow.gate("LONG", view) != shadow.UNBEKANNT
    assert shadow.known_share(None) is None and shadow.gate("LONG", None) == shadow.NEUTRAL  # no Lage: as before


def test_shadow_summary_counts_unknown_side_plans_apart():
    from src.dashboard import orderflow_shadow as shadow

    plans = {"a": {"gate_at_plan": shadow.UNBEKANNT, "journal": {"status": "CLOSED", "net_r": -1.0}},
             "b": {"gate_at_plan": shadow.NEUTRAL, "lage_at_plan": {"price": 1.0},
                   "journal": {"status": "CLOSED", "net_r": 1.0}},
             "c": {"gate_at_plan": shadow.NEUTRAL, "lage_at_plan": None, "journal": {"status": "CLOSED", "net_r": 2.0}}}
    out = shadow.summary({"plans": plans})
    assert out["side_unknown"] == 1
    assert out["by_gate"] == {shadow.UNBEKANNT: {"n": 1, "sum_net_r": -1.0}, shadow.NEUTRAL: {"n": 1, "sum_net_r": 1.0},
                              shadow.OHNE_LAGE: {"n": 1, "sum_net_r": 2.0}}   # no Lage is not neutral flow


def test_known_share_boundary_and_lowest_window_counts():
    from src.dashboard import orderflow_shadow as shadow

    def lage(windows):
        return {"price": 1.0, "wave": {"direction": "auf"}, "windows": windows}

    at = {"1m": {"volume": 100.0, "unknown_volume": 5.0}}
    assert shadow.known_share(lage(at)) == 0.95 and shadow.gate("LONG", shadow.lage_view(lage(at))) == shadow.BESTAETIGT
    below = {"1m": {"volume": 10000.0, "unknown_volume": 501.0}}
    assert shadow.gate("LONG", shadow.lage_view(lage(below))) == shadow.UNBEKANNT
    mixed = {"1m": {"volume": 10.0, "unknown_volume": 5.0}, "5m": {"volume": 1000.0, "unknown_volume": 5.0},
             "15m": {"volume": 0.0, "unknown_volume": 0.0}}               # one bad window is enough, an empty one is skipped
    assert shadow.known_share(lage(mixed)) == 0.5 and shadow.gate("LONG", shadow.lage_view(lage(mixed))) == shadow.UNBEKANNT


def test_known_side_is_compared_exactly_not_rounded():
    """Codex Mission 06: 0.94996 must not pass as 0.95."""
    from src.dashboard import orderflow_shadow as shadow

    def view(volume, unknown):
        return shadow.lage_view({"price": 100.0, "wave": {"direction": "auf"},
                                 "windows": {"1m": {"volume": volume, "unknown_volume": unknown}}})

    assert shadow.gate("LONG", view(100000.0, 5004.0)) == shadow.UNBEKANNT            # 0.94996
    assert shadow.gate("LONG", view(100000.0, 5000.0)) == shadow.BESTAETIGT           # exactly 0.95
    assert shadow.gate("LONG", view(100000.0, 4999.0)) == shadow.BESTAETIGT           # above
    assert view(100000.0, 5004.0)["known_share"] == pytest.approx(0.94996)            # raw, for display


@pytest.mark.parametrize("volume, unknown", [(float("nan"), 0.0), (float("inf"), 0.0), (-1.0, 0.0), (10.0, -1.0),
                                             (10.0, 11.0), ("10", 0.0), (True, 0.0), (10.0, float("nan"))])
def test_invalid_volumes_are_unknown_downstream(volume, unknown):
    from src.dashboard import orderflow_shadow as shadow

    v = shadow.lage_view({"price": 100.0, "wave": {"direction": "auf", "strength": 3},
                          "windows": {"1m": {"volume": volume, "unknown_volume": unknown}}})
    assert v["side_ok"] is False and v["side_status"] == "INVALID"
    assert shadow.gate("LONG", v) == shadow.UNBEKANNT and shadow.should_exit("SHORT", v) is None


def test_empty_volume_is_no_evidence_and_old_views_still_work():
    from src.dashboard import orderflow_shadow as shadow

    # Codex Mission 07: volume 0 (or none) is no evidence, so even a forced wave "auf" is UNBEKANNT, never BESTÄTIGT.
    empty = shadow.lage_view({"price": 100.0, "wave": {"direction": "auf", "strength": 2}, "windows": {"5m": {"volume": 0.0, "unknown_volume": 0.0}}})
    assert empty["side_ok"] is False and empty["side_status"] == "EMPTY" and shadow.gate("LONG", empty) == shadow.UNBEKANNT
    no_windows = shadow.lage_view({"price": 100.0, "wave": {"direction": "auf", "strength": 2}})
    assert shadow.gate("LONG", no_windows) == shadow.UNBEKANNT and no_windows["side_status"] == "MISSING"
    assert shadow.side_unknown({"known_share": 0.9}) and not shadow.side_unknown({"known_share": 0.95})  # pre-07 views


_WAVE = {"price": 100.0, "wave": {"direction": "auf", "strength": 3}}
_FULL = {"volume": 100.0, "unknown_volume": 0.0}


def _without(name):
    return {k: v for k, v in _FULL.items() if k != name}


@pytest.mark.parametrize("window, status", [
    (_without("unknown_volume"), "MISSING"),            # Codex Mission 07-FINAL: absent is not a proven 0
    (_without("volume"), "MISSING"),
    ({}, "MISSING"),                                    # a window with neither field
    ({**_FULL, "unknown_volume": None}, "MISSING"),     # null is no number either
    ({**_FULL, "volume": None}, "MISSING"),
    ({**_FULL, "unknown_volume": "0"}, "INVALID"),
    ({**_FULL, "unknown_volume": False}, "INVALID"),    # False is not 0
    ({"volume": "x"}, "INVALID"),                       # invalid wins over missing
])
def test_missing_null_and_invalid_fields_are_never_a_known_side(window, status):
    from src.dashboard import orderflow_shadow as shadow

    for windows in ({"1m": window}, {"1m": dict(_FULL), "5m": window}, {"5m": window, "15m": dict(_FULL)}):
        v = shadow.lage_view({**_WAVE, "windows": windows})
        assert (v["side_ok"], v["side_status"]) == (False, status)
        for direction in ("LONG", "SHORT"):
            assert shadow.gate(direction, v) == shadow.UNBEKANNT and shadow.should_exit(direction, v) is None


def test_explicit_zero_is_a_value_and_the_only_way_to_a_known_side():
    from src.dashboard import orderflow_shadow as shadow

    for zero in (0, 0.0):
        v = shadow.lage_view({**_WAVE, "windows": {"1m": {"volume": 100.0, "unknown_volume": zero}}})
        assert (v["side_ok"], v["side_status"], v["known_share"]) == (True, "OK", 1.0)
        assert shadow.gate("LONG", v) == shadow.BESTAETIGT and shadow.gate("SHORT", v) == shadow.GEGEN
    for windows, status in ((None, "MISSING"), ({}, "EMPTY"), ([], "INVALID"), ("1m", "INVALID"), ({"1m": None}, "INVALID")):
        v = shadow.lage_view({**_WAVE, "windows": windows})
        assert (v["side_ok"], v["side_status"]) == (False, status) and shadow.gate("LONG", v) == shadow.UNBEKANNT


def test_a_lage_written_before_the_side_fields_existed_is_unknown_not_confirmed():
    """Upgrade path: an ``orderflow-lage/1`` file (volume, no unknown_volume) read by the new code."""
    from src.dashboard import orderflow_shadow as shadow

    legacy = {"schema": "orderflow-lage/1", **_WAVE,
              "windows": {name: {"trades": 5, "volume": 12.0, "delta": 3.0} for name in ("1m", "5m", "15m")}}
    v = shadow.lage_view(legacy)
    assert v["side_status"] == "MISSING" and v["known_share"] is None and shadow.gate("LONG", v) == shadow.UNBEKANNT


def test_the_tracker_always_writes_both_fields_also_for_empty_windows():
    """Producer side of the contract: every window of a real snapshot carries both numbers explicitly."""
    from src.dashboard import orderflow_shadow as shadow

    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    for state in (tracker.snapshot(T0),):
        for window in state["windows"].values():
            assert isinstance(window["volume"], float) and isinstance(window["unknown_volume"], float)
    quiet_baseline(tracker)
    state = tracker.snapshot(T0 + timedelta(seconds=20 * 60))
    assert all(type(w["unknown_volume"]) is float and type(w["volume"]) is float for w in state["windows"].values())
    assert shadow.known_side(state)["status"] == "OK"
