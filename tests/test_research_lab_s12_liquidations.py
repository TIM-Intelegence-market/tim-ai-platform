"""Study S12 packages L1-L3: liquidation events, raw store, collector, heatmap states, gate."""
from __future__ import annotations

import asyncio
import gzip
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.liquidation_map.heatmap import build_heatmap, Candle
from src.research_lab.liquidations import collector, events, gate, snapshots, store
from src.research_lab.liquidations.__main__ import main

NS = store.NS_PER_S
T0 = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)

BINANCE_SELL = {"e": "forceOrder", "E": 1762041600123, "o": {
    "s": "BTCUSDT", "S": "SELL", "o": "LIMIT", "f": "IOC", "q": "0.014", "p": "80000.10", "ap": "80010.50",
    "X": "FILLED", "l": "0.014", "z": "0.014", "T": 1762041600100}}
BYBIT_PUSH = {"topic": "allLiquidation.BTCUSDT", "type": "snapshot", "ts": 1762041600300, "data": [
    {"T": 1762041600200, "s": "BTCUSDT", "S": "Buy", "v": "0.5", "p": "79990.0"},
    {"T": 1762041600250, "s": "BTCUSDT", "S": "Sell", "v": "0.2", "p": "81000.0"}]}


def ns(moment: datetime) -> int:
    return int(moment.timestamp() * NS)


# ---------------------------------------------------------------- events

def test_binance_sell_is_a_liquidated_long():
    [event] = events.parse_binance(BINANCE_SELL)
    assert (event.venue, event.side, event.raw_side, event.status) == ("binance", "long", "SELL", "FILLED")
    assert event.price == Decimal("80010.50") and event.quantity == Decimal("0.014")
    assert event.notional == Decimal("80010.50") * Decimal("0.014")
    assert event.time_ms == 1762041600100 and event.counts


def test_binance_buy_is_short_and_combined_wrapper_and_status():
    msg = json.loads(json.dumps(BINANCE_SELL))
    msg["o"]["S"], msg["o"]["X"] = "BUY", "PARTIALLY_FILLED"
    [event] = events.parse_binance({"stream": "btcusdt@forceOrder", "data": msg})
    assert event.side == "short" and not event.counts
    assert events.parse_binance({"result": None, "id": 1}) == []


@pytest.mark.parametrize("change", [{"S": "HOLD"}, {"ap": 80000.0}, {"ap": "nan"}, {"z": "-1"}, {"T": "1"}])
def test_binance_rejects_bad_fields(change):
    msg = json.loads(json.dumps(BINANCE_SELL))
    msg["o"].update(change)
    with pytest.raises(events.EventFormatError):
        events.parse_binance(msg)


def test_bybit_sides_and_control_messages():
    first, second = events.parse_bybit(BYBIT_PUSH)
    assert (first.side, first.raw_side, first.price) == ("long", "Buy", Decimal("79990.0"))
    assert (second.side, second.raw_side) == ("short", "Sell")
    assert events.parse_bybit({"op": "pong", "success": True}) == []
    assert events.parse_bybit({"success": True, "ret_msg": "", "op": "subscribe"}) == []
    with pytest.raises(events.EventFormatError):
        events.parse_bybit({"topic": "publicTrade.BTCUSDT", "data": []})


def test_dedupe_keeps_first_identical_event():
    [a] = events.parse_binance(BINANCE_SELL)
    [b] = events.parse_binance(BINANCE_SELL)
    other = json.loads(json.dumps(BINANCE_SELL))
    other["o"]["z"] = "0.015"
    [c] = events.parse_binance(other)
    assert events.dedupe([a, b, c]) == [a, c]


# ---------------------------------------------------------------- store

def test_append_read_and_payload_hash(tmp_path):
    record = store.make_record("message", "binance", "s1", ns(T0), 5, payload='{"x":1}')
    path = store.append(tmp_path, record)
    store.append(tmp_path, store.make_record("alive", "binance", "s1", ns(T0) + NS, 6))
    assert path == tmp_path / "raw" / "binance" / "2026-11-02.jsonl"
    rows = list(store.read_records(path))
    assert [r["kind"] for r in rows] == ["message", "alive"]
    assert store.check_payload(rows[0]) and store.check_payload(rows[1])
    rows[0]["payload"] = '{"x":2}'
    assert not store.check_payload(rows[0])
    with pytest.raises(ValueError):
        store.make_record("other", "binance", "s1", 0, 0)


