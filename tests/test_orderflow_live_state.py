from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.models.market_data import Trade
from src.orderflow import live_state as ls

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
SYMBOL = "BTCUSDT"


def _feed(tracker, trades):
    """Synthetic trades: each one available at its own event time, said explicitly (the tracker never assumes it)."""
    return sum(tracker.ingest([t], available_at=t.event_time) for t in trades)


def trade(seconds: float, price: float, qty: float, buy: bool, tid: int) -> Trade:
    return Trade(SYMBOL, price, qty, T0 + timedelta(seconds=seconds), tid, buyer_is_maker=not buy)


def quiet_baseline(tracker: ls.LiveOrderflowTracker, minutes: int = 20, price: float = 75000.0) -> int:
    """20 quiet minutes: one small buy and one small sell per minute, price flat."""
    tid = 0
    trades = []
    for minute in range(minutes):
        trades.append(trade(minute * 60 + 10, price, 0.1, True, tid := tid + 1))
        trades.append(trade(minute * 60 + 40, price, 0.1, False, tid := tid + 1))
    _feed(tracker, trades)
    return tid


def test_ingest_tracks_day_cvd_extremes_and_skips_replayed_ids():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    assert _feed(tracker, [trade(0, 75000, 1.0, True, 1), trade(1, 75010, 0.5, False, 2)]) == 2
    assert _feed(tracker, [trade(1, 75010, 0.5, False, 2), trade(2, 74990, 0.25, True, 3)]) == 1
    assert tracker.day_cvd == pytest.approx(0.75)
    assert (tracker.day_high, tracker.day_low, tracker.last_trade_id) == (75010, 74990, 3)
    assert _feed(tracker, [Trade("ETHUSDT", 2000, 1, T0, 9, False)]) == 0


def test_buyer_wave_building_with_strength_and_text():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tid = quiet_baseline(tracker)
    base = 20 * 60
    trades = []
    for minute, (buy_qty, step) in enumerate(((2.0, 5), (4.0, 10), (8.0, 20))):
        for k in range(4):
            trades.append(trade(base + minute * 60 + k * 10, 75000 + step * (minute + 1) + k, buy_qty / 4, True, tid := tid + 1))
        trades.append(trade(base + minute * 60 + 50, 75000 + step * (minute + 1), 0.2, False, tid := tid + 1))
    _feed(tracker, trades)
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
    _feed(tracker, trades)
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
    _feed(tracker, trades)
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
    _feed(tracker, [trade(0, 75000, 1.0, True, 1), trade(1, 75010, 0.5, False, 2)])
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
    _feed(tracker, [_raw(0, 2.0, None, 1)])
    state = tracker.snapshot(T0 + timedelta(seconds=5))
    one = state["windows"]["1m"]
    assert one["delta"] == 0 and one["buy_share"] is None
    assert one["volume"] == pytest.approx(2.0) and one["unknown_volume"] == pytest.approx(2.0) and one["unknown_trades"] == 1
    assert tracker.day_cvd == 0 and state["day"]["unknown_volume"] == pytest.approx(2.0) and tracker.unknown_trades == 1
    assert state["wave"]["direction"] == "keine"


def test_buy_share_denominator_is_known_volume_only():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(tracker, [_raw(0, 1.0, False, 1), _raw(1, 1.0, True, 2), _raw(2, 2.0, None, 3), _raw(3, 4.0, "false", 4)])
    one = tracker.snapshot(T0 + timedelta(seconds=10))["windows"]["1m"]
    assert one["buy_share"] == pytest.approx(0.5)  # 1 of 2 known, the 6 unknown are not in the denominator
    assert one["volume"] == pytest.approx(8.0) and one["delta"] == 0 and one["unknown_volume"] == pytest.approx(6.0)


def test_levels_keep_unknown_out_of_bid_ask_and_delta():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(tracker, [_raw(0, 1.0, False, 1, 75000), _raw(1, 3.0, None, 2, 75000)])
    state = tracker.snapshot(T0 + timedelta(seconds=10), [{"name": "L", "price": 75000.0}])
    row = state["levels"][0]
    assert (row["bid"], row["ask"], row["unknown"], row["delta"]) == (0.0, 1.0, 3.0, 1.0)
    assert state["schema"] == "orderflow-lage/3"  # 2 from Paket B, 3 from Paket A


