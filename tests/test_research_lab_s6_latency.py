"""Study S6 latency check on aggTrades (section 6.2, package P5)."""
from __future__ import annotations

import hashlib
import io
import random
import zipfile
from datetime import date

import pytest

from src.research_lab.data.store import HoldoutLocked
from src.research_lab.hypotheses import s6
from src.research_lab.hypotheses.s6 import LONG, SHORT
from src.research_lab.studies import s6_latency as lat

DAY = date(2021, 3, 4)
DAY_MS = 1_614_816_000_000  # 2021-03-04 00:00 UTC
M = 60_000


def _zip(rows: list[str], header: bool = False) -> bytes:
    body = ("agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n" if header else "") + "\n".join(rows) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BTCUSDT-aggTrades-2021-03-04.csv", body)
    return buf.getvalue()


def _row(i: int, price: float, qty: float, ts: int) -> str:
    return f"{i},{price},{qty},{i},{i},{ts},true"


def test_day_ref_url_and_holdout_guard() -> None:
    ref = lat.AggTradesDayRef("ETHUSDT", DAY)
    assert ref.url == "https://data.binance.vision/data/futures/um/daily/aggTrades/ETHUSDT/ETHUSDT-aggTrades-2021-03-04.zip"
    assert ref.checksum_url.endswith(".zip.CHECKSUM") and ref.start_ms == DAY_MS and ref.end_ms == DAY_MS + 86_400_000
    with pytest.raises(HoldoutLocked):
        lat.AggTradesDayRef("BTCUSDT", date(2025, 1, 1))
    with pytest.raises(ValueError):
        lat.AggTradesDayRef("DOGEUSDT", DAY)


def test_iter_trades_handles_header_and_microseconds() -> None:
    rows = [_row(1, 100.0, 0.5, DAY_MS + 10), _row(2, 101.0, 1.0, (DAY_MS + 20) * 1000)]
    plain = list(lat.iter_trades(_zip(rows)))
    headed = list(lat.iter_trades(_zip(rows, header=True)))
    assert plain == headed and [t.ts for t in plain] == [DAY_MS + 10, DAY_MS + 20]
    assert plain[0].price == 100.0 and plain[1].qty == 1.0
    found = lat.trades_in_minutes(_zip(rows + [_row(3, 99.0, 2.0, DAY_MS + 5 * M + 7)]), {DAY_MS, DAY_MS + 5 * M, DAY_MS + 9 * M})
    assert [t.price for t in found[DAY_MS]] == [100.0, 101.0] and [t.price for t in found[DAY_MS + 5 * M]] == [99.0]
    assert found[DAY_MS + 9 * M] == []


def test_sample_days_is_deterministic_sorted_and_within_days() -> None:
    days = {"SOLUSDT": {f"2021-01-{d:02d}" for d in range(1, 29)}, "BTCUSDT": {f"2020-05-{d:02d}" for d in range(1, 31)}}
    a = lat.sample_days(days)
    b = lat.sample_days(days)
    assert a == b and list(a) == ["BTCUSDT", "SOLUSDT"]
    assert all(len(v) == 10 and v == sorted(v) and set(v) <= days[k] for k, v in a.items())
    assert lat.sample_days(days, seed=1) != a
    assert lat.sample_days({"ETHUSDT": {"2020-01-01", "2020-01-02"}})["ETHUSDT"] == ["2020-01-01", "2020-01-02"]


def _trades(points: list[tuple[int, float, float]]) -> list[lat.AggTrade]:
    return [lat.AggTrade(DAY_MS + off, p, q) for off, p, q in points]