def test_cut_off_line_loses_only_itself(tmp_path):
    path = store.append(tmp_path, store.make_record("alive", "binance", "s1", ns(T0), 1))
    with open(path, "ab") as handle:
        handle.write(b'{"kind":"alive","receive_ns":12')  # crash in the middle of a write
    store.append(tmp_path, store.make_record("alive", "binance", "s1", ns(T0) + NS, 2))
    bad: list[int] = []
    rows = list(store.read_records(path, bad))
    assert [r["mono_ns"] for r in rows] == [1, 2] and bad == [2]
    assert store.manifest(tmp_path, "binance", T0.date())["bad_lines"] == [2]


def _proofs(sid, start, seconds, step=60, kind="alive"):
    return [{"kind": kind, "session_id": sid, "receive_ns": ns(start) + s * NS} for s in range(0, seconds + 1, step)]


def test_coverage_needs_consecutive_proofs_of_one_session():
    window = (ns(T0), ns(T0) + 3600 * NS)
    full = _proofs("a", T0 - timedelta(seconds=30), 3700)
    assert store.coverage(store.connected_intervals(full), *window) == pytest.approx(1.0)
    # gap of 10 minutes without proofs is not covered
    gap = [r for r in full if not (ns(T0) + 600 * NS < r["receive_ns"] < ns(T0) + 1200 * NS)]
    assert store.coverage(store.connected_intervals(gap), *window) == pytest.approx(1 - 660 / 3600, abs=0.02)
    # a disconnect ends the session; later records of it do not count
    cut = full[:20] + [{"kind": "disconnect", "session_id": "a", "receive_ns": full[20]["receive_ns"]}] + full[21:]
    assert store.coverage(store.connected_intervals(cut), *window) < 0.35
    # proofs of different sessions do not bridge each other
    mixed = [dict(r, session_id="a" if i % 2 else "b") for i, r in enumerate(full)]
    assert store.coverage(store.connected_intervals(mixed), *window) == 0.0


def test_gaps():
    intervals = [store.Interval(10, 20), store.Interval(15, 30), store.Interval(50, 60)]
    assert store.gaps(intervals, 0, 100) == [(0, 10), (30, 50), (60, 100)]
    assert store.gaps([], 0, 5) == [(0, 5)]


def test_manifest_and_write_once(tmp_path):
    for r in _proofs("a", T0, 86_400 - 60):
        store.append(tmp_path, store.make_record("alive", "binance", "a", r["receive_ns"], 0))
    info = store.manifest(tmp_path, "binance", T0.date())
    assert info["records"] == 1440 and info["bad_payload_hashes"] == 0
    assert info["coverage"] == pytest.approx(1.0, abs=0.002)
    assert sum(g["seconds"] for g in info["gaps"]) <= 120
    target = store.write_manifest(tmp_path, "binance", T0.date())
    target.write_text("{}")
    store.write_manifest(tmp_path, "binance", T0.date())
    assert target.read_text() == "{}"
    assert store.manifest(tmp_path, "bybit", T0.date())["exists"] is False


# ---------------------------------------------------------------- collector

