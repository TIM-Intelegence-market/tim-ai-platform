"""Perp trades and open interest for the chart (Beirat 29.10.2026, F5): gapless, resumable, checked."""

from __future__ import annotations

import asyncio
import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.dashboard import perp_flow
from src.dashboard.app import DashboardState
from src.dashboard.footprint_data import bar_deltas, cvd_lines, footprint_bars, volume_profiles
from src.dashboard.perp_flow import BATCH, PerpFlow, oi_chart, open_interest, zscores

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
YESTERDAY_MS = int(datetime(2026, 10, 30, tzinfo=timezone.utc).timestamp() * 1000)
NOW_MS = int(NOW.timestamp() * 1000)


def make_trades(start_ms: int = YESTERDAY_MS - 600_000, end_ms: int = NOW_MS, every_ms: int = 60_000, first_id: int = 1000):
    """One trade a minute; every third one a seller, every 50th a big buyer order of two trades in the same ms."""
    trades, agg_id, ms = [], first_id, start_ms
    while ms < end_ms:
        price = 80_000.0 + (ms // 60_000) % 40 * 5
        seller = agg_id % 3 == 0
        trades.append({"a": agg_id, "p": str(price), "q": "0.5", "f": agg_id, "l": agg_id, "T": ms, "m": seller})
        agg_id += 1
        if agg_id % 50 == 0:
            for _ in range(2):
                trades.append({"a": agg_id, "p": str(price), "q": "1.0", "f": agg_id, "l": agg_id, "T": ms + 1, "m": False})
                agg_id += 1
        ms += every_ms
    return trades


class FakeBinance:
    def __init__(self, trades, missing=()):
        self.trades = [t for t in trades if t["a"] not in set(missing)]
        self.calls = []

    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        if path == "/fapi/v1/aggTrades" and "startTime" in params:
            start, end = int(params["startTime"]), int(params["endTime"])
            return [t for t in self.trades if start <= t["T"] <= end][:1]
        if path == "/fapi/v1/aggTrades":
            start = int(params["fromId"])
            return [t for t in self.trades if t["a"] >= start][: int(params["limit"])]
        if path == "/fapi/v1/klines":
            start, end = int(params["startTime"]), int(params["endTime"])
            rows = []
            for hour in range(start, end, 3_600_000):
                inside = [t for t in self.trades if hour <= t["T"] < hour + 3_600_000]
                volume = sum(float(t["q"]) for t in inside)
                buy = sum(float(t["q"]) for t in inside if not t["m"])
                rows.append([hour, "0", "0", "0", "0", f"{volume:.3f}", hour + 3_599_999, "0", len(inside), f"{buy:.3f}", "0", "0"])
            return rows
        raise AssertionError(path)


def collect(flow: PerpFlow) -> None:
    while flow.step() == BATCH:
        pass


def test_fresh_start_reads_from_yesterday_midnight_and_fills_the_footprint_store(tmp_path) -> None:
    trades = make_trades()
    flow = PerpFlow(tmp_path, fetch=FakeBinance(trades), clock=lambda: NOW.timestamp())
    collect(flow)
    kept = [t for t in trades if t["T"] >= YESTERDAY_MS]
    store = flow.store()
    assert store["market"] == "perp" and sorted(store["days"]) == ["2026-10-30", "2026-10-31"]
    rows = [r for day in store["days"].values() for r in day]
    assert sum(r[2] + r[3] for r in rows) == pytest.approx(sum(float(t["q"]) for t in kept))
    assert sum(r[3] - r[2] for r in rows) == pytest.approx(sum(float(t["q"]) * (-1 if t["m"] else 1) for t in kept))
    # bid = seller aggressive (buyer is maker), as in MarketRepository.agg_trade_levels
    first = kept[0]
    row = next(r for r in store["days"]["2026-10-30"] if r[0] == first["T"] // 1000 // 300 * 300 and r[1] == float(first["p"]))
    assert (row[2] > 0) == bool(first["m"]) or row[3] > 0
    assert store["complete"] == {"2026-10-30": int(NOW.timestamp())}  # today is still running
    assert flow.health()["gaps"] == 0 and flow.next_id == trades[-1]["a"] + 1
    # Two trades of one taker order in the same ms: one bubble of 2 BTC (about 160,000 $).
    assert all(b[2] == pytest.approx(2.0) and b[3] == 1 for day in store["bubbles"].values() for b in day)
    assert store["bubbles"]["2026-10-30"]
    # The store works with the spot functions unchanged.
    assert [p["day"] for p in volume_profiles(store, NOW)] == ["2026-10-30", "2026-10-31"]
    times = list(range(int(NOW.timestamp()) - 6 * 1800, int(NOW.timestamp()), 1800))
    assert footprint_bars(store, times, 1800)["bars"]


def test_restart_goes_on_from_the_saved_id_without_gap_or_double_count(tmp_path) -> None:
    trades = make_trades()
    early = NOW - timedelta(hours=3)
    fake = FakeBinance([t for t in trades if t["T"] < early.timestamp() * 1000])
    flow = PerpFlow(tmp_path, fetch=fake, clock=lambda: early.timestamp())
    collect(flow)
    flow.save()
    saved_state = (tmp_path / "state.json").read_text()
    # More trades, saved day files, then a crash before state.json: the day file is ahead of the state.
    fake.trades = trades
    flow.clock = lambda: NOW.timestamp()
    collect(flow)
    flow.save()
    (tmp_path / "state.json").write_text(saved_state)

    again = PerpFlow(tmp_path, fetch=FakeBinance(trades), clock=lambda: NOW.timestamp())
    again.load()
    assert again.next_id == json.loads(saved_state)["next_id"]
    collect(again)
    kept = [t for t in trades if t["T"] >= YESTERDAY_MS]
    rows = [r for day in again.store()["days"].values() for r in day]
    assert sum(r[2] + r[3] for r in rows) == pytest.approx(sum(float(t["q"]) for t in kept))
    assert again.health()["gaps"] == 0 and "2026-10-30" in again.complete_days()


def test_a_missing_id_is_counted_and_the_day_is_not_complete(tmp_path) -> None:
    trades = make_trades()
    hole = next(t["a"] for t in trades if t["T"] >= YESTERDAY_MS + 5 * 3_600_000)
    flow = PerpFlow(tmp_path, fetch=FakeBinance(trades, missing=[hole]), clock=lambda: NOW.timestamp())
    collect(flow)
    health = flow.health()
    assert health["gaps"] == 1 and health["last_gap"]["resume_id"] == hole + 1
    assert "2026-10-30" not in flow.complete_days()


def test_a_state_older_than_the_store_starts_fresh(tmp_path) -> None:
    trades = make_trades()
    flow = PerpFlow(tmp_path, fetch=FakeBinance(trades), clock=lambda: NOW.timestamp())
    flow.next_id, flow.segments = 5, [[0, 1000]]
    flow.start_point()
    assert flow.next_id == next(t["a"] for t in trades if t["T"] >= YESTERDAY_MS)
    assert flow.gaps[-1]["reason"].startswith("Stand zu alt")


def test_hourly_check_against_binance_candles(tmp_path) -> None:
    trades = make_trades()
    fake = FakeBinance(trades)
    later = NOW + timedelta(minutes=5)  # the last full hour counts once the record reaches past its end
    flow = PerpFlow(tmp_path, fetch=fake, clock=lambda: later.timestamp())
    collect(flow)
    results = flow.check()
    assert len(results) == perp_flow.CHECK_HOURS and all(r["ok"] for r in results)
    assert flow.check() == []  # checked hours are not fetched again
    assert flow.health()["checks_ok"] == flow.health()["checks"] == perp_flow.CHECK_HOURS
    # A wrong record shows up.
    flow.checks = []
    key = "2026-10-31"
    first_cell = next(iter(flow.days[key]))
    flow.days[key][first_cell][1] += 3.0
    hour = first_cell[0] // 3600 * 3600
    flow.clock = lambda: hour + 3 * 3600 + 60
    assert any(not r["ok"] for r in flow.check())


def test_saved_files_are_gzip_json_per_day_and_old_days_go(tmp_path) -> None:
    trades = make_trades()
    flow = PerpFlow(tmp_path, fetch=FakeBinance(trades), clock=lambda: NOW.timestamp())
    collect(flow)
    flow.save()
    payload = json.loads(gzip.decompress((tmp_path / "perp-2026-10-30.json.gz").read_bytes()))
    assert payload["day"] == "2026-10-30" and payload["upto"] == flow.next_id and payload["rows"]
    flow.clock = lambda: (NOW + timedelta(days=perp_flow.DAYS_KEPT + 1)).timestamp()
    flow.prune()
    flow.save()
    assert not list(tmp_path.glob("perp-2026-10-30*"))


def test_zscore_uses_the_last_window_values() -> None:
    values = [10.0] * 9 + [20.0]
    scores = zscores(values, window=10)
    assert scores[:9] == [None] * 9 and scores[9] == pytest.approx(3.0)
    assert zscores([5.0] * 4, window=2) == [None, 0.0, 0.0, 0.0]


def test_open_interest_snapshot_and_chart_part() -> None:
    start = int((NOW - timedelta(hours=299)).timestamp())
    rows = [{"timestamp": (start + i * 3600) * 1000, "sumOpenInterest": str(90_000 + (i % 7) * 10), "sumOpenInterestValue": "7.2e9"}
            for i in range(300)]
    snapshot = open_interest(lambda path, params: rows, now=NOW)
    assert snapshot["window_hours"] == 180 and len(snapshot["points"]) == 300 and len(snapshot["z"]) == 300 - 179
    part = oi_chart(snapshot, int(NOW.timestamp()) - 10 * 3600, NOW)
    assert part and not part["stale"] and len(part["points"]) == 12 and part["last"] == snapshot["points"][-1][1]
    assert oi_chart(snapshot, int(NOW.timestamp()), NOW + timedelta(hours=4))["stale"]
    with pytest.raises(ValueError):
        open_interest(lambda path, params: {"code": -1}, now=NOW)


def _store(market: str, delta_per_bucket: float, start: datetime, hours: int) -> dict:
    rows = []
    for i in range(hours * 12):
        t = int(start.timestamp()) + i * 300
        rows.append([t, 80_000.0, 1.0, 1.0 + delta_per_bucket])
    day = start.date().isoformat()
    return {"symbol": "BTCUSDT", "market": market, "tick": 5.0, "bucket_seconds": 300, "days": {day: rows}, "complete": {}, "bubbles": {}}


def test_cvd_lines_start_together_and_add_up_the_bar_deltas() -> None:
    spot = _store("spot", 0.5, NOW - timedelta(hours=6), 6)
    perp = _store("perp", -2.0, NOW - timedelta(hours=3), 3)
    times = list(range(int((NOW - timedelta(hours=6)).timestamp()), int(NOW.timestamp()), 1800))
    assert bar_deltas(spot, times, 1800)[times[0]] == pytest.approx(6 * 0.5)
    lines = cvd_lines(spot, perp, times, 1800)
    assert lines["start"] == int((NOW - timedelta(hours=3)).timestamp()) and lines["note"] is None
    assert lines["spot"][0][0] == lines["perp"][0][0] == lines["start"]
    assert lines["spot"][-1][1] == pytest.approx(3 * 12 * 0.5) and lines["perp"][-1][1] == pytest.approx(-3 * 12 * 2.0)
    only_spot = cvd_lines(spot, None, times, 1800)
    assert only_spot["perp"] == [] and only_spot["note"].startswith("CVD nur Spot")
    assert cvd_lines(spot, perp, times, 60)["note"] == "CVD ab 5m."


def test_live_chart_switches_trades_between_spot_and_perp() -> None:
    from src.dashboard.chart_live import KlineCache, build_live_chart
    from tests.test_chart_live import fake_fetch

    now = datetime(2026, 10, 26, 21, 10, tzinfo=timezone.utc)
    spot = _store("spot", 0.5, now - timedelta(hours=10), 10)
    spot["source"] = "spot-quelle"
    perp = {**_store("perp", -2.0, now - timedelta(hours=10), 10), "source": perp_flow.SOURCE, "health": {"checks": 3, "checks_ok": 3, "gaps": 0}}
    common = {"cache": KlineCache(fake_fetch()), "now": now, "footprint": spot, "perp": perp}
    default = build_live_chart("BTCUSDT", "30m", **common)
    assert default["markets"]["active"] == "spot" and default["markets"]["available"] == ["spot", "perp"]
    assert default["trade_source"] == "spot-quelle" and default["perp_health"]["checks_ok"] == 3
    assert default["cvd"]["spot"] and default["cvd"]["perp"] and {"cvd", "oi"} <= set(default["default_groups"])
    switched = build_live_chart("BTCUSDT", "30m", market="perp", **common)
    assert switched["markets"]["active"] == "perp" and switched["trade_source"] == perp_flow.SOURCE
    assert switched["footprint"]["bars"][-1]["delta"] < 0 < default["footprint"]["bars"][-1]["delta"]
    missing = build_live_chart("BTCUSDT", "30m", market="perp", cache=KlineCache(fake_fetch()), now=now, footprint=spot)
    assert missing["markets"]["active"] == "spot" and any(n.startswith("Perp-Trades noch nicht da") for n in missing["notes"])


def test_live_chart_carries_open_interest_for_btc_only() -> None:
    from src.dashboard.chart_live import KlineCache, build_live_chart
    from tests.test_chart_live import fake_fetch

    now = datetime(2026, 10, 26, 21, 10, tzinfo=timezone.utc)
    start = int((now - timedelta(hours=299)).timestamp())
    rows = [{"timestamp": (start + i * 3600) * 1000, "sumOpenInterest": str(90_000 + i), "sumOpenInterestValue": "7e9"} for i in range(300)]
    snapshot = open_interest(lambda path, params: rows, now=now)
    btc = build_live_chart("BTCUSDT", "1h", cache=KlineCache(fake_fetch()), now=now, open_interest=snapshot)
    assert btc["oi"] and btc["oi"]["points"] and btc["oi"]["last_z"] is not None
    eth = build_live_chart("ETHUSDT", "1h", cache=KlineCache(fake_fetch()), now=now, open_interest=snapshot)
    assert eth["oi"] is None
    old = build_live_chart("BTCUSDT", "1h", cache=KlineCache(fake_fetch()), now=now + timedelta(hours=4), open_interest=snapshot)
    assert old["oi"] is None


def test_runtime_loop_publishes_and_saves(tmp_path) -> None:
    trades = make_trades(start_ms=NOW_MS - 2 * 86_400_000)
    state = DashboardState()
    flow = PerpFlow(tmp_path, fetch=FakeBinance(trades), clock=lambda: NOW.timestamp())
    oi_rows = [{"timestamp": NOW_MS - i * 3_600_000, "sumOpenInterest": "90000", "sumOpenInterestValue": "7e9"} for i in range(200)]

    async def go() -> None:
        stop = asyncio.Event()
        original = perp_flow.IDLE_SECONDS
        perp_flow.IDLE_SECONDS = 0.01
        try:
            task = asyncio.create_task(perp_flow.run(state, stop, flow=flow, oi_fetch=lambda path, params: oi_rows))
            for _ in range(500):
                await asyncio.sleep(0.01)
                if state.perp_flow.get("days") and state.open_interest:
                    break
            stop.set()
            await asyncio.wait_for(task, 5)
        finally:
            perp_flow.IDLE_SECONDS = original

    asyncio.run(go())
    assert state.perp_flow["market"] == "perp" and state.perp_flow["days"]
    assert state.open_interest["points"] and (tmp_path / "state.json").exists()
