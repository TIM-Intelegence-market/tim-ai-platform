from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from src.models.market_data import Trade
from src.orderflow import live_state as ls
from tests._side_evidence import ABSENT, win

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
    # The store from after now is not seen at now, so neither are its rows nor its bucket width: fail closed.
    assert later["status"] == "Bucket-Größe unbekannt" and later["bucket_seconds_status"] == "NOT_AVAILABLE"
    assert "delta_15m" not in later


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

    full = win(100.0, 0.0)
    at = {"1m": win(100.0, 5.0), "5m": full, "15m": full}
    assert shadow.known_share(lage(at)) == 0.95 and shadow.gate("LONG", shadow.lage_view(lage(at))) == shadow.BESTAETIGT
    below = {"1m": win(10000.0, 501.0), "5m": full, "15m": full}
    assert shadow.gate("LONG", shadow.lage_view(lage(below))) == shadow.UNBEKANNT
    mixed = {"1m": win(10.0, 5.0), "5m": win(1000.0, 5.0),
             "15m": win(0.0, 0.0)}                                                 # one bad window is enough, an empty one is skipped
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
    assert out["status"] == "Bucket-Größe unbekannt" and out["store_time_known"] is False
    assert out["bucket_seconds_status"] == "NOT_AVAILABLE" and "delta_15m" not in out


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
    assert again["delta_15m"] == pytest.approx(1.0)
    assert {k: v for k, v in again.items() if k != "updated_at"} == {k: v for k, v in at_noon.items() if k != "updated_at"}
    # A revision of a known bucket after the decision: the decision keeps the old value.
    revised = [[t - 600, 75000.0, 1.0, 40.0]]
    kept = replay._perp({"days": {"d": revised}, "bucket_seconds": 300,
                         "updated_at": (noon + timedelta(hours=1)).isoformat()}, noon)
    assert kept["delta_15m"] == pytest.approx(1.0) and kept["buckets_revised"] == 0   # nothing after noon leaks in
    # After a restart the log is empty: what was before is seen from the first look on, never earlier.
    fresh = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    late = fresh._perp({"days": {"d": backfill}, "bucket_seconds": 300,
                        "updated_at": (noon + timedelta(hours=1)).isoformat()}, noon)
    assert late["status"] == "Bucket-Größe unbekannt" and late["bucket_seconds_status"] == "NOT_AVAILABLE"


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
                                 "windows": {name: win(volume, unknown) for name in ("1m", "5m", "15m")}})

    assert shadow.gate("LONG", view(100000.0, 5004.0)) == shadow.UNBEKANNT            # 0.94996
    assert shadow.gate("LONG", view(100000.0, 5000.0)) == shadow.BESTAETIGT           # exactly 0.95
    assert shadow.gate("LONG", view(100000.0, 4999.0)) == shadow.BESTAETIGT           # above
    assert view(100000.0, 5004.0)["known_share"] == pytest.approx(0.94996)            # raw, for display


@pytest.mark.parametrize("volume, unknown", [(float("nan"), 0.0), (float("inf"), 0.0), (-1.0, 0.0), (10.0, -1.0),
                                             (10.0, 11.0), ("10", 0.0), (True, 0.0), (10.0, float("nan"))])
def test_invalid_volumes_are_unknown_downstream(volume, unknown):
    from src.dashboard import orderflow_shadow as shadow

    v = shadow.lage_view({"price": 100.0, "wave": {"direction": "auf", "strength": 3},
                          "windows": {"1m": win(volume, unknown)}})
    assert v["side_ok"] is False and v["side_status"] == "INVALID"
    assert shadow.gate("LONG", v) == shadow.UNBEKANNT and shadow.should_exit("SHORT", v) is None


def test_empty_volume_is_no_evidence_and_old_views_still_work():
    from src.dashboard import orderflow_shadow as shadow

    # Codex Mission 07: volume 0 (or none) is no evidence, so even a forced wave "auf" is UNBEKANNT, never BESTÄTIGT.
    empty = shadow.lage_view({"price": 100.0, "wave": {"direction": "auf", "strength": 2}, "windows": {name: win(0.0, 0.0) for name in ("1m", "5m", "15m")}})
    assert empty["side_ok"] is False and empty["side_status"] == "EMPTY" and shadow.gate("LONG", empty) == shadow.UNBEKANNT
    no_windows = shadow.lage_view({"price": 100.0, "wave": {"direction": "auf", "strength": 2}})
    assert shadow.gate("LONG", no_windows) == shadow.UNBEKANNT and no_windows["side_status"] == "MISSING"
    assert shadow.side_unknown({"known_share": 0.9}) and not shadow.side_unknown({"known_share": 0.95})  # pre-07 views