class FakeSocket:
    def __init__(self, messages, error=None, pong=True):
        self.messages, self.error, self.sent, self.pong, self.closed = list(messages), error, [], pong, False

    async def send(self, text):
        self.sent.append(text)

    async def ping(self):
        waiter = asyncio.get_running_loop().create_future()
        if self.pong:
            waiter.set_result(0.001)
        return waiter

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(0)
        if self.messages:
            return self.messages.pop(0)
        if self.error:
            raise self.error
        raise StopAsyncIteration

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_session_records_raw_messages_and_disconnect(tmp_path):
    socket = FakeSocket([json.dumps(BYBIT_PUSH), "not json", json.dumps({"op": "pong"})], error=ConnectionError("lost"))
    recorder = collector.Recorder(tmp_path, "bybit", now_ns=lambda: ns(T0), mono_ns=iter(range(100)).__next__)
    asyncio.run(collector.run_session(collector.VENUES["bybit"], recorder, connect=lambda url: socket))
    rows = list(store.read_records(store.raw_path(tmp_path, "bybit", T0.date())))
    assert [r["kind"] for r in rows] == ["connect", "message", "message", "message", "disconnect"]
    assert rows[2]["payload"] == "not json" and recorder.parse_errors == 1
    assert "ConnectionError: lost" in rows[-1]["note"]
    assert json.loads(socket.sent[0]) == {"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]}


def test_failed_connect_is_recorded_and_not_covered(tmp_path):
    def broken(url):
        raise OSError("dns")
    recorder = collector.Recorder(tmp_path, "binance", now_ns=lambda: ns(T0))
    asyncio.run(collector.run_session(collector.VENUES["binance"], recorder, connect=broken))
    [row] = store.read_records(store.raw_path(tmp_path, "binance", T0.date()))
    assert row["kind"] == "connect_failed" and "dns" in row["note"]
    assert store.connected_intervals([row, dict(row, receive_ns=row["receive_ns"] + NS)]) == []


def test_rejected_bybit_subscription_ends_session(tmp_path):
    socket = FakeSocket([json.dumps({"success": False, "ret_msg": "error:topic", "op": "subscribe"}),
                         json.dumps(BYBIT_PUSH)])
    recorder = collector.Recorder(tmp_path, "bybit", now_ns=lambda: ns(T0))
    asyncio.run(collector.run_session(collector.VENUES["bybit"], recorder, connect=lambda url: socket))
    rows = list(store.read_records(store.raw_path(tmp_path, "bybit", T0.date())))
    assert [r["kind"] for r in rows] == ["connect", "message", "disconnect"]
    assert "SubscriptionRejected" in rows[-1]["note"]


def test_missing_pong_ends_session_without_alive(tmp_path):
    class Hanging(FakeSocket):
        async def __anext__(self):
            while not self.closed:
                await asyncio.sleep(0.01)
            raise StopAsyncIteration
    recorder = collector.Recorder(tmp_path, "binance", now_ns=lambda: ns(T0))
    old = collector.PONG_TIMEOUT_SECONDS
    collector.PONG_TIMEOUT_SECONDS = 0.02
    try:
        asyncio.run(collector.run_session(collector.VENUES["binance"], recorder, connect=lambda u: Hanging([], pong=False),
                                          alive_seconds=0.01))
    finally:
        collector.PONG_TIMEOUT_SECONDS = old
    kinds = [r["kind"] for r in store.read_records(store.raw_path(tmp_path, "binance", T0.date()))]
    assert kinds == ["connect", "disconnect"]


def test_write_failure_does_not_end_the_venue_loop(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def failing(venue, recorder, connect):
        calls["n"] += 1
        if calls["n"] >= 3:
            stop.set()
        raise OSError("disk full")

    stop = asyncio.Event()
    monkeypatch.setattr(collector, "run_session", failing)
    asyncio.run(asyncio.wait_for(collector.run_venue(collector.VENUES["binance"], tmp_path, stop=stop), timeout=10))
    assert calls["n"] == 3


def test_alive_records_while_open(tmp_path):
    class SlowSocket(FakeSocket):
        async def __anext__(self):
            await asyncio.sleep(0.05)
            raise StopAsyncIteration
    recorder = collector.Recorder(tmp_path, "binance", now_ns=lambda: ns(T0))
    asyncio.run(collector.run_session(collector.VENUES["binance"], recorder, connect=lambda u: SlowSocket([]),
                                      alive_seconds=0.01))
    kinds = [r["kind"] for r in store.read_records(store.raw_path(tmp_path, "binance", T0.date()))]
    assert kinds[0] == "connect" and kinds[-1] == "disconnect" and kinds.count("alive") >= 2


def test_venue_endpoints():
    assert collector.VENUES["binance"].url == "wss://fstream.binance.com/market/ws/btcusdt@forceOrder"
    assert collector.VENUES["bybit"].client_ping == {"op": "ping"}


# ---------------------------------------------------------------- snapshots

PERIOD = snapshots.PERIOD_SECONDS


def _raw_answers(t: datetime, periods=500, oi_shift=0, decline_every=7):
    """Synthetic Binance answers: klines up to and including the running candle, OI up to t."""
    t_s = int(t.timestamp())
    first = t_s - (periods - 1) * PERIOD
    klines, oi = [], []
    for k in range(periods):
        open_s = first + k * PERIOD
        mid = 80_000 + 400 * ((k * 37) % 23 - 11) / 11
        klines.append([open_s * 1000, f"{mid:.1f}", f"{mid + 60:.1f}", f"{mid - 60:.1f}", f"{mid + 5:.1f}", "1"])
    for k in range(periods + 1):
        stamp = first + k * PERIOD + oi_shift
        if stamp > t_s + PERIOD:
            break
        value = 90_000 + 15 * k - (40 if k % decline_every == 0 else 0)
        oi.append({"symbol": "BTCUSDT", "sumOpenInterest": f"{value:.3f}", "timestamp": stamp * 1000})
    return oi, klines


def _fetcher(t, **kw):
    oi, klines = _raw_answers(t, **kw)

    def fetch(path, params):
        return oi if "openInterest" in path else klines
    return fetch


def test_window_starts():
    assert snapshots.window_start(datetime(2026, 11, 2, 13, 5, tzinfo=timezone.utc)) == datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    assert snapshots.next_window_start(datetime(2026, 11, 2, 12, tzinfo=timezone.utc)) == datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    assert snapshots.next_window_start(datetime(2026, 11, 2, 18, 0, 1, tzinfo=timezone.utc)) == datetime(2026, 11, 3, tzinfo=timezone.utc)


def test_take_stores_raw_and_recomputes_bit_for_bit(tmp_path):
    path = snapshots.take(tmp_path, T0, fetch=_fetcher(T0), now=lambda: T0 + timedelta(seconds=120))
    record = snapshots.load(path)
    assert path == tmp_path / "snapshots" / "2026-11-02" / "0000.json.gz"
    assert record["valid"], record["reasons"]
    assert snapshots.verify(path) == []
    assert record["tim"]["periods_with_oi"] == record["baseline"]["periods_with_oi"] >= 450
    # no candle at or after t - 1800 + 1 and no OI after t went into the models
    assert record["tim"]["last"] == float(record["klines"][-2][4])
    # the file is never replaced
    assert snapshots.take(tmp_path, T0, fetch=lambda p, q: pytest.fail("fetched again")) == path


def test_verify_detects_changed_raw_answers(tmp_path):
    path = snapshots.take(tmp_path, T0, fetch=_fetcher(T0), now=lambda: T0 + timedelta(seconds=120))
    record = snapshots.load(path)
    record["klines"][10][2] = "99999.0"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(record, handle)
    problems = snapshots.verify(path)
    assert "raw answers changed" in problems and "stored result differs from recomputation" in problems


def test_display_filters_are_off_and_baseline_has_no_oi_information():
    oi_rows, klines = _raw_answers(T0)
    raw = {"t": T0.isoformat(), "fetched_at": T0.isoformat(), "open_interest": oi_rows, "klines": klines}
    result = snapshots.compute(raw)
    tim, base = result["tim"], result["baseline"]
    # same candles, different OI series -> different models; baseline never shrinks (no decline)
    assert snapshots.top_rows(tim, "long") != [] and snapshots.top_rows(base, "long") != []
    candles = [c for c in (Candle(int(k[0]) // 1000, float(k[2]), float(k[3]), float(k[4])) for k in klines)
               if c.time <= int(T0.timestamp()) - PERIOD]
    display = build_heatmap(candles, {int(r["timestamp"]) // 1000: float(r["sumOpenInterest"]) for r in oi_rows
                                      if int(r["timestamp"]) // 1000 <= int(T0.timestamp())}, T0)
    assert display["input_hash"] == tim["input_hash"]
    # the display drops cells under 2 % of the strongest one; the study keeps them
    assert len(tim["cells"]) > len(display["cells"])
    assert any(c["usd"] < 0.02 * tim["max_usd"] for c in tim["cells"])


def test_top_rows_side_filter_and_ties():
    model = {"last": 100.0, "step": 1.0, "cells": [
        {"side": "long", "price": 99.0, "usd": 5.0, "end": None},
        {"side": "long", "price": 99.5, "usd": 9.0, "end": None},   # row + step > last: excluded
        {"side": "long", "price": 90.0, "usd": 5.0, "end": None},
        {"side": "long", "price": 95.0, "usd": 7.0, "end": 123},     # swept: excluded
        {"side": "short", "price": 100.0, "usd": 3.0, "end": None},  # not above last: excluded
        {"side": "short", "price": 101.0, "usd": 3.0, "end": None}]}
    assert snapshots.top_rows(model, "long") == [99.0, 90.0]
    assert snapshots.top_rows(model, "short") == [101.0]


def test_invalid_states():
    oi_rows, klines = _raw_answers(T0, oi_shift=60)
    late = {"t": T0.isoformat(), "fetched_at": (T0 + timedelta(minutes=16)).isoformat(),
            "open_interest": oi_rows, "klines": klines}
    reasons = snapshots.compute(late)["reasons"]
    assert any("after t" in r for r in reasons) and any("not on candle open times" in r for r in reasons)
    short_oi, short_k = _raw_answers(T0, periods=300)
    few = {"t": T0.isoformat(), "fetched_at": T0.isoformat(), "open_interest": short_oi, "klines": short_k}
    assert any("periods_with_oi" in r for r in snapshots.compute(few)["reasons"])
    with pytest.raises(ValueError):
        snapshots.take(Path("/nonexistent"), T0 + timedelta(hours=1), fetch=_fetcher(T0))


# ---------------------------------------------------------------- gate

def _fill_window(root, t, coverage_seconds=6 * 3600, liquidation=True):
    sid = f"s-{t:%d%H}"
    for r in _proofs(sid, t - timedelta(seconds=30), coverage_seconds + 30):
        store.append(root, store.make_record("alive", "binance", sid, r["receive_ns"], 0))
    if liquidation:
        msg = json.loads(json.dumps(BINANCE_SELL))
        msg["o"]["T"] = int((t + timedelta(hours=1)).timestamp() * 1000)
        text = json.dumps(msg)
        for _ in range(2):  # duplicate counts once
            store.append(root, store.make_record("message", "binance", sid, ns(t + timedelta(hours=1, seconds=1)), 0, payload=text))
    snapshots.take(root, t, fetch=_fetcher(t), now=lambda: t + timedelta(seconds=120))


def test_count_window_valid_and_reasons(tmp_path):
    _fill_window(tmp_path, T0)
    count = gate.count_window(tmp_path, T0)
    assert count.valid and count.events == 1 and count.coverage >= 0.99
    t2 = T0 + timedelta(hours=6)
    _fill_window(tmp_path, t2, coverage_seconds=3 * 3600, liquidation=False)
    bad = gate.count_window(tmp_path, t2)
    assert not bad.valid and any(r.startswith("coverage") for r in bad.reasons) and "no counted liquidation" in bad.reasons
    assert "no heatmap state" in gate.count_window(tmp_path, T0 + timedelta(hours=12)).reasons


def test_gate_rule(tmp_path, monkeypatch):
    def fake(root, t):
        k = int((t - T0).total_seconds() // (6 * 3600))
        return gate.WindowCount(t=t.isoformat(), valid=(k % share) != 0)

    monkeypatch.setattr(gate, "count_window", fake)
    for share, expected in ((1_000_000, "continue_56_days"), (2, "extend_84_days"), (1, "stop_not_assessable")):
        result = gate.run(tmp_path, T0, now=T0 + timedelta(days=14))
        assert result["gate"] == expected, (share, result.get("projected_56"))
    share = 2
    assert gate.run(tmp_path, T0, now=T0 + timedelta(days=13))["gate"] == "pending"
    with pytest.raises(ValueError):
        gate.run(tmp_path, T0 + timedelta(hours=6))


def test_cli_verify_gate_and_sides(tmp_path, capsys):
    _fill_window(tmp_path, T0)
    assert main(["--data-dir", str(tmp_path), "verify"]) == 0
    assert "1 states, 0 with problems" in capsys.readouterr().out
    assert main(["--data-dir", str(tmp_path), "gate", "--start", "2026-11-02"]) == 0
    assert json.loads(capsys.readouterr().out)["gate"] == "pending"
    assert main(["--data-dir", str(tmp_path), "manifest", "--day", "2026-11-02"]) == 0
    capsys.readouterr()
    assert main(["--data-dir", str(tmp_path), "sides", "--limit", "5"]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_second_run_on_same_folder_exits(tmp_path):
    from src.research_lab.liquidations.__main__ import _lock
    held = _lock(tmp_path)
    try:
        with pytest.raises(SystemExit):
            _lock(tmp_path)
    finally:
        held.close()
