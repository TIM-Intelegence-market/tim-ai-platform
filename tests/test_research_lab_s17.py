"""S17: hour candles, past-only ATR, exclusions, weeks, groups, Spearman, design effect and a reproducible bootstrap."""
from __future__ import annotations

from datetime import date

import pytest

from src.research_lab.studies import s17
from src.research_lab.studies.s17 import DAY, HOUR, Candle, Case

START = s17._ms(date(2021, 1, 4))  # a Monday


def _minute(start: int, trades: int, first: int, last: int, high: int, low: int) -> list[int]:
    return [start, trades, 6, 4, first, last, high, low]


def _flat(hours: int, price: float = 100.0, width: float = 2.0, start: int = START) -> dict[int, Candle]:
    return {start + h * HOUR: Candle(start + h * HOUR, True, price, price + width / 2, price - width / 2, price)
            for h in range(hours)}


def test_hour_candle_takes_first_and_last_traded_minute():
    rows = [_minute(START + i * 60_000, 0, 0, 0, 0, 0) for i in range(60)]
    rows[3] = _minute(START + 3 * 60_000, 2, 100 * 10**8, 101 * 10**8, 102 * 10**8, 99 * 10**8)
    rows[4] = _minute(START + 4 * 60_000, 1, 101 * 10**8, 103 * 10**8, 104 * 10**8, 100 * 10**8)
    rows[50] = _minute(START + 50 * 60_000, 1, 103 * 10**8, 98 * 10**8, 103 * 10**8, 97 * 10**8)
    c = s17.hour_candle(START, rows)
    assert (c.open, c.high, c.low, c.close, c.trade_count) == (100, 104, 97, 98, 4)
    assert c.minute_vol is None  # only one pair of adjacent traded minutes
    assert not s17.hour_candle(START, [_minute(START + i * 60_000, 0, 0, 0, 0, 0) for i in range(60)]).trades


def test_atr_uses_only_closed_past_candles_as_indicators_atr():
    candles = _flat(30)
    start = START + 20 * HOUR
    assert s17.atr_before(candles, start) == pytest.approx(2.0)
    # A huge range in the case's own hour must not change its ATR.
    candles[start] = Candle(start, True, 100, 150, 50, 100)
    assert s17.atr_before(candles, start) == pytest.approx(2.0)
    # The previous close enters the true range (gap of 10 at the oldest used pair).
    candles[start - 15 * HOUR] = Candle(start - 15 * HOUR, True, 90, 91, 89, 90)
    assert s17.atr_before(candles, start) == pytest.approx((2.0 * 13 + 11.0) / 14)
    assert s17.atr_before(candles, START + 14 * HOUR) is None  # only 14 earlier candles


def test_exclusions_and_cost_in_r():
    candles = _flat(48)
    candles[START + 30 * HOUR] = Candle(START + 30 * HOUR, False)
    cases, excluded = s17.build_cases(candles, START, START + 48 * HOUR)
    assert excluded == {"stunde_ohne_handel": 1, "vorlauf_unvollstaendig": 15 + 15, "fehlerhafte_minute": 0}
    assert len(cases) == 48 - 31
    assert cases[0].cost_r == pytest.approx(0.0016 * 100 / (1.5 * 2.0))
    candles[START + 40 * HOUR] = Candle(START + 40 * HOUR, True, 100, 101, 99, 100, faulty=True)
    _, excluded = s17.build_cases(candles, START, START + 48 * HOUR)
    assert excluded["fehlerhafte_minute"] == 8


def test_week_weekday_and_sections():
    assert s17.weekday_of(START) == 0 and s17.weekday_of(START + 6 * DAY + 23 * HOUR) == 6
    assert s17.week_of(START) == s17.week_of(START + 7 * DAY - 1) != s17.week_of(START + 7 * DAY)
    assert s17.section_of(s17._ms(date(2022, 12, 31)) + 23 * HOUR) == "training"
    assert s17.section_of(s17._ms(date(2023, 1, 1))) == "validierung"
    assert s17.section_of(s17._ms(date(2025, 1, 1))) is None


def test_holdout_is_refused_before_reading(tmp_path):
    with pytest.raises(PermissionError):
        s17.load_candles(tmp_path, date(2024, 12, 30), date(2025, 1, 1))