_WAVE = {"price": 100.0, "wave": {"direction": "auf", "strength": 3}}
_FULL = win(100.0, 0.0)


def _without(name):
    return win(**{"volume": 100.0, "unknown_volume": 0.0, name: ABSENT})


@pytest.mark.parametrize("window, status", [
    (_without("unknown_volume"), "MISSING"),            # Codex Mission 07-FINAL: absent is not a proven 0
    (_without("volume"), "MISSING"),
    (win(), "MISSING"),                                 # a window with neither field
    (win(100.0, None), "MISSING"),                       # null is no number either
    (win(None, 0.0), "MISSING"),
    (win(100.0, "0"), "INVALID"),
    (win(100.0, False), "INVALID"),                     # False is not 0
    (win("x"), "INVALID"),                              # invalid wins over missing
])
def test_missing_null_and_invalid_fields_are_never_a_known_side(window, status):
    from src.dashboard import orderflow_shadow as shadow

    for bad in ("1m", "5m", "15m"):
        windows = {name: window if name == bad else dict(_FULL) for name in ("1m", "5m", "15m")}
        v = shadow.lage_view({**_WAVE, "windows": windows})
        assert (v["side_ok"], v["side_status"]) == (False, status)
        for direction in ("LONG", "SHORT"):
            assert shadow.gate(direction, v) == shadow.UNBEKANNT and shadow.should_exit(direction, v) is None


def test_explicit_zero_is_a_value_and_the_only_way_to_a_known_side():
    from src.dashboard import orderflow_shadow as shadow

    for zero in (0, 0.0):
        v = shadow.lage_view({**_WAVE, "windows": {name: win(100.0, zero) for name in ("1m", "5m", "15m")}})
        assert (v["side_ok"], v["side_status"], v["known_share"]) == (True, "OK", 1.0)
        assert shadow.gate("LONG", v) == shadow.BESTAETIGT and shadow.gate("SHORT", v) == shadow.GEGEN
    for windows, status in ((None, "MISSING"), ({}, "MISSING"), ([], "INVALID"), ("1m", "INVALID"),
                            ({"1m": None, "5m": dict(_FULL), "15m": dict(_FULL)}, "INVALID")):
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


@pytest.mark.parametrize("present", [(), ("1m",), ("5m",), ("15m",), ("1m", "5m"), ("1m", "15m"), ("5m", "15m")])
def test_a_window_the_gate_model_needs_but_the_lage_lacks_is_missing_evidence(present):
    """F4: the shadow gate reads 1m, 5m and 15m; a Lage without one of them is never judged."""
    from src.dashboard import orderflow_shadow as shadow

    v = shadow.lage_view({**_WAVE, "windows": {name: dict(_FULL) for name in present}})
    assert (v["side_ok"], v["side_status"]) == (False, "MISSING")
    assert shadow.gate("LONG", v) == shadow.UNBEKANNT and shadow.should_exit("SHORT", v) is None


def test_required_windows_per_signal_model():
    from src.dashboard import orderflow_shadow as shadow

    assert shadow.REQUIRED_WINDOWS == {"welle": ("1m", "5m"), "level": ("15m",), "of-schatten": ("1m", "5m", "15m")}
    assert set(shadow.REQUIRED_WINDOWS["of-schatten"]) == set(ls.WINDOWS)       # the producer writes exactly these
    lage = {**_WAVE, "windows": {"1m": dict(_FULL), "5m": dict(_FULL)}}
    assert shadow.known_side(lage, "welle")["status"] == "OK"
    assert shadow.known_side(lage, "level")["status"] == "MISSING" and shadow.known_side(lage)["status"] == "MISSING"
    extra = {**_WAVE, "windows": {"15m": dict(_FULL), "1h": win(5.0)}}  # a present window is always checked
    assert shadow.known_side(extra, "level")["status"] == "MISSING"
    with pytest.raises(KeyError):
        shadow.known_side(lage, "unbekanntes-modell")


def _perp_store(now, **bucket):
    return {"symbol": "BTCUSDT", "updated_at": now.isoformat(), **bucket,
            "days": {"2026-11-08": [[now.timestamp() - 600, 74950.0, 3.0, 1.0], [now.timestamp() - 900, 74950.0, 1.0, 5.0]]}}