# Paket A (#372): point-in-time. A snapshot at t sees only trades with event time and availability <= t.
def _stream(n: int = 40) -> list[Trade]:
    """One trade every 30 s for 20 minutes, alternating sides, rising price, ids 1..n."""
    return [trade(i * 30, 75000 + i, 0.1 + (i % 3) * 0.05, i % 2 == 0, i + 1) for i in range(n)]


def test_future_trade_does_not_change_an_earlier_snapshot():
    base = _stream(20)
    clean = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(clean, base)
    at = T0 + timedelta(seconds=19 * 30 + 5)
    expected = clean.snapshot(at)
    leaked = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(leaked, base + [trade(19 * 30 + 35, 76000, 2.0, True, 99)])  # 30 s after the snapshot moment
    state = leaked.snapshot(at)
    assert state["snapshot_hash"] == expected["snapshot_hash"]
    assert state["windows"] == expected["windows"] and state["price"] == expected["price"] and state["day"] == expected["day"]
    assert state["future_trades"] == 1 and state["stale"] is False and state["last_trade_at"] == expected["last_trade_at"]


def test_codex_reproduction_future_trade_is_not_counted():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(tracker, [trade(30, 75000, 2.0, True, 1)])
    state = tracker.snapshot(T0)
    assert state["windows"]["1m"]["delta"] == 0 and state["price"] is None and state["stale"] is True
    assert state["future_trades"] == 1


def test_trade_is_invisible_before_it_was_available():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([trade(0, 75000, 1.0, True, 1)], available_at=T0 + timedelta(seconds=20))
    assert tracker.snapshot(T0 + timedelta(seconds=10))["windows"]["1m"]["trades"] == 0
    assert tracker.snapshot(T0 + timedelta(seconds=25))["windows"]["1m"]["trades"] == 1


def test_late_trade_is_counted_not_inserted_back_in_time():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(tracker, [trade(60, 75000, 1.0, True, 2)])
    _feed(tracker, [trade(30, 75000, 5.0, True, 3)])
    state = tracker.snapshot(T0 + timedelta(seconds=90))
    assert state["late_dropped"] == 1 and state["windows"]["5m"]["volume"] == pytest.approx(1.0)


def test_replay_in_chunks_equals_all_at_once_at_every_step():
    stream = _stream()
    whole = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(whole, stream)
    chunked = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    fed = 0
    for step in range(1, 21):
        now = T0 + timedelta(seconds=step * 60)
        upto = [t for t in stream if t.event_time <= now]
        chunked.ingest(upto[fed:], available_at=now)
        fed = len(upto)
        assert chunked.snapshot(now)["snapshot_hash"] == whole.snapshot(now)["snapshot_hash"], step


def test_snapshot_time_cannot_go_backwards():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.snapshot(T0 + timedelta(seconds=60))
    with pytest.raises(ValueError):
        tracker.snapshot(T0)


def test_perp_running_bucket_never_counts_and_a_store_from_after_now_is_not_seen():
    now = T0 + timedelta(minutes=10)
    t = int(now.timestamp())
    rows = [[t - 600, 75000.0, 1.0, 2.0], [t - 120, 75000.0, 0.0, 1.0], [t + 300, 75000.0, 0.0, 9.0]]
    live = ls.LiveOrderflowTracker(SYMBOL, 5.0)._perp({"days": {"d": rows}, "bucket_seconds": 300, "updated_at": now.isoformat()}, now)
    assert live["delta_15m"] == pytest.approx(1.0) and live["closed_buckets_only"] is True   # running bucket t-120 left out
    later = ls.LiveOrderflowTracker(SYMBOL, 5.0)._perp(
        {"days": {"d": rows}, "bucket_seconds": 300, "updated_at": (now + timedelta(hours=1)).isoformat()}, now)
    assert later["status"] == "keine Daten in den letzten 15 Minuten" and later["buckets_unknown"] == 1