def test_groups_break_ties_by_smaller_key():
    medians = {h: float(h % 3) for h in range(24)}
    cheap, dear = s17.pick_groups(medians)
    assert cheap == [0, 3, 6, 9, 12, 15] and dear == [2, 5, 8, 11, 14, 17]


def test_spearman_with_ties():
    assert s17.spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert s17.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert s17.spearman([1, 1, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9486833, rel=1e-6)


def test_design_effect():
    assert s17.design_effect([1.0, 2.0, 3.0, 4.0], [1, 2, 3, 4]) == 1.0
    assert s17.design_effect([1.0, 1.0, 3.0, 3.0], [1, 1, 2, 2]) == pytest.approx(1.5)  # same formula as S16


def test_p_two_sided():
    assert s17.p_two_sided([1.0] * 99, 99) == pytest.approx(0.02)
    assert s17.p_two_sided([-1.0, 1.0] * 50, 100) == 1.0


def _cases(weeks: int, dear_hours: set[int]) -> list[Case]:
    out = []
    for w in range(weeks):
        for k in range(7 * 24):
            start = START + w * 7 * DAY + k * HOUR
            hour = k % 24
            cost = 0.3 if hour in dear_hours else 0.1
            cost += ((w * 31 + k * 7) % 11) * 0.001
            out.append(Case(start, "training", cost, 0.01))
    return out


def test_week_bootstrap_is_reproducible_and_finds_the_difference():
    cases = _cases(12, {20, 21, 22, 23, 0, 1})
    groups = s17.pick_groups(s17.medians_by(cases, "hour"))
    assert groups[1] == [0, 1, 20, 21, 22, 23]
    comps = {"stunden": (groups[0], groups[1], "hour")}
    a = s17.week_bootstrap(cases, comps, draws=200, seed=3)
    b = s17.week_bootstrap(cases, comps, draws=200, seed=3)
    assert a == b
    assert a["stunden"]["delta_r"] == pytest.approx(0.2, abs=0.01)
    assert a["stunden"]["p"] == pytest.approx(2 / 201) and a["stunden"]["wochen"] == 12


def test_spec_digest_covers_rules_only():
    text = "# T\n| Spezifikation | x, „## 1.“ bis „## Änderungsprotokoll“ |\n## 1. Frage\nA\n## Änderungsprotokoll\n| 1 |\n"
    other = text.replace("| x |", "| y |").replace("| 1 |", "| 2 |")
    assert s17.spec_digest(text) == s17.spec_digest(other)
    assert s17.spec_digest(text) != s17.spec_digest(text.replace("A\n", "B\n"))
    assert len(s17.spec_digest(text)) == 64


def test_load_candles_checks_manifest_and_builds_24_hours(tmp_path):
    import hashlib
    import json
    day = date(2021, 3, 1)
    header = ("window_start_ms,trade_count,buy_count,buy_sats,sell_sats,largest_sats,large_count,buy_quote_e8,"
              "sell_quote_e8,first_price_e8,last_price_e8,high_price_e8,low_price_e8,last_trade_ms")
    start = s17._ms(day)
    lines = [header] + [f"{start + i * 60_000},1,1,1,0,1,0,100,0,{10**10},{10**10},{10**10 + 10**8},{10**10 - 10**8},"
                        f"{start + i * 60_000 + 5}" for i in range(1440)]
    (tmp_path / "bars").mkdir()
    path = tmp_path / "bars" / "BTCUSDT-2021-03-01.csv"
    path.write_text("\n".join(lines) + "\n")
    entry = {"bars_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "quality": {"id_gaps": 0, "time_regressions": 0, "duplicate_rows": 0}}
    (tmp_path / "bars_manifest.json").write_text(json.dumps({"2021-03-01": entry}))
    candles, digest = s17.load_candles(tmp_path, day, day)
    assert len(candles) == 24 and len(digest) == 64
    c = candles[start + 5 * HOUR]
    assert (c.open, c.high, c.low, c.close, c.trade_count, c.faulty) == (100, 101, 99, 100, 60, False)
    path.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(ValueError):
        s17.load_candles(tmp_path, day, day)