@pytest.mark.parametrize("bucket, status", [
    ({}, "MISSING"), ({"bucket_seconds": None}, "MISSING"),
    ({"bucket_seconds": 0}, "INVALID"), ({"bucket_seconds": -300}, "INVALID"), ({"bucket_seconds": "300"}, "INVALID"),
    ({"bucket_seconds": True}, "INVALID"), ({"bucket_seconds": float("nan")}, "INVALID"),
    ({"bucket_seconds": float("inf")}, "INVALID"), ({"bucket_seconds": 299.5}, "INVALID"),
])
def test_perp_without_a_usable_bucket_size_is_unknown_never_assumed(bucket, status):
    """F1 (#372 Mission 07-FINAL): the 300 s default decided which buckets are closed; now there is no default."""
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(tracker, [trade(0, 75000, 1.0, True, 1)])
    now = T0 + timedelta(seconds=1)
    state = tracker.snapshot(now, perp_store=_perp_store(now, **bucket))
    perp = state["perp"]
    assert perp["bucket_seconds"] is None and perp["bucket_seconds_status"] == status
    assert "delta_5m" not in perp and "delta_15m" not in perp and "Perp-Delta" not in state["text"]
    assert json.dumps(state)


@pytest.mark.parametrize("seconds", [60, 300, 300.0, 900])
def test_perp_uses_the_bucket_size_the_store_states(seconds):
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(tracker, [trade(0, 75000, 1.0, True, 1)])
    now = T0 + timedelta(seconds=1)
    perp = tracker.snapshot(now, perp_store=_perp_store(now, bucket_seconds=seconds))["perp"]
    assert perp["bucket_seconds"] == int(seconds) and type(perp["bucket_seconds"]) is int and "bucket_seconds_status" not in perp


def _without_store_time(perp):
    return {k: v for k, v in perp.items() if k != "updated_at"}


# Codex #377 (27.11.): a 300 s perp bucket still open at 12:00 must not become closed in the identical 12:00 snapshot
# because the store revision of 13:00 states a width of 60 s. The width is evidence of its own revision.
def test_perp_bucket_width_from_a_later_revision_is_not_used_at_the_snapshot():
    noon = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    t = int(noon.timestamp())
    rows = [[t - 900, 75000.0, 1.0, 2.0], [t - 240, 75000.0, 0.0, 5.0]]   # 11:45 closed, 11:56 open until 12:01 at 300 s
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    first = tracker._perp({"days": {"d": rows}, "bucket_seconds": 300, "updated_at": noon.isoformat()}, noon)
    assert first["bucket_seconds"] == 300 and first["delta_5m"] == pytest.approx(0.0)
    assert first["delta_15m"] == pytest.approx(1.0)
    later = noon + timedelta(hours=1)
    again = tracker._perp({"days": {"d": rows}, "bucket_seconds": 60, "updated_at": later.isoformat()}, noon)
    assert again["bucket_seconds"] == 300                      # the 13:00 width is not known at 12:00
    assert again["delta_5m"] == pytest.approx(0.0) and again["delta_15m"] == pytest.approx(1.0)
    assert _without_store_time(again) == _without_store_time(first)   # only the echoed store time differs
    # From 13:00 on the 60 s revision is the one seen (the old rows are then outside the 15 minutes).
    assert tracker._perp_history.width_at(later.timestamp()) == (60, "OK")
    assert tracker._perp_history.width_at(noon.timestamp()) == (300, "OK")


def test_perp_bucket_width_only_from_a_later_revision_fails_closed():
    noon = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    t = int(noon.timestamp())
    rows = [[t - 900, 75000.0, 1.0, 2.0], [t - 240, 75000.0, 0.0, 5.0]]
    out = ls.LiveOrderflowTracker(SYMBOL, 5.0)._perp(
        {"days": {"d": rows}, "bucket_seconds": 60, "updated_at": (noon + timedelta(hours=1)).isoformat()}, noon)
    assert out["status"] == "Bucket-Größe unbekannt" and out["bucket_seconds"] is None
    assert out["bucket_seconds_status"] == "NOT_AVAILABLE" and "delta_5m" not in out


@pytest.mark.parametrize("bad", [{}, {"bucket_seconds": None}, {"bucket_seconds": "60"}, {"bucket_seconds": 0}])
def test_perp_later_revision_with_missing_width_does_not_change_the_earlier_snapshot(bad):
    noon = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    t = int(noon.timestamp())
    rows = [[t - 900, 75000.0, 1.0, 2.0], [t - 240, 75000.0, 0.0, 5.0]]
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    first = tracker._perp({"days": {"d": rows}, "bucket_seconds": 300, "updated_at": noon.isoformat()}, noon)
    later = noon + timedelta(hours=1)
    again = tracker._perp({"days": {"d": rows}, **bad, "updated_at": later.isoformat()}, noon)
    assert _without_store_time(again) == _without_store_time(first)   # only the echoed store time differs
    # At 13:00 the newest seen revision has no usable width: fail closed, the 300 s of 12:00 is not carried over.
    at_one = tracker._perp({"days": {"d": rows}, **bad, "updated_at": later.isoformat()}, later)
    assert at_one["status"] == "Bucket-Größe unbekannt" and at_one["bucket_seconds"] is None
    assert at_one["bucket_seconds_status"] in {"MISSING", "INVALID"}


