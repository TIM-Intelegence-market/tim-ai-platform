"""Study S13: noise-band breakout (rules only, synthetic bars, no market data)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from src.research_lab.backtest.engine import run_backtest
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s13
from src.research_lab.protocol import CostModel

NY, UTC = s13.S13_VARIANTS
M = s13.INTERVAL_MS
ZERO = CostModel(0.0, 0.0, 0.0)


def _k(t: int, o: float, h: float, low: float, c: float, vol: float = 1.0) -> Kline:
    return Kline(t, o, h, low, c, vol, t + M - 1, vol / 2)


def _utc_bars(days: int, last_day: dict[int, float] | None = None, wiggle: float = 0.01,
              start: date = date(2021, 3, 1)) -> tuple[list[Kline], int]:
    """1m bars over `days` UTC days. Every day opens at 100; minute k closes at 100 * (1 + wiggle) on
    odd k and 100 * (1 - wiggle) on even k, so |move| = wiggle at every minute and sigma = wiggle.
    `last_day` overrides closes of the final day by minute k (bar opens at the previous close)."""
    anchor0 = int(datetime.combine(start, time(0), tzinfo=timezone.utc).timestamp() * 1000)
    bars: list[Kline] = []
    for d in range(days):
        anchor = anchor0 + d * s13.DAY_MS
        prev = 100.0
        for k in range(1, 1441):
            t = anchor + (k - 1) * M
            close = 100 * (1 + wiggle) if k % 2 else 100 * (1 - wiggle)
            if d == days - 1 and last_day is not None and k in last_day:
                close = last_day[k]
            o = 100.0 if k == 1 else prev
            bars.append(_k(t, o, max(o, close), min(o, close), close))
            prev = close
    return bars, anchor0


def test_variants_are_the_preregistered_pair() -> None:
    assert [(v.variant_id, v.anchor) for v in s13.S13_VARIANTS] == [("S13-NY", "ny"), ("S13-UTC", "utc")]
    assert NY.params["band_multiplier"] == 1.0 and NY.params["lookback_sessions"] == 14


def test_ny_sessions_follow_nyse_calendar_and_dst() -> None:
    days = s13.sessions(NY, s13.ny_ms(date(2021, 3, 12), s13.NY_OPEN), s13.ny_ms(date(2021, 3, 17), s13.NY_OPEN))
    assert [x.day for x in days] == [date(2021, 3, 12), date(2021, 3, 15), date(2021, 3, 16)]
    winter, summer = days[0], days[1]  # US DST started 2021-03-14
    assert winter.anchor_ms % s13.DAY_MS == (14 * 60 + 30) * M
    assert summer.anchor_ms % s13.DAY_MS == (13 * 60 + 30) * M
    assert all(x.minutes == 390 for x in days)
    assert summer.prev_close_ms == s13.ny_ms(date(2021, 3, 12), s13.NY_CLOSE) - M  # Friday's last bar
    hol = s13.sessions(NY, s13.ny_ms(date(2021, 12, 23), s13.NY_OPEN), s13.ny_ms(date(2021, 12, 28), s13.NY_OPEN))
    assert date(2021, 12, 24) not in [x.day for x in hol]  # Christmas observed


def test_sigma_band_and_warmup() -> None:
    bars, anchor0 = _utc_bars(16)
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    assert len(table.sessions) == 16
    early = table.check(anchor0 + 13 * s13.DAY_MS + 29 * M)  # session 13: only 13 earlier sessions
    assert early is not None and early.upper is None
    ch = table.check(anchor0 + 14 * s13.DAY_MS + 29 * M)  # session 14, k = 30
    assert ch is not None and ch.k == 30 and not ch.last and ch.entry_allowed
    assert ch.upper == pytest.approx(101.0) and ch.lower == pytest.approx(99.0)
    assert ch.risk == pytest.approx(3.0)
    end = table.check(anchor0 + 14 * s13.DAY_MS + (s13.UTC_SESSION_MINUTES - 1) * M)
    assert end is not None and end.last and not end.entry_allowed


def test_breakout_long_short_and_inside() -> None:
    bars, anchor0 = _utc_bars(16, {30: 101.5, 60: 98.5})
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    base = anchor0 + 15 * s13.DAY_MS
    assert s13.entry_side(table.check(base + 29 * M), 101.5) == 1
    assert s13.entry_side(table.check(base + 59 * M), 98.5) == -1
    assert s13.entry_side(table.check(base + 89 * M), 101.0) == 0  # equal to the band is not a breakout
    assert table.check(base + 30 * M) is None  # not a check bar


def test_no_band_when_today_has_a_gap() -> None:
    bars, anchor0 = _utc_bars(16, {30: 101.5})
    base = anchor0 + 15 * s13.DAY_MS
    bars = [b for b in bars if b.open_time != base + 10 * M]
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    ch = table.check(base + 29 * M)
    assert ch is not None and ch.upper is None and ch.vwap is None
    assert s13.entry_side(ch, 101.5) == 0


def test_decision_at_check_bar_does_not_read_later_bars() -> None:
    """A table built from bars cut right after a check bar gives the same check there."""
    bars, anchor0 = _utc_bars(16, {30: 101.5, 60: 100.2, 90: 99.0})
    end = anchor0 + 16 * s13.DAY_MS
    full = s13.build_table(bars, UTC, anchor0, end)
    for k in (30, 60, 90):
        t = anchor0 + 15 * s13.DAY_MS + (k - 1) * M
        cut = s13.build_table([b for b in bars if b.open_time <= t], UTC, anchor0, end)
        a, b = full.check(t), cut.check(t)
        assert a is not None and b is not None
        assert (a.upper, a.lower, a.vwap, a.risk) == (b.upper, b.lower, b.vwap, b.risk)


def test_trailing_exit_rule() -> None:
    ch = s13.Check(0, 60, False, True, 101.0, 99.0, 100.5, 3.0)
    assert not s13.exits(ch, 1, 101.2)
    assert s13.exits(ch, 1, 100.9)  # below max(upper 101, vwap 100.5)
    vw = s13.Check(0, 60, False, True, 101.0, 99.0, 101.6, 3.0)
    assert s13.exits(vw, 1, 101.4)  # VWAP above the band is the stop
    assert not s13.exits(ch, -1, 98.8) and s13.exits(ch, -1, 99.1)
    assert s13.exits(s13.Check(0, 1410, True, False, 101.0, 99.0, 100.0, 3.0), 1, 150.0)  # session end
    assert s13.exits(s13.Check(0, 60, False, True, None, None, None, None), 1, 150.0)  # no band: flat


def test_engine_run_long_trails_out_and_r_uses_catastrophe_stop() -> None:
    # Session 15: breakout at k=30 (101.5), still above at k=60, falls back inside at k=90.
    closes = {k: 101.5 for k in range(30, 89)} | {k: 100.0 for k in range(89, 1441)}
    bars, anchor0 = _utc_bars(16, closes)
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    result = run_backtest(bars, s13.strategy(table), M, costs=ZERO)
    assert len(result.trades) == 1
    trade = result.trades[0]
    base = anchor0 + 15 * s13.DAY_MS
    assert trade.side == 1 and trade.entry_time == base + 30 * M and trade.entry_price == pytest.approx(101.5)
    assert trade.stop == pytest.approx(101.5 - 3.0)
    assert trade.reason == "rule" and trade.exit_time == base + 90 * M  # exit at the open after the k=90 check
    assert trade.r == pytest.approx((100.0 - 101.5) / 3.0)


def test_engine_flat_at_session_end_and_catastrophe_stop() -> None:
    closes = {k: 101.5 for k in range(30, 1441)}
    bars, anchor0 = _utc_bars(16, closes)
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    trades = run_backtest(bars, s13.strategy(table), M, costs=ZERO).trades
    assert len(trades) == 1 and trades[0].reason == "rule"
    assert trades[0].exit_time == anchor0 + 15 * s13.DAY_MS + s13.UTC_SESSION_MINUTES * M

    crash = {k: 101.5 for k in range(30, 45)} | {k: 97.0 for k in range(45, 1441)}
    bars, anchor0 = _utc_bars(16, crash)
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    trades = run_backtest(bars, s13.strategy(table), M, costs=ZERO).trades
    assert trades[0].reason.startswith("stop") and trades[0].r == pytest.approx(-1.0, abs=0.2)


def test_count_is_first_signal_per_session() -> None:
    bars, anchor0 = _utc_bars(16, {30: 101.5, 60: 98.5})
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    result = s13.count_signals(bars, table, anchor0)
    c = result.counts
    assert (c.sessions, c.warmup, c.signals) == (16, 14, 1)
    assert c.no_breakout == 1  # session 14 is all wiggle, never outside the band
    assert result.signals[0].direction == 1 and result.signals[0].signal_time == anchor0 + 15 * s13.DAY_MS + 29 * M


def test_ny_band_uses_previous_close_for_gaps() -> None:
    """Every bar opens at 100 and closes at 100 * (1 +/- 1 %), so sigma = 1 %. Yesterday's last bar
    closed at 98 (gap up today): upper uses the open 100, lower the previous close 98."""
    days = s13.sessions(NY, s13.ny_ms(date(2021, 2, 1), s13.NY_OPEN), s13.ny_ms(date(2021, 2, 24), s13.NY_OPEN))
    assert len(days) >= 16
    target, prev = days[15], days[14]
    first, last = days[0].anchor_ms - 60 * M, target.end_ms + 60 * M
    bars = []
    for i, t in enumerate(range(first, last, M)):
        close = 98.0 if t == target.prev_close_ms else 100 * (1.01 if i % 2 else 0.99)
        bars.append(_k(t, 100.0, max(100.0, close), min(100.0, close), close))
    assert target.prev_close_ms == prev.end_ms - M
    table = s13.build_table(bars, NY, days[0].anchor_ms, target.anchor_ms + 1)
    ch = table.check(target.anchor_ms + 29 * M)
    assert ch is not None and ch.k == 30
    assert ch.upper == pytest.approx(101.0) and ch.lower == pytest.approx(98 * 0.99)
    assert ch.risk == pytest.approx(3.0)


def test_no_same_side_reentry_on_the_exit_bar() -> None:
    """Above the band but below VWAP: the long exits and is not bought back on the same check bar."""
    closes = {k: 103.0 for k in range(30, 60)} | {k: 101.2 for k in range(60, 1441)}
    bars, anchor0 = _utc_bars(16, closes)
    table = s13.build_table(bars, UTC, anchor0, anchor0 + 16 * s13.DAY_MS)
    check = table.check(anchor0 + 15 * s13.DAY_MS + 59 * M)
    assert check is not None and check.upper < 101.2 < check.vwap
    trades = run_backtest(bars, s13.strategy(table), M, costs=ZERO).trades
    assert trades[0].exit_time == anchor0 + 15 * s13.DAY_MS + 60 * M
    assert all(t.entry_time != trades[0].exit_time for t in trades[1:])