# Codex #376: the consumer (Orderflow-Schatten) must not read unknown flow as neutral flow.
def test_pure_unknown_flow_is_unbekannt_in_the_shadow_not_neutral():
    from src.dashboard import orderflow_shadow as shadow

    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(tracker, [_raw(0, 5.0, None, 1)])
    view = shadow.lage_view(tracker.snapshot(T0))
    assert view["known_share"] == 0.0
    assert shadow.gate("LONG", view) == shadow.UNBEKANNT and shadow.gate("SHORT", view) == shadow.UNBEKANNT
    assert shadow.should_exit("LONG", view) is None


def test_mostly_unknown_flow_is_unbekannt_and_mostly_known_is_judged():
    from src.dashboard import orderflow_shadow as shadow

    mostly = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(mostly, [_raw(0, 1.0, False, 1), _raw(1, 9.0, None, 2)])
    view = shadow.lage_view(mostly.snapshot(T0 + timedelta(seconds=2)))
    assert view["known_share"] == pytest.approx(0.1) and shadow.gate("LONG", view) == shadow.UNBEKANNT
    known = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(known, [_raw(0, 99.0, False, 1), _raw(1, 1.0, None, 2)])
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


# Codex #377 negative tests: availability order, day values after prune, UTC day change, perp store time.
def test_non_monotone_availability_keeps_windows_and_day_values_consistent():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([_raw(-20, 2.0, False, 1)], available_at=T0 + timedelta(seconds=10))
    tracker.ingest([_raw(-10, 3.0, False, 2)], available_at=T0 - timedelta(seconds=5))
    early = tracker.snapshot(T0)
    # visibility is a prefix: trade 2 is not visible before trade 1, so neither window nor day sees 5 (or 3 of 5)
    assert early["windows"]["5m"]["delta"] == 0 and early["day"]["cvd"] is None and early["future_trades"] == 2
    later = tracker.snapshot(T0 + timedelta(seconds=10))
    assert later["windows"]["5m"]["delta"] == pytest.approx(5.0) and later["day"]["cvd"] == pytest.approx(5.0)


def test_day_values_survive_the_prune_of_their_trades():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([_raw(0, 2.0, False, 1, 75010.0)], available_at=T0)
    assert tracker.snapshot(T0)["day"]["cvd"] == pytest.approx(2.0)
    later = tracker.snapshot(T0 + timedelta(minutes=31))              # the trade is pruned, same UTC day
    assert later["day"]["cvd"] == pytest.approx(2.0) and later["day"]["high"] == 75010.0
    assert later["day"]["status"] == "OK" and later["stale"] is True


def test_day_values_reset_on_the_utc_day_change_and_are_unknown_without_trades():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    assert tracker.snapshot(T0)["day"] == {"cvd": None, "high": None, "low": None, "unknown_volume": None,
                                           "source": "seit Start der Runtime", "status": "UNKNOWN"}  # restart: unknown
    midnight = T0.replace(hour=23, minute=59, second=50)
    tracker.ingest([Trade(SYMBOL, 75000.0, 1.0, midnight, 1, buyer_is_maker=False)], available_at=midnight)
    assert tracker.snapshot(midnight)["day"]["cvd"] == pytest.approx(1.0)
    next_day = tracker.snapshot(midnight + timedelta(seconds=20))     # no trade of the new day yet
    assert next_day["day"]["cvd"] is None and next_day["day"]["status"] == "UNKNOWN"
    tracker.ingest([Trade(SYMBOL, 75000.0, 0.5, midnight + timedelta(seconds=25), 2, buyer_is_maker=True)],
                   available_at=midnight + timedelta(seconds=25))
    assert tracker.snapshot(midnight + timedelta(seconds=30))["day"]["cvd"] == pytest.approx(-0.5)
    unknown_day = {**next_day, "stale": False, "price": 75000.0}
    assert "Tages-CVD" not in ls.describe(unknown_day)             # an unknown day value is not written as 0


def test_naive_available_at_is_refused():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    with pytest.raises(ValueError):
        tracker.ingest([_raw(0, 1.0, False, 1)], available_at=T0.replace(tzinfo=None))


def test_perp_store_without_updated_at_is_not_evidence():
    now = T0 + timedelta(minutes=10)
    t = int(now.timestamp())
    rows = [[t - 600, 75000.0, 1.0, 2.0], [t - 120, 75000.0, 0.0, 1.0]]
    out = ls.LiveOrderflowTracker(SYMBOL, 5.0)._perp({"days": {"d": rows}, "bucket_seconds": 300}, now)
    assert out["status"] == "keine Daten in den letzten 15 Minuten" and out["store_time_known"] is False