def test_snapshot_replay_with_the_later_store_keeps_the_noon_perp_block():
    noon = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    t = int(noon.timestamp())
    rows = [[t - 900, 75000.0, 1.0, 2.0], [t - 240, 75000.0, 0.0, 5.0]]
    store = {"symbol": "BTCUSDT", "days": {"d": rows}, "bucket_seconds": 300, "updated_at": noon.isoformat()}
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _feed(tracker, [trade(0, 75000, 1.0, True, 1)])
    noon_state = tracker.snapshot(noon, perp_store=store)
    late_store = {**store, "bucket_seconds": 60, "updated_at": (noon + timedelta(hours=1)).isoformat()}
    replay = tracker.snapshot(noon, perp_store=late_store)
    assert replay["perp"]["bucket_seconds"] == 300
    assert replay["perp"]["delta_5m"] == noon_state["perp"]["delta_5m"] == pytest.approx(0.0)


# Codex #377 Gegenproben (27.11., COORD-376-86dd94f-377-e51e4f25): the width is evidence of the revision a bucket was
# first seen in. A late-noted revision is kept in its place; a width change never closes an unchanged open bucket.
NOON = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
N = int(NOON.timestamp())
OPEN_300 = [N - 240, 75000.0, 0.0, 5.0]          # 11:56, open until 12:01 at 300 s, closed at 60 s
CLOSED_300 = [N - 900, 75000.0, 1.0, 2.0]        # 11:45, closed either way


def _store(rows, width, at):
    store = {"symbol": "BTCUSDT", "days": {"d": [list(r) for r in rows]}, "updated_at": at.isoformat()}
    if width is not ABSENT_WIDTH:
        store["bucket_seconds"] = width
    return store


ABSENT_WIDTH = object()


def test_width_change_300_to_60_at_120015_does_not_close_the_unchanged_open_bucket():
    """Round 2: a start stated once under 300 s and once under 60 s is two different buckets; which one the row means
    cannot be decided, so the windows it could fall into are UNKNOWN, never counted under the shorter width."""
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    first = tracker._perp(_store([CLOSED_300, OPEN_300], 300, NOON), NOON)
    assert first["delta_5m"] == pytest.approx(0.0) and first["delta_15m"] == pytest.approx(1.0)
    switch = NOON + timedelta(seconds=15)
    after = tracker._perp(_store([CLOSED_300, OPEN_300], 60, switch), switch)
    assert after["bucket_seconds"] == 60 and after["buckets_ambiguous"] == 2
    assert after["delta_5m"] is None and after["delta_15m"] is None and after["volume_15m"] is None
    assert after["window_status"] == {"5m": "UNKNOWN", "15m": "UNKNOWN"}
    # Not at 12:01 either: the bucket end is never decided by one of the two widths.
    one = NOON + timedelta(seconds=61)
    later = tracker._perp(_store([CLOSED_300, OPEN_300], 60, switch), one)
    assert later["delta_5m"] is None and later["delta_15m"] is None
    # Once both starts are out of reach (start < t - 15 min - 300 s), the windows are known again.
    clear = NOON + timedelta(minutes=17)
    fresh_row = [int(clear.timestamp()) - 120, 75000.0, 1.0, 4.0]       # a 60 s bucket, closed
    out = tracker._perp(_store([CLOSED_300, OPEN_300, fresh_row], 60, clear), clear)
    assert out["window_status"] == {"5m": "OK", "15m": "OK"}
    assert out["delta_5m"] == pytest.approx(3.0) and out["delta_15m"] == pytest.approx(3.0)


def test_a_new_bucket_in_the_60s_revision_is_judged_by_60s():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker._perp(_store([CLOSED_300], 300, NOON), NOON)
    switch = NOON + timedelta(seconds=15)
    new = [N - 60, 75000.0, 0.0, 3.0]            # 11:59, a 60 s bucket first written at 12:00:15: closed at 12:00
    out = tracker._perp(_store([CLOSED_300, new], 60, switch), switch)
    assert out["delta_5m"] == pytest.approx(3.0)                 # 11:45 (now ambiguous) is out of the 5m reach
    assert out["delta_15m"] is None and out["window_status"]["15m"] == "UNKNOWN"


