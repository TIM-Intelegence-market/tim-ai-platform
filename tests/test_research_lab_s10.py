"""Study S10: IB breakout, POC-zone retest (rules only, synthetic bars, no market data)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s10

DAY = date(2020, 1, 2)  # Thursday, NYSE open, New York winter time (09:30 = 14:30 UTC)
P, O = s10.S10_VARIANTS
IB_START = s10.ny_ms(DAY, s10.IB_START)
STEP = s10.INTERVAL_MS


def _k(t: int, o: float, h: float, low: float, c: float, vol: float = 10.0, taker: float = 5.0, step: int = STEP) -> Kline:
    return Kline(t, o, h, low, c, vol, t + step - 1, taker)


def _ib(low: float = 100.0, high: float = 110.0) -> list[Kline]:
    """30 1m bars inside [low, high]; most volume around 104-106 (POC there), both extremes touched."""
    bars = []
    for i in range(30):
        t = IB_START + i * 60_000
        if i == 0:
            bars.append(_k(t, 105, high, 104, 105, 1.0, step=60_000))
        elif i == 1:
            bars.append(_k(t, 105, 106, low, 105, 1.0, step=60_000))
        else:
            bars.append(_k(t, 105, 106, 104, 105, 20.0, step=60_000))
    return bars


def _session(moves: dict[int, tuple[float, float, float, float, float, float]] | None = None) -> list[Kline]:
    """5m bars from the warm-up start to 16:00. Index 0 = first bar at or after 10:00 (IB end).
    Default bar: flat around 105, range 1, volume 10, delta 0."""
    start, end = s10.session_window(DAY)
    ib_end = s10.ny_ms(DAY, s10.IB_END)
    bars = []
    for t in range(start, end, STEP):
        idx = (t - ib_end) // STEP
        o, h, low, c, vol, taker = (moves or {}).get(idx, (105.0, 105.5, 104.5, 105.0, 10.0, 5.0))
        bars.append(_k(t, o, h, low, c, vol, taker))
    return bars


def _scan(session: list[Kline], variant: s10.S10Variant = P, ib: list[Kline] | None = None, atr: float | None = 20.0):
    counts = s10.Counts()
    signal = s10.scan_day(DAY, s10.DayData(ib if ib is not None else _ib(), session), atr, variant, counts)
    return signal, counts


BREAKOUT_UP = (110.5, 112.0, 110.0, 111.5, 10.0, 6.0)  # closes above IBH 110
RETEST = (111.5, 111.6, 105.5, 105.8, 10.0, 5.0)  # low into the zone (VAH 106), closes inside
REACTION = (107.0, 109.0, 106.8, 108.5, 10.0, 6.0)  # closes above VAH


def test_variants_are_the_preregistered_pair() -> None:
    assert [v.variant_id for v in s10.S10_VARIANTS] == ["S10-P", "S10-O"]
    assert [v.orderflow for v in s10.S10_VARIANTS] == [False, True]


def test_ib_profile_puts_poc_and_value_area_where_the_volume_is() -> None:
    profile = s10.ib_profile(_ib())
    assert profile is not None
    assert (profile.low, profile.high) == (100.0, 110.0)
    assert 104.0 <= profile.val < profile.poc < profile.vah <= 106.5


def test_ib_profile_tie_goes_to_the_middle() -> None:
    flat = [_k(IB_START + i * 60_000, 0, 40, 0, 0, 1.0, step=60_000) for i in range(30)]  # bins of exactly 1.0
    profile = s10.ib_profile(flat)
    assert profile is not None and profile.poc == 19.5  # bins 19 and 20 tie nearest the middle; the lower wins


def test_trading_days_skip_weekends_holidays_and_follow_dst() -> None:
    days = s10.trading_days(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000,
                            datetime(2020, 1, 7, tzinfo=timezone.utc).timestamp() * 1000)
    assert days == [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)]  # 1 Jan holiday, 4/5 Jan weekend
    assert s10.ny_ms(date(2020, 1, 2), s10.IB_START) == int(datetime(2020, 1, 2, 14, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert s10.ny_ms(date(2020, 7, 1), s10.IB_START) == int(datetime(2020, 7, 1, 13, 30, tzinfo=timezone.utc).timestamp() * 1000)


def test_long_breakout_retest_reaction_gives_one_signal() -> None:
    signal, counts = _scan(_session({0: BREAKOUT_UP, 1: RETEST, 2: REACTION}))
    assert signal is not None and signal.direction == 1
    ib_end = s10.ny_ms(DAY, s10.IB_END)
    assert signal.signal_time == ib_end + 3 * STEP
    assert signal.entry_time == ib_end + 3 * STEP
    assert signal.stop < signal.profile.val
    assert counts.signals == 1 and counts.days == 1


def test_retest_bar_may_be_the_reaction_bar() -> None:
    both = (111.5, 111.6, 106.0, 108.5, 10.0, 6.0)
    signal, _ = _scan(_session({0: BREAKOUT_UP, 1: both}))
    assert signal is not None


def test_short_is_mirrored() -> None:
    down = (99.5, 100.0, 98.0, 98.5, 10.0, 4.0)
    retest = (98.5, 105.0, 98.4, 103.0, 10.0, 5.0)  # high into [VAL, POC], close inside
    reaction = (103.0, 103.2, 101.0, 101.5, 10.0, 4.0)  # closes below VAL
    signal, _ = _scan(_session({0: down, 1: retest, 2: reaction}))
    assert signal is not None and signal.direction == -1 and signal.stop > signal.profile.vah


def test_close_beyond_far_value_area_edge_invalidates_the_day() -> None:
    deep = (111.5, 111.6, 100.5, 101.0, 10.0, 5.0)  # closes below VAL
    signal, counts = _scan(_session({0: BREAKOUT_UP, 1: deep, 2: REACTION}))
    assert signal is None and counts.invalidated == 1


def test_no_breakout_before_noon() -> None:
    late = {i: (105.0, 112.0, 104.5, 111.0, 10.0, 6.0) for i in range(24, 30)}  # 12:00 onwards
    signal, counts = _scan(_session(late))
    assert signal is None and counts.no_breakout == 1


def test_breakout_bar_closing_at_noon_counts() -> None:
    ib_end = s10.ny_ms(DAY, s10.IB_END)
    last = (s10.ny_ms(DAY, s10.LAST_BREAKOUT_CLOSE) - STEP - ib_end) // STEP
    signal, _ = _scan(_session({last: BREAKOUT_UP, last + 1: RETEST, last + 2: REACTION}))
    assert signal is not None


def test_reaction_after_one_pm_is_too_late() -> None:
    ib_end = s10.ny_ms(DAY, s10.IB_END)
    first_late = (s10.ny_ms(DAY, s10.LAST_REACTION_CLOSE) - ib_end) // STEP  # bar opening at 13:00
    above = {i: (111.5, 112.0, 111.0, 111.5, 10.0, 5.0) for i in range(1, first_late)}  # price stays above the zone
    signal, counts = _scan(_session({0: BREAKOUT_UP, **above, first_late: RETEST, first_late + 1: REACTION}))
    assert signal is None and counts.no_retest == 1


def test_touch_without_reaction_counts_as_no_reaction() -> None:
    signal, counts = _scan(_session({0: BREAKOUT_UP, 1: RETEST}))
    assert signal is None and counts.no_reaction == 1


def test_narrow_ib_is_skipped() -> None:
    signal, counts = _scan(_session({0: BREAKOUT_UP, 1: RETEST, 2: REACTION}), atr=50.0)  # 10 < 0.25 x 50
    assert signal is None and counts.ib_narrow == 1


def test_missing_bars_or_atr_skip_the_day() -> None:
    session = _session({0: BREAKOUT_UP, 1: RETEST, 2: REACTION})
    signal, counts = _scan(session[:10] + session[11:])
    assert signal is None and counts.data_missing == 1
    signal, counts = _scan(session, ib=_ib()[:-1])
    assert signal is None and counts.data_missing == 1
    signal, counts = _scan(session, atr=None)
    assert signal is None and counts.atr_missing == 1


def test_variant_o_needs_absorption_at_the_zone() -> None:
    signal, counts = _scan(_session({0: BREAKOUT_UP, 1: RETEST, 2: REACTION}), O)
    assert signal is None and counts.no_absorption == 1
    absorbing = (111.5, 111.6, 105.5, 106.2, 30.0, 10.0)  # into the zone, volume 3x, delta -10
    wide = (105, 112, 100, 105, 10, 5)  # wide bars before, so range 6.1 < 0.8 x mean range 7.8
    session = _session({-3: wide, -2: wide, -1: wide,
                        0: BREAKOUT_UP, 1: absorbing, 2: REACTION})
    signal, _ = _scan(session, O)
    assert signal is not None and signal.direction == 1


def test_absorption_rule() -> None:
    quiet = [_k(i * STEP, 100, 101, 99, 100, 10.0, 5.0) for i in range(5)]
    sellers_absorbed = _k(5 * STEP, 100, 100.5, 99.5, 100, 15.0, 4.0)  # delta -7, volume 1.5x, range 0.5x
    assert s10.absorbed(quiet + [sellers_absorbed], 1)
    assert not s10.absorbed(quiet + [sellers_absorbed], -1)  # delta is with a short
    thin = _k(5 * STEP, 100, 100.5, 99.5, 100, 8.0, 2.0)
    assert not s10.absorbed(quiet + [thin], 1)
    assert not s10.absorbed(quiet[1:] + [sellers_absorbed], 1)  # fewer than five bars before


def test_signal_ignores_bars_after_it() -> None:
    base = {0: BREAKOUT_UP, 1: RETEST, 2: REACTION}
    a, _ = _scan(_session(base))
    later = {**base, **{i: (105.0, 140.0, 60.0, 61.0, 99.0, 1.0) for i in range(4, 60)}}
    b, _ = _scan(_session(later))
    assert a == b


def test_daily_atr_needs_complete_days() -> None:
    day0 = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    bars = [_k(day0 + i * STEP, 100, 110, 90, 100) for i in range(15 * 288)]
    daily = s10.daily_bars(bars)
    target = day0 + 15 * s10.DAY_MS
    assert s10.daily_atr_before(daily, target) == 20.0
    del daily[day0 + 3 * s10.DAY_MS]
    assert s10.daily_atr_before(daily, target) is None


def test_split_day_data_and_count() -> None:
    session = _session({0: BREAKOUT_UP, 1: RETEST, 2: REACTION})
    data = s10.split_day_data([DAY], _ib(), session)
    assert len(data[DAY].ib) == 30 and data[DAY].session == session
    day_start = int(datetime(2020, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
    daily = {day_start - k * s10.DAY_MS: (120.0, 100.0, 110.0, 288) for k in range(1, 16)}
    result = s10.count_signals([DAY], data, daily, P)
    assert len(result.signals) == 1 and result.counts.signals == 1


def test_count_script_writes_an_outcome_blind_report(tmp_path) -> None:
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("research_lab_s10", "scripts/research_lab_s10.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    day_start = int(datetime(2020, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
    history = [_k(t, 105, 105.5, 104.5, 105) for t in range(day_start - 15 * s10.DAY_MS, day_start, STEP)]
    session = _session({0: BREAKOUT_UP, 1: RETEST, 2: REACTION})

    class FakeStore:
        def load_klines(self, refs):
            refs = list(refs)
            if refs[0].symbol != "BTCUSDT":
                return []
            if refs[0].interval == "1m":
                return _ib() if refs[0].period == "2020-01" else []
            return history + session

        def dataset_hash(self, refs):
            return "fake"

    assert script.count(FakeStore(), tmp_path) == 0
    report = json.loads(next(tmp_path.glob("s10_count_*.json")).read_text())
    assert report["outcome_blind"] and set(report["variants"]) == {"S10-P", "S10-O"}
    row = report["variants"]["S10-P"]
    assert row["train"] == {"signals": 1, "signal_days": 1, "btc": 1, "long": 1, "short": 0} and not row["passes_gate"]
    assert report["variants"]["S10-O"]["train"]["signals"] == 0
    assert "expectancy" not in json.dumps(report)
    assert next(tmp_path.glob("s10_count_*.md")).read_text().startswith("# S10 Zähllauf")