# Mission 07 (Codex #377): a perp bucket of 11:50 that is first written at 13:00 is no evidence at 12:00.
def test_perp_backfill_after_the_decision_does_not_change_the_snapshot_at_the_decision():
    noon = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    t = int(noon.timestamp())
    early = [[t - 600, 75000.0, 1.0, 2.0]]
    backfill = early + [[t - 300, 75000.0, 0.0, 50.0]]          # the 11:55 bucket, written only at 13:00
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    at_noon = tracker._perp({"days": {"d": early}, "bucket_seconds": 300, "updated_at": noon.isoformat()}, noon)
    assert at_noon["delta_15m"] == pytest.approx(1.0)
    # Replay of the same decision with the store as it looks at 13:00: the backfilled bucket stays out.
    replay = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    replay._perp({"days": {"d": early}, "bucket_seconds": 300, "updated_at": noon.isoformat()}, noon)
    again = replay._perp({"days": {"d": backfill}, "bucket_seconds": 300,
                          "updated_at": (noon + timedelta(hours=1)).isoformat()}, noon)
    assert again["delta_15m"] == pytest.approx(1.0) and again["buckets_unknown"] == 1
    # A revision of a known bucket after the decision: the decision keeps the old value.
    revised = [[t - 600, 75000.0, 1.0, 40.0]]
    kept = replay._perp({"days": {"d": revised}, "bucket_seconds": 300,
                         "updated_at": (noon + timedelta(hours=1)).isoformat()}, noon)
    assert kept["delta_15m"] == pytest.approx(1.0) and kept["buckets_revised_later"] == 1
    # After a restart the log is empty: what was before is seen from the first look on, never earlier.
    fresh = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    late = fresh._perp({"days": {"d": backfill}, "bucket_seconds": 300,
                        "updated_at": (noon + timedelta(hours=1)).isoformat()}, noon)
    assert late["status"] == "keine Daten in den letzten 15 Minuten"


def test_trades_without_available_at_are_unknown_and_never_evidence():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    assert tracker.ingest([_raw(-30, 2.0, False, 1), _raw(-20, 1.0, True, 2)]) == 0
    state = tracker.snapshot(T0)
    assert state["unavailable_dropped"] == 2 and state["windows"]["5m"]["trades"] == 0 and state["price"] is None
    # The same trades with a known availability are taken (ids were not advanced by the refused batch).
    assert _feed(tracker, [_raw(-30, 2.0, False, 1), _raw(-20, 1.0, True, 2)]) == 2
    later = tracker.snapshot(T0 + timedelta(seconds=1))
    assert later["windows"]["5m"]["trades"] == 2 and later["day"]["status"] == "UNVOLLSTÄNDIG"
    assert "unavailable_dropped" not in json.dumps({k: v for k, v in later.items() if k == "snapshot_hash"})


def test_head_of_line_delay_of_the_prefix_rule_is_reported():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker.ingest([_raw(-20, 2.0, False, 1)], available_at=T0 + timedelta(seconds=10))
    tracker.ingest([_raw(-10, 3.0, False, 2)], available_at=T0 - timedelta(seconds=5))   # waits 15 s for trade 1
    tracker.ingest([_raw(30, 1.0, False, 3)], available_at=T0 + timedelta(seconds=30))   # no wait
    state = tracker.snapshot(T0 + timedelta(seconds=40))
    assert state["held_back"] == {"trades": 1, "max_seconds": 15.0}
    live = ls.LiveOrderflowTracker(SYMBOL, 5.0)                       # live: one read time per batch, never held back
    live.ingest([_raw(0, 1.0, False, 1), _raw(1, 1.0, True, 2)], available_at=T0 + timedelta(seconds=2))
    assert live.snapshot(T0 + timedelta(seconds=3))["held_back"] == {"trades": 0, "max_seconds": 0.0}


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
    assert shadow.gate("LONG", no_windows) == shadow.UNBEKANNT
    assert shadow.side_unknown({"known_share": 0.9}) and not shadow.side_unknown({"known_share": 0.95})  # pre-07 views