@pytest.mark.parametrize("missing", [ABSENT_WIDTH, None, "300", 0])
def test_120015_revision_without_width_noted_after_1300_is_kept_and_not_filled_with_300(missing):
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker._perp(_store([CLOSED_300, OPEN_300], 300, NOON), NOON)
    one = NOON + timedelta(hours=1)
    tracker._perp(_store([CLOSED_300, OPEN_300], 60, one), one)
    gap = NOON + timedelta(seconds=15)
    seen = NOON + timedelta(seconds=20)          # a replay step at 12:00:20 reads the 12:00:15 store after 13:00
    tracker._perp(_store([CLOSED_300, OPEN_300], missing, gap), seen)
    history = tracker._perp_history
    assert len(history._widths) == 3
    assert history.width_at(seen.timestamp())[0] is None                    # not lost, not 300
    assert history.width_at((NOON + timedelta(seconds=10)).timestamp()) == (300, "OK")
    assert history.width_at(one.timestamp()) == (60, "OK")
    between = tracker._perp(_store([CLOSED_300, OPEN_300], 60, one), NOON + timedelta(minutes=30))
    assert between["status"] == "Bucket-Größe unbekannt" and between["bucket_seconds"] is None   # no 300 carried over
    assert "delta_5m" not in between


# --- Round 2 (27.11., COORD-REF-AB-62de6bd-6a9a8fb-20261127): canonical as-of history ---------------------------------
# Oracle written from the reference text (docs/ORDERFLOW_REFERENZ_AB.md), not from the code: plain loops over every
# revision ever noted, no folding, exact Fractions.

def _width(width):
    return ls.bucket_size({} if width is ABSENT_WIDTH else {"bucket_seconds": width})


def _oracle(revisions, t):
    """revisions: (u, seen, width, rows). Returns (bucket_seconds, delta_5m, delta_15m) or a status string."""
    from fractions import Fraction
    from decimal import Decimal

    visible = [r for r in revisions if r[1] <= t]
    if not visible:
        return "NOT_AVAILABLE"
    top = max(r[0] for r in visible)
    stated = {_width(r[2]) for r in visible if r[0] == top}
    if len(stated) > 1:
        return "INCONSISTENT"
    (current, status), = stated
    if current is None:
        return status
    if current > ls.PERP_MAX_WIDTH:
        return "TOO_WIDE"
    starts = {row[0] for r in visible for row in r[3] if row[0] >= r[1] - ls.PERP_ROW_HORIZON}
    total = {"5m": Fraction(0), "15m": Fraction(0)}
    unknown = set()
    for start in starts:
        having = [r for r in visible if any(row[0] == start for row in r[3]) and start >= r[1] - ls.PERP_ROW_HORIZON]
        widths = {_width(r[2]) for r in having}
        newest = max(r[0] for r in having)
        values = set()
        for r in having:
            if r[0] == newest:
                rows = [row for row in r[3] if row[0] == start]
                values.add((sum(Fraction(Decimal(repr(float(row[2])))) for row in rows),
                            sum(Fraction(Decimal(repr(float(row[3])))) for row in rows)))
        only = next(iter(widths))[0]
        if len(widths) != 1 or only is None or only > ls.PERP_MAX_WIDTH or len(values) != 1 or (None, None) in values:
            reach = min(max([w for w, _s in widths if w is not None] + [current]), ls.PERP_MAX_WIDTH)
            for name, span in (("5m", 300), ("15m", 900)):
                if t - span - reach <= start < t:
                    unknown.add(name)
            continue
        (w, _s), = widths
        if start + w > t:
            continue
        (bid, ask), = values
        for name, span in (("5m", 300), ("15m", 900)):
            if start >= t - span - w:
                total[name] += ask - bid
    return (current, *(None if name in unknown else float(total[name]) for name in ("5m", "15m")))


def _answer(perp):
    if perp.get("bucket_seconds") is None:
        return perp["bucket_seconds_status"]
    if "delta_5m" not in perp:                                   # no data in the last 15 minutes
        return (perp["bucket_seconds"], 0.0, 0.0)
    return (perp["bucket_seconds"], perp["delta_5m"], perp["delta_15m"])


def _note(tracker, revision, now=None):
    u, seen, width, rows = revision
    at = datetime.fromtimestamp(u, timezone.utc)
    return tracker._perp(_store(rows, width, at), datetime.fromtimestamp(seen if now is None else now, timezone.utc))