def test_check_fill_long_cases() -> None:
    limit, delta = 100.0, 0.01  # through at <= 99.99; q = 10 coins
    clean = lat.check_fill(_trades([(4_000, 100.5, 1), (8_000, 100.0, 2), (9_000, 99.98, 6), (20_000, 99.9, 5)]), DAY_MS,
                           symbol="BTCUSDT", k=2.0, side=LONG, limit=limit, delta=delta)
    assert not clean.doubtful and clean.first_through_ms == 9_000 and clean.qty_through == 11 and clean.pre_crossed_any and not clean.pre_crossed_placement
    early = lat.check_fill(_trades([(1_000, 99.9, 20)]), DAY_MS, symbol="BTCUSDT", k=2.0, side=LONG, limit=limit, delta=delta)
    assert early.reasons == ("early",)
    crossed = lat.check_fill(_trades([(2_000, 100.0, 1), (10_000, 99.9, 20)]), DAY_MS, symbol="BTCUSDT", k=2.0, side=LONG, limit=limit, delta=delta)
    assert crossed.reasons == ("pre_crossed",)
    thin = lat.check_fill(_trades([(10_000, 99.9, 3), (11_000, 100.2, 50)]), DAY_MS, symbol="BTCUSDT", k=2.0, side=LONG, limit=limit, delta=delta)
    assert thin.reasons == ("thin",) and thin.qty_through == 3
    none = lat.check_fill(_trades([(10_000, 100.0, 50)]), DAY_MS, symbol="BTCUSDT", k=2.0, side=LONG, limit=limit, delta=delta)
    assert none.reasons == ("no_trade",) and none.first_through_ms is None
    assert lat.check_fill([], DAY_MS, symbol="BTCUSDT", k=2.0, side=LONG, limit=limit, delta=delta).reasons == ("no_trade",)


def test_check_fill_short_mirrors_long() -> None:
    limit, delta = 100.0, 0.01
    ok = lat.check_fill(_trades([(5_000, 99.5, 1), (7_000, 100.02, 30)]), DAY_MS, symbol="ETHUSDT", k=3.0, side=SHORT, limit=limit, delta=delta)
    assert not ok.doubtful and ok.first_through_ms == 7_000 and ok.q == pytest.approx(10.0)
    crossed = lat.check_fill(_trades([(500, 100.0, 1), (7_000, 100.02, 30)]), DAY_MS, symbol="ETHUSDT", k=3.0, side=SHORT, limit=limit, delta=delta)
    assert crossed.reasons == ("pre_crossed",)


def test_summarize_floors_lambda_and_flags_raise() -> None:
    limit, delta = 100.0, 0.01
    good = lat.check_fill(_trades([(9_000, 99.9, 20)]), DAY_MS, symbol="BTCUSDT", k=2.0, side=LONG, limit=limit, delta=delta)
    bad = lat.check_fill(_trades([(1_000, 99.9, 20)]), DAY_MS, symbol="BTCUSDT", k=2.0, side=LONG, limit=limit, delta=delta)
    s = lat.summarize([good] * 99 + [bad])
    assert s["checked"] == 100 and s["doubtful"] == 1 and s["lambda_raw"] == 0.01 and s["lambda"] == 0.05 and not s["raise_delta"]
    s2 = lat.summarize([good] * 2 + [bad] * 2)
    assert s2["lambda"] == 0.5 and s2["raise_delta"] and s2["reasons"] == {"early": 2}
    assert lat.summarize([])["lambda"] is None
    d = lat.check_as_dict(bad)
    assert d["doubtful"] is True and d["reasons"] == ("early",)


def test_minute_store_verifies_reduces_and_caches(tmp_path) -> None:
    rows = [_row(1, 100.0, 0.5, DAY_MS + 10), _row(2, 99.0, 2.0, DAY_MS + 3 * M + 500)]
    archive = _zip(rows)
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        if url.endswith(".CHECKSUM"):
            return f"{hashlib.sha256(archive).hexdigest()}  BTCUSDT-aggTrades-2021-03-04.zip\n".encode()
        return archive

    store = lat.AggTradesMinuteStore(tmp_path, fetcher)
    ref = lat.AggTradesDayRef("BTCUSDT", DAY)
    found, digest = store.load(ref, {DAY_MS + 3 * M})
    assert digest == hashlib.sha256(archive).hexdigest() and [t.price for t in found[DAY_MS + 3 * M]] == [99.0]
    assert len(calls) == 2 and store.path(ref).exists()
    again, _ = store.load(ref, {DAY_MS + 3 * M})
    assert again == found and len(calls) == 2  # served from the reduced file
    store.load(ref, {DAY_MS, DAY_MS + 3 * M})
    assert len(calls) == 4  # a minute that was not kept triggers a new download
    with pytest.raises(ValueError):
        store.load(ref, {DAY_MS - M})

    def bad_fetcher(url: str) -> bytes:
        return b"deadbeef" * 8 + b"  BTCUSDT-aggTrades-2021-03-04.zip" if url.endswith(".CHECKSUM") else archive

    with pytest.raises(ValueError):
        lat.AggTradesMinuteStore(tmp_path / "other", bad_fetcher).load(ref, {DAY_MS})


def _market(n: int = 3_000, seed: int = 11) -> list:
    rnd = random.Random(seed)
    bars = []
    price = 100.0
    t0 = 1_577_836_800_000
    for i in range(n):
        o = price
        jump = rnd.gauss(0, 0.006) if rnd.random() < 0.03 else 0.0  # fat tails so that k = 3 limits fill too
        c = price * (1 + rnd.gauss(0, 0.0008) + jump)
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0004)) + abs(jump) * 0.5)
        lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.0004)) - abs(jump) * 0.5)
        t = t0 + i * M
        bars.append(s6.Kline(t, o, h, lo, c, 10.0, t + 59_999, 5.0))
        price = c
    return bars


def _legacy_count(bars, variant, start_ms, end_ms):
    """The gate implementation as run on 25.10. (commit 3be449f), kept here to pin list_fills to it."""
    from bisect import bisect_left

    ref = s6.compute_reference(bars)
    ticks = s6.empirical_ticks(bars)
    fills = both = unlocked = skipped = noref = 0
    days: set[str] = set()
    sides_count = {"long": 0, "short": 0}
    i = bisect_left([b.open_time for b in bars], start_ms)
    locked_until = -1
    while i < len(bars) and bars[i].open_time < end_ms:
        if i == 0 or ref.vwap[i] is None:
            if i >= locked_until:
                noref += 1
            i += 1
            continue
        tick = ticks.get(s6.month_key(bars[i].open_time), 0.0)
        b = bars[i]
        sides = []
        for side in (LONG, SHORT):
            limit = s6.limit_price(ref.vwap[i], ref.sigma30[i], variant.k, side, tick)
            if s6.crosses(bars, i, limit, side):
                if i >= locked_until:
                    skipped += 1
                continue
            if s6.traded_through(b, limit, side, s6.margin(limit, tick, s6.BASE_COSTS)):
                sides.append(side)
        if sides:
            unlocked += 1
        if sides and i >= locked_until:
            fills += 1
            days.add(s6.day_key(b.open_time))
            if len(sides) == 2:
                both += 1
                locked_until = i + 1 + s6.LOCK_AFTER_LOSS
            else:
                sides_count["long" if sides[0] == LONG else "short"] += 1
                locked_until = i + s6.TIME_STOP_BARS + s6.LOCK_AFTER_EXIT
        i += 1
    return fills, both, unlocked, skipped, noref, days, sides_count


@pytest.mark.parametrize("k", [2.0, 3.0])
def test_list_fills_reproduces_the_gate_count(k: float) -> None:
    bars = _market()
    variant = next(v for v in s6.S6_VARIANTS if v.k == k)
    end = bars[-1].open_time + M
    c = s6.count_fills(bars, variant, bars[0].open_time, end)
    fills, skipped, noref = s6.list_fills(bars, variant, bars[0].open_time, end)
    legacy = _legacy_count(bars, variant, bars[0].open_time, end)
    assert (c.fills, c.both, c.fills_unlocked, c.skipped_cross, c.no_reference, c.fill_days, c.fills_by_side) == legacy
    assert c.fills > 0 and len(fills) == c.fills_unlocked and sum(f.counted for f in fills) == c.fills
    assert (skipped, noref) == (c.skipped_cross, c.no_reference)
    for f in fills:
        assert len(f.sides) == len(f.limits) == len(f.margins) and all(d > 0 for d in f.margins)