def _query(tracker, t):
    """The as-of answer at t without noting anything new (a store without updated_at is never noted)."""
    return _answer(tracker._perp({"symbol": "BTCUSDT", "days": {"d": [[0, 0, 0, 0]]}}, datetime.fromtimestamp(t, timezone.utc)))


def _close(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return a[0] == b[0] and all((x is None and y is None) or (x is not None and y is not None and abs(x - y) < 1e-6)
                                for x, y in zip(a[1:], b[1:]))


def _revisions(rng):
    rows = [list(CLOSED_300), list(OPEN_300)]
    out = []
    for _ in range(rng.randint(1, 6)):
        u = N + rng.choice((0, 0, 5, 15, 30, 61, 120, 300, 900, 3600))
        seen = u + rng.choice((0, 0, 0, 10, 600))
        width = rng.choice((300, 300, 300, 60, ABSENT_WIDTH))
        if rng.random() < 0.4:
            rows = [list(r) for r in rows]
            if rng.random() < 0.5:
                rows.append([N - 60 * rng.randint(0, 20), 75000.0, float(rng.randint(0, 4)), float(rng.randint(0, 9))])
            else:
                pick = rng.randrange(len(rows))
                rows[pick] = rows[pick][:3] + [float(rng.randint(0, 9))]
        out.append((u, seen, width, [list(r) for r in rows]))
    return out


PROBES = (0, 10, 15, 20, 29, 60, 61, 200, 300, 900, 1000, 3600, 3610, 4500)


def test_seeded_sweep_as_of_agrees_with_the_oracle_in_every_noting_order():
    rng = random.Random(20261127)
    for _ in range(250):
        revisions = _revisions(rng)
        orders = [list(revisions), list(reversed(revisions))]
        shuffled = list(revisions)
        rng.shuffle(shuffled)
        orders.append(shuffled)
        orders.append(revisions + revisions[: rng.randint(0, len(revisions))])        # duplicates change nothing
        answers = []
        for order in orders:
            tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
            for revision in order:
                _note(tracker, revision)
            answers.append([_query(tracker, N + p) for p in PROBES])
        for p, expected in zip(PROBES, (_oracle(revisions, N + p) for p in PROBES)):
            for answer in answers:
                got = answer[PROBES.index(p)]
                assert _close(got, expected), (revisions, p, got, expected)


def test_hypothesis_as_of_is_order_free_and_agrees_with_the_oracle():
    hypothesis = pytest.importorskip("hypothesis")
    st = hypothesis.strategies
    row = st.tuples(st.integers(0, 20), st.integers(0, 5), st.integers(0, 9))
    revision = st.tuples(st.sampled_from((0, 5, 15, 61, 300, 900, 3600)), st.sampled_from((0, 0, 10, 600)),
                         st.sampled_from((300, 60, 900, 1800, ABSENT_WIDTH)), st.lists(row, max_size=5))

    @hypothesis.settings(max_examples=200, deadline=None, derandomize=True)
    @hypothesis.given(st.lists(revision, min_size=1, max_size=5), st.randoms(use_true_random=False))
    def run(raw, rnd):
        revisions = [(N + u, N + u + lag, width, [[N - 60 * k, 75000.0, float(b), float(a)] for k, b, a in rows])
                     for u, lag, width, rows in raw]
        order = list(revisions)
        rnd.shuffle(order)
        one, two = ls.LiveOrderflowTracker(SYMBOL, 5.0), ls.LiveOrderflowTracker(SYMBOL, 5.0)
        for revision in revisions:
            _note(one, revision)
        for revision in order:
            _note(two, revision)
        for p in PROBES:
            expected = _oracle(revisions, N + p)
            assert _close(_query(one, N + p), expected) and _close(_query(two, N + p), expected)

    run()


def test_noting_a_revision_at_a_later_decision_time_never_backdates_it():
    """seen = max(now, updated_at): a store read at 12:10 is not evidence at 12:05, even if it was written at 12:00."""
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _note(tracker, (N, N, 300, [[N - 300, 75000.0, 1.0, 2.0]]), now=N + 600)
    assert _query(tracker, N + 300) == "NOT_AVAILABLE"
    assert _query(tracker, N + 600) == (300, 0.0, 1.0)


def test_restart_with_the_same_available_revisions_gives_the_same_answers():
    rng = random.Random(4011)
    for _ in range(50):
        revisions = _revisions(rng)
        running = ls.LiveOrderflowTracker(SYMBOL, 5.0)
        for revision in sorted(revisions, key=lambda r: r[1]):
            _note(running, revision)
        restarted = ls.LiveOrderflowTracker(SYMBOL, 5.0)              # empty after a restart, then fed the same set
        for revision in revisions:
            _note(restarted, revision)
        for p in PROBES:
            assert _query(running, N + p) == _query(restarted, N + p)


def test_history_is_bounded_and_folding_changes_no_answer_after_the_floor():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    revisions = []
    for step in range(0, 4 * 3600, 30):                          # four hours of a live store saved every 30 s
        start = N + step - step % 300
        rows = [[start - 300 * k, 75000.0, float(k), float(step % 7)] for k in range(1, 5)]
        revisions.append((N + step, N + step, 300, rows))
    for revision in revisions:
        _note(tracker, revision)
    history = tracker._perp_history
    assert len(history._widths) <= ls.PERP_KEEP // 30 + 2
    assert len(history._buckets) <= (ls.PERP_KEEP + 2 * ls.PERP_ROW_HORIZON) // 300 + 2
    last = revisions[-1][1]
    for offset in (0, 300, 1800, ls.PERP_KEEP - 1):
        t = last - offset
        assert _close(_query(tracker, t), _oracle(revisions, t)), offset
    assert _query(tracker, last - ls.PERP_KEEP - 1) == ls.BUCKET_HISTORY_GONE


def test_codex_round2_a1_reversed_noting_order_keeps_the_noon_answer():
    """Codex #377 (27.11.), A1: 12:00 with 300 s; 13:00 with 60 s where 11:45 ask 2 -> 9 and 11:56 unchanged.
    Both noted at the decision time 12:00, then the 12:00 revision asked again: (0, 1) in either order."""
    noon = (N, N, 300, [list(CLOSED_300), list(OPEN_300)])
    one = (N + 3600, N + 3600, 60, [CLOSED_300[:3] + [9.0], list(OPEN_300)])
    for order in ([noon, one], [one, noon]):
        tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
        for u, seen, width, rows in order:
            tracker._perp(_store(rows, width, datetime.fromtimestamp(u, timezone.utc)), NOON)
        out = tracker._perp(_store(noon[3], 300, NOON), NOON)
        assert (out["delta_5m"], out["delta_15m"]) == (pytest.approx(0.0), pytest.approx(1.0)), order
        assert out["bucket_seconds"] == 300


def test_codex_round2_a2_value_update_under_60s_does_not_move_the_bucket_end():
    """Codex #377 (27.11.), A2: at 12:00:15 a 60 s revision changes only 11:56 ask 5 -> 6. Round 1 gave
    delta_5m=6, delta_15m=7 (11:56 closed by 60 s). The 300 s bucket may not end before 12:01; which bucket the row
    means is ambiguous, so 5m and 15m are UNKNOWN, at 12:00:15 and still at 12:01:01, in either noting order."""
    noon = (N, N, 300, [list(CLOSED_300), list(OPEN_300)])
    update = (N + 15, N + 15, 60, [list(CLOSED_300), OPEN_300[:3] + [6.0]])
    for order in ([noon, update], [update, noon]):
        tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
        for revision in order:
            _note(tracker, revision)
        for t in (N + 15, N + 61):
            out = tracker._perp({"days": {"d": [[0, 0, 0, 0]]}}, datetime.fromtimestamp(t, timezone.utc))
            assert out["delta_5m"] is None and out["delta_15m"] is None, (order, t, out)
            assert out["delta_5m"] != 6.0 and out["window_status"] == {"5m": "UNKNOWN", "15m": "UNKNOWN"}
        assert _query(tracker, N + 10) == (300, 0.0, 1.0)               # before the update: the noon answer


def test_same_write_time_different_values_is_ambiguous_not_first_or_last():
    a = (N, N, 300, [list(CLOSED_300)])
    b = (N, N + 5, 300, [CLOSED_300[:3] + [7.0]])
    for order in ([a, b], [b, a]):
        tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
        for revision in order:
            _note(tracker, revision)
        assert _query(tracker, N + 1) == (300, 0.0, 1.0)              # only a is seen by then
        assert _query(tracker, N + 10) == (300, 0.0, None)            # both: the 11:45 value is not decidable


def test_unusable_rows_and_too_wide_widths_fail_closed():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _note(tracker, (N, N, 300, [list(CLOSED_300), [N - 600, 75000.0, float("nan"), 1.0]]))
    assert _query(tracker, N) == (300, None, None)             # 11:50 could be in both windows: not decidable
    wide = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    _note(wide, (N, N, 1800, [list(CLOSED_300)]))
    assert _query(wide, N) == ls.BUCKET_TOO_WIDE


def test_restart_sees_nothing_before_its_first_look():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker._perp(_store([CLOSED_300, OPEN_300], 300, NOON), NOON)
    fresh = ls.LiveOrderflowTracker(SYMBOL, 5.0)                       # restart at 13:00, store says 60 s
    one = NOON + timedelta(hours=1)
    out = fresh._perp(_store([CLOSED_300, OPEN_300], 60, one), NOON)  # a replay of noon after the restart
    assert out["status"] == "Bucket-Größe unbekannt" and out["bucket_seconds_status"] == "NOT_AVAILABLE"


def test_two_revisions_seen_at_the_same_moment_with_different_widths_are_inconsistent():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker._perp(_store([CLOSED_300, OPEN_300], 300, NOON), NOON)
    tracker._perp(_store([CLOSED_300, OPEN_300], 60, NOON), NOON)
    out = tracker._perp(_store([CLOSED_300, OPEN_300], 300, NOON), NOON)
    assert out["status"] == "Bucket-Größe unbekannt" and out["bucket_seconds_status"] == "INCONSISTENT"


def test_codex_7218699983_case_1_missing_width_at_120015_after_1300_is_unknown_at_120015():
    """Exactly as Codex reproduced it on e51e4f25 (#377 issuecomment-7218699983, case 1)."""
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    first = tracker._perp(_store([CLOSED_300, OPEN_300], 300, NOON), NOON)
    assert (first["delta_5m"], first["delta_15m"]) == (pytest.approx(0.0), pytest.approx(1.0))
    control = tracker._perp(_store([CLOSED_300, OPEN_300], 60, NOON + timedelta(hours=1)), NOON)
    assert control["bucket_seconds"] == 300 and control["delta_5m"] == pytest.approx(0.0)
    decision = NOON + timedelta(seconds=15)
    out = tracker._perp(_store([CLOSED_300, OPEN_300], ABSENT_WIDTH, decision), decision)
    assert out["status"] == "Bucket-Größe unbekannt" and out["bucket_seconds_status"] == "MISSING"
    assert "delta_5m" not in out and "delta_15m" not in out


def test_codex_7218699983_case_2_fresh_tracker_300_then_60_at_120015():
    tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
    tracker._perp(_store([CLOSED_300, OPEN_300], 300, NOON), NOON)
    decision = NOON + timedelta(seconds=15)
    out = tracker._perp(_store([CLOSED_300, OPEN_300], 60, decision), decision)
    # Round 2: never 5 (the open 300 s bucket closed by 60 s); the identity of both starts is ambiguous: UNKNOWN.
    assert out["delta_5m"] is None and out["delta_15m"] is None and out["buckets_ambiguous"] == 2


def test_ab_integration_one_snapshot_exact_side_and_order_free_perp_through_json():
    """A+B together (round 2): the real tracker with available trades (Codex B case) and two perp revisions
    (Codex A1), noted in either order at the decision time. Same snapshot hash, exact side evidence through JSON,
    the shadow says BELOW/UNBEKANNT, the perp block is the noon answer (0, 1)."""
    from src.dashboard import orderflow_shadow as shadow

    noon_store = _store([CLOSED_300, OPEN_300], 300, NOON)
    late_store = _store([CLOSED_300[:3] + [9.0], OPEN_300], 60, NOON + timedelta(hours=1))
    states = []
    for order in ([noon_store, late_store], [late_store, noon_store]):
        tracker = ls.LiveOrderflowTracker(SYMBOL, 5.0)
        for k, (qty, maker) in enumerate(((0.0001332602127840482, False), (0.000007013695409686748, None))):
            at = NOON - timedelta(seconds=20 - k)
            tracker.ingest([Trade(SYMBOL, 75000.0, qty, at, k + 1, buyer_is_maker=maker)], available_at=at)  # type: ignore[arg-type]
        for store in order:
            tracker.snapshot(NOON, perp_store=store)
        states.append(json.loads(json.dumps(tracker.snapshot(NOON, perp_store=noon_store))))
    first, second = states
    assert first["snapshot_hash"] == second["snapshot_hash"] and first == second
    assert first["windows"]["1m"]["side_evidence"] == {"schema": "side-evidence/1", "known": "0.0001332602127840482",
                                                       "unknown": "0.000007013695409686748"}
    view = shadow.lage_view(first)
    assert (view["side_ok"], view["side_status"]) == (False, "BELOW")
    assert shadow.gate("LONG", view) == shadow.UNBEKANNT and shadow.should_exit("SHORT", view) is None
    assert (first["perp"]["bucket_seconds"], first["perp"]["delta_5m"], first["perp"]["delta_15m"]) == (300, 0.0, 1.0)
