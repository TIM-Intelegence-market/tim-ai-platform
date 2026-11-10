"""S19 orderflow thresholds on BTC (src/research_lab/studies/s19.py): grid, flags, events, counts, statistics."""
from __future__ import annotations

import csv
import hashlib
import json
import random
from datetime import date
from decimal import Decimal

import pytest

from src.orderflow_scenario import footprint as engine_fp
from src.orderflow_scenario.engines import orderflow_interpretation as engine_oi
from src.research_lab.of2.candles import Candle
from src.research_lab.orderflow_ml.bars import (
    BAR_HEADER,
    BAR_VERSION,
    E8,
    MINUTE_MS,
    PROFILE_HEADER,
    MinuteBar,
)
from src.research_lab.studies import s19

DAY = date(2021, 3, 1)
START = s19._ms(DAY)
PRICE = 50_000.0


def bar(t: int, o: float, h: float, l: float, c: float, buy: int, sell: int) -> MinuteBar:
    return MinuteBar(t, buy + sell, buy, buy * E8, sell * E8, E8, 0, buy * E8 * 100, sell * E8 * 100,
                     int(o * E8), int(c * E8), int(h * E8), int(l * E8), t + 1000)


def synthetic_day(day: date, rng: random.Random, price: float, *, spread: int = 12) -> tuple[list[MinuteBar], list[tuple[int, int, int, int]], int, float]:
    """One day of minute bars with a profile of several bins per minute (so 15m candles have >= 20 steps)."""
    width = int(0.001 * price * E8)
    start = s19._ms(day)
    bars, entries = [], []
    for i in range(1440):
        t = start + i * MINUTE_MS
        o = price
        c = price + rng.gauss(0, 0.0008) * price
        h = max(o, c) + abs(rng.gauss(0, 0.0004)) * price
        l = min(o, c) - abs(rng.gauss(0, 0.0004)) * price
        buy, sell = rng.randint(1, 12), rng.randint(1, 12)
        bars.append(bar(t, o, h, l, c, buy, sell))
        centre = int(c * E8) // width
        for k in range(-spread, spread + 1):
            entries.append((i, centre + k, rng.randint(0, 3) * E8 // 4, rng.randint(0, 3) * E8 // 4))
        price = c
    return bars, sorted(entries), width, price


def write_store(root, days: list[date], seed: int = 1) -> None:
    rng = random.Random(seed)
    price = PRICE
    (root / "bars").mkdir(parents=True, exist_ok=True)
    (root / "profile").mkdir(exist_ok=True)
    manifest = {}
    for day in days:
        bars, entries, width, price = synthetic_day(day, rng, price)
        bpath = root / "bars" / f"BTCUSDT-{day.isoformat()}.csv"
        with bpath.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(BAR_HEADER)
            writer.writerows(b.as_row() for b in bars)
        ppath = root / "profile" / f"BTCUSDT-{day.isoformat()}.csv"
        with ppath.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(PROFILE_HEADER)
            writer.writerows(entries)
        manifest[day.isoformat()] = {"bar_version": BAR_VERSION, "bars_sha256": hashlib.sha256(bpath.read_bytes()).hexdigest(),
                                     "profile_sha256": hashlib.sha256(ppath.read_bytes()).hexdigest(), "profile_width_e8": width,
                                     "quality": {"id_gaps": 0, "time_regressions": 0, "duplicate_rows": 0, "rows": 1, "empty_minutes": 0}}
    (root / "bars_manifest.json").write_text(json.dumps(manifest))


# -- grid ------------------------------------------------------------------------------------------------
def test_grid_has_28_flags_112_hypotheses_and_todays_values_are_the_code_constants() -> None:
    assert len(s19.FLAG_KEYS) == 28 and s19.HYPOTHESES == 112
    assert s19.TODAY_KEYS == {"I": "I:4x3", "A": "A:-", "C": "C:3", "T": "T:0.25", "H": "H:1.2", "E": "E:0.7x0.8"}
    for family in s19.FAMILIES:
        assert s19.TODAY[family] in s19.GRID[family]
    assert Decimal(s19.TODAY["I"][0]) == engine_fp.IMBALANCE_RATIO and s19.TODAY["I"][1] == engine_fp.STACK_MIN
    assert Decimal(s19.TODAY["C"][0]) == engine_fp.CLUSTER_RATIO and Decimal(str(s19.TODAY["T"][0])) == engine_fp.THIN_EXTREME_RATIO
    assert Decimal(str(s19.TODAY["H"][0])) == engine_oi.HEAVY_VOLUME_RATIO
    assert Decimal(str(s19.TODAY["E"][0])) == engine_oi.THIN_VOLUME_RATIO and Decimal(str(s19.TODAY["E"][1])) == engine_oi.SHRINKING_RANGE_RATIO


# -- flags per candle ------------------------------------------------------------------------------------
def _candle(start: int, open_: float, close: float, volume: int, delta: int, high: float | None = None, low: float | None = None) -> Candle:
    return Candle(start, 15, 10, open_, high if high is not None else max(open_, close), low if low is not None else min(open_, close), close, volume, delta)


def _bar(levels: list[tuple[int, int, int]], open_: float, close: float, step: float = 10.0) -> engine_fp.FootprintBar:
    """levels: (bin index, buy, sell) -> engine bar with bid = sell, ask = buy."""
    rows = tuple(engine_fp.FootprintLevel(Decimal(b) * Decimal(str(step)), Decimal(sell), Decimal(buy)) for b, buy, sell in levels)
    return engine_fp.FootprintBar(levels=rows, open=Decimal(str(open_)), close=Decimal(str(close)))


def _history(n: int = 6, volume: int = 100, rng_range: float = 20.0, close: float = 5000.0) -> list[Candle]:
    return [_candle(START + i * s19.CANDLE_MS, close, close, volume, 0, high=close + rng_range / 2, low=close - rng_range / 2) for i in range(n)]


def _flags(candle: Candle, bar, history: list[Candle] | None = None) -> set[str]:
    return set(s19.read_candle(history if history is not None else _history(), candle, bar, 10.0).flags)


def test_stacked_buy_imbalances_fire_the_imbalance_grid_by_factor_and_stack() -> None:
    # 24 levels, all balanced (5/5) except three consecutive levels whose buy side is 4x the sell side one step below.
    levels = [(500 + i, 5, 5) for i in range(24)]
    for i in (10, 11, 12):
        levels[i] = (500 + i, 20, 5)  # buy 20 against sell 5 below: ratio 4
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5100.0, 5120.0, 100, 10), _bar(levels, 5100.0, 5120.0))
    assert {"I:3x2|up", "I:3x3|up", "I:4x2|up", "I:4x3|up"} <= flags
    assert not {"I:5x2|up", "I:4x4|up", "I:3x4|up"} & flags and not any(f.startswith("I:") and f.endswith("|down") for f in flags)


def test_finished_auction_at_the_high_after_a_rise_expects_a_reversal_down() -> None:
    levels = [(500 + i, 5, 5) for i in range(24)]
    levels[-1] = (523, 5, 0)  # zero sells at the top
    history = _history(close=5000.0)
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5200.0, 5230.0, 100, 10), _bar(levels, 5200.0, 5230.0), history)
    assert "A:-|down" in flags
    falling = _flags(_candle(START + 6 * s19.CANDLE_MS, 4800.0, 4790.0, 100, 10), _bar(levels, 4800.0, 4790.0), history)
    assert "A:-|down" not in falling  # the move is down, the finished high does not count


def test_cluster_and_thin_extreme_follow_the_engine_reading_with_the_grid_ratios() -> None:
    # Down candle, heavy sell cluster at the lowest level (passive buyers hold): reversal up, strength 3.6x the mean.
    levels = [(500 + i, 2, 2) for i in range(24)]
    levels[0] = (500, 6, 10)  # total 16 against a mean of 4.5
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5230.0, 5000.0, 100, -50), _bar(levels, 5230.0, 5000.0))
    assert {"C:2|up", "C:3|up"} <= flags and "C:4|up" not in flags
    # Up candle whose top level carries 1/5 of the mean level volume: thin extreme, reversal down at 0.25 and 0.30.
    levels = [(500 + i, 10, 10) for i in range(24)]
    levels[-1] = (523, 2, 2)  # 4 against a mean of about 19.3
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5000.0, 5230.0, 100, 50), _bar(levels, 5000.0, 5230.0))
    assert {"T:0.25|down", "T:0.3|down"} <= flags and "T:0.2|down" not in flags


def test_effort_flags_absorption_and_exhaustion_against_the_aggressor() -> None:
    history = _history(volume=100, rng_range=20.0)
    # Heavy buying (delta > 0) that closes lower: absorption with effort at 1.0 and 1.2 (ratio 1.3), not 1.5.
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5000.0, 4990.0, 130, 40), None, history)
    assert {"H:1|down", "H:1.2|down"} <= flags and "H:1.5|down" not in flags and not any(f.startswith("E:") for f in flags)
    # Thin buying (ratio 0.5) that closes lower: exhaustion for every thin grid value, every shrink value (R3).
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5000.0, 4990.0, 50, 10), None, history)
    assert {f"E:{t}x{s}|down" for t in ("0.6", "0.7", "0.8") for s in ("0.7", "0.8", "0.9")} <= flags
    # Thin buying that still rises on a shrinking range (0.5 of the mean range): R4, reversal down.
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5000.0, 5008.0, 50, 10, high=5010.0, low=5000.0), None, history)
    assert "E:0.7x0.8|down" in flags
    # Thin buying that rises with an expanding range: nothing.
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5000.0, 5008.0, 50, 10, high=5030.0, low=4990.0), None, history)
    assert not any(f.startswith("E:") for f in flags)
    # Fewer than 20 traded levels: no footprint family, effort still read.
    levels = [(500 + i, 5, 5) for i in range(10)]
    flags = _flags(_candle(START + 6 * s19.CANDLE_MS, 5000.0, 4990.0, 130, 40), _bar(levels, 5000.0, 4990.0), history)
    assert not any(f[0] in "IACT" for f in flags) and "H:1.2|down" in flags


# -- events, outcomes, base rate -----------------------------------------------------------------------
def _reading(i: int, close: float, flags: tuple[str, ...] = (), traded: bool = True) -> s19.Reading:
    return s19.Reading(START + i * s19.CANDLE_MS, close, traded, 30 if traded else 0, flags)


def test_debounce_drops_a_flag_within_three_candles_of_todays_value_of_the_family() -> None:
    flags = {0: ("I:4x3|up", "I:3x2|up"), 2: ("I:3x2|up",), 3: ("I:4x3|up",), 4: ("I:4x3|down",), 7: ("I:3x2|up",), 8: ("C:3|up",)}
    readings = [_reading(i, 1, flags.get(i, ())) for i in range(9)]
    events = [(e.index, e.key, e.direction) for e in s19.events_of(readings)]
    # candle 2 and 3: within 3 of today's fire at 0 -> dropped; candle 4 is the other direction; 7 is 4 after the fire at 3
    assert events == [(0, "I:4x3", "up"), (0, "I:3x2", "up"), (4, "I:4x3", "down"), (7, "I:3x2", "up"), (8, "C:3", "up")]


def test_outcome_needs_a_gapless_run_and_the_base_rate_is_per_week_and_direction() -> None:
    readings = [_reading(i, 100 + i) for i in range(10)]
    assert s19.outcome(readings, 0, 4) == 1 and s19.outcome(readings, 6, 4) is None
    readings[3] = _reading(3, 0.0, traded=False)
    assert s19.outcome(readings, 0, 4) is None and s19.outcome(readings, 4, 4) == 1
    shifted = readings[:3] + [s19.Reading(START + 5 * s19.CANDLE_MS, 103, True, 30, ())] + readings[4:]  # a missing candle in time
    assert s19.outcome(shifted, 0, 4) is None
    rates = s19.base_rates([_reading(i, 100 + (i % 2)) for i in range(40)])  # closes alternate 100/101
    week = s19.week_of(START)
    assert rates[(week, 4, "up")] == 0.0 and rates[(week, 4, "down")] == 0.0  # after 4 candles the close is equal
    rising = s19.base_rates([_reading(i, 100 + i) for i in range(40)])
    assert rising[(week, 4, "up")] == 1.0 and rising[(week, 16, "down")] == 0.0


# -- store, workers, cache, count ------------------------------------------------------------------------
def test_read_range_is_the_same_with_one_or_two_workers_and_from_the_cache(tmp_path) -> None:
    days = [date(2021, 3, 1), date(2021, 3, 2), date(2021, 3, 3), date(2021, 3, 4)]
    write_store(tmp_path, days)
    one, gaps = s19.read_range(tmp_path, days[0], days[-1], workers=1)
    assert len(one) == 4 * 96 and gaps == [] and sum(r.traded for r in one) == 4 * 96
    assert sum(r.levels >= s19.MIN_LEVELS for r in one) > 300 and any(f.startswith("I:") for r in one for f in r.flags)
    two, _ = s19.read_range(tmp_path, days[0], days[-1], workers=2)
    assert two == one  # the second worker warms its history up from the day before its stretch
    cache = tmp_path / "cache"
    cached_first, _ = s19.read_range(tmp_path, days[0], days[1], workers=1, cache=cache)
    assert sorted(p.name for p in s19.cache_root(cache, s19.FP_STEP_PCT, s19.MIN_LEVELS).glob("*.json")) == ["2021-03-01.json", "2021-03-02.json"]
    (tmp_path / "bars" / "BTCUSDT-2021-03-01.csv").write_text("broken")  # the cache is read, not the store
    again, _ = s19.read_range(tmp_path, days[0], days[-1], workers=1, cache=cache)
    assert again == one and cached_first == one[:2 * 96]


def test_missing_day_is_a_gap_and_the_holdout_is_refused(tmp_path) -> None:
    write_store(tmp_path, [date(2021, 3, 1), date(2021, 3, 3)])
    readings, gaps = s19.read_range(tmp_path, date(2021, 3, 1), date(2021, 3, 3))
    assert gaps == ["2021-03-02"] and len(readings) == 3 * 96 and not any(r.traded for r in readings[96:192])
    assert s19.outcome(readings, 95, 4) is None
    with pytest.raises(PermissionError):
        s19.read_range(tmp_path, date(2024, 12, 30), date(2025, 1, 1))


def test_count_is_blind_and_the_gate_needs_500_events_in_100_weeks(tmp_path) -> None:
    days = [date(2021, 3, 1), date(2021, 3, 2)]
    write_store(tmp_path, days)
    readings, gaps = s19.read_range(tmp_path, days[0], days[-1])
    result = s19.count(readings, gaps)
    assert result["hypotheses"] == 112 and set(result["flags"]) == set(s19.FLAG_KEYS)
    assert result["sections"]["training"]["candles"] == 192 and result["sections"]["validierung"]["candles"] == 0
    assert all(not g["testable"] for g in result["gate"].values())
    assert sum(c["training/up"]["events"] + c["training/down"]["events"] for c in result["flags"].values()) > 0
    text = json.dumps(result)
    assert "hit" not in text and "lift" not in text
    report = s19.count_report(result, stamp="test")
    assert "`I:4x3` (heute)" in report and "Keine Trefferquote" in report


# -- statistics and verdict --------------------------------------------------------------------------------
def test_block_bootstrap_p_is_deterministic_and_orders_clear_from_null_effects() -> None:
    strong = {w: [10.0, 8.0, 5.0] for w in range(120)}  # 80 % hits against a 50 % base
    null = {w: [10.0, 5.0, 5.0] for w in range(120)}
    p_strong = s19.block_bootstrap_p(strong, seed="a", draws=499)
    assert p_strong == s19.block_bootstrap_p(strong, seed="a", draws=499) and p_strong < 0.01
    assert s19.block_bootstrap_p(null, seed="a", draws=499) > 0.5
    assert s19.block_bootstrap_p({1: [3.0, 2.0, 1.5]}, seed="a") is None
    assert s19.lift_of(strong.values()) == pytest.approx(30.0)


def _results(lift_today: float, lift_neighbour: float, *, events: int = 600, weeks: int = 120, significant: bool = True) -> dict:
    results = {}
    for section in s19.SECTIONS:
        for key in s19.FLAG_KEYS:
            for direction in s19.DIRECTIONS:
                for h in s19.HORIZONS:
                    lift = lift_today if key == "C:3" else lift_neighbour if key == "C:4" else -1.0
                    results[f"{section}/{key}/{direction}/h{h}"] = {"events": events, "weeks": weeks, "lift_pp": lift, "p": 0.001,
                                                                     "holm_significant": significant and lift > 0}
    return results


def test_verdict_confirms_replaces_only_with_a_two_point_margin_and_names_untestable_families() -> None:
    assert s19.verdict("C", _results(4.0, 5.0), True)["status"] == "bestätigt"
    replaced = s19.verdict("C", _results(4.0, 6.0), True)
    assert replaced["status"] == "bestätigt, Nachbarwert besser" and replaced["directions"]["up"]["replacement"] == "C:4"
    assert s19.verdict("C", _results(2.0, 6.0), True)["status"] == "ohne Nachweis"  # today's value fails the 3 pp floor
    assert s19.verdict("C", _results(4.0, 5.0, events=400), True)["status"] == "ohne Nachweis"
    assert s19.verdict("C", _results(4.0, 5.0, significant=False), True)["status"] == "ohne Nachweis"
    assert s19.verdict("C", _results(4.0, 5.0), False) == {"status": "nicht testbar", "today": "C:3"}


def test_evaluate_runs_end_to_end_on_a_small_store_and_reports_every_hypothesis(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(s19, "DRAWS", 99)
    days = [date(2021, 3, 1), date(2021, 3, 2), date(2021, 3, 3)]
    write_store(tmp_path, days)
    readings, gaps = s19.read_range(tmp_path, days[0], days[-1])
    result = s19.evaluate(readings, gaps)
    assert len(result["results"]) == 2 * 112 and set(result["verdicts"]) == set(s19.FAMILIES)
    assert all(v["status"] == "nicht testbar" for v in result["verdicts"].values())
    some = [r for r in result["results"].values() if r["events"] > 0]
    assert some and all(0 <= r["hit_rate"] <= 1 for r in some)
    assert "share_of_candles_with_today_flag" in result["descriptive"]
    report = s19.evaluate_report(result, stamp="test")
    assert "## Urteil je Familie" in report and "| `I:4x3` | up |" in report


def test_cli_count_writes_json_and_markdown(tmp_path) -> None:
    days = [date(2021, 3, 1), date(2021, 3, 2)]
    write_store(tmp_path / "store", days)
    assert s19.main(["count", "--bars", str(tmp_path / "store"), "--out", str(tmp_path / "out"), "--first", "2021-03-01", "--last", "2021-03-02",
                     "--cache", str(tmp_path / "cache")]) == 0
    written = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert len(written) == 2 and written[0].startswith("s19_count_") and written[0].endswith(".json")
    payload = json.loads((tmp_path / "out" / written[0]).read_text())
    assert payload["range"] == ["2021-03-01", "2021-03-02"] and len(payload["dataset_hash"]) == 64 and payload["mode"] == "count"


def test_cache_is_split_by_footprint_geometry_and_cli_accepts_it(tmp_path) -> None:
    days = [date(2021, 3, 1), date(2021, 3, 2), date(2021, 3, 3)]
    write_store(tmp_path, days)
    cache = tmp_path / "cache"
    fine, _ = s19.read_range(tmp_path, days[0], days[-1], cache=cache, min_levels=5)
    coarse, _ = s19.read_range(tmp_path, days[0], days[-1], cache=cache, min_levels=10_000)
    assert {d.name for d in cache.iterdir()} == {f"step{s19.FP_STEP_PCT:g}_levels5", f"step{s19.FP_STEP_PCT:g}_levels10000"}
    assert any(f.startswith("I:") for r in fine for f in r.flags)
    assert not any(f.split("|")[0][0] in "IACT" for r in coarse for f in r.flags)  # footprint families need the levels
    assert all(r.levels == c.levels for r, c in zip(fine, coarse, strict=True))  # the level count itself is geometry-free
    out = tmp_path / "out"
    assert s19.main(["count", "--bars", str(tmp_path), "--out", str(out), "--first", days[0].isoformat(), "--last", days[-1].isoformat(),
                     "--cache", str(cache), "--min-levels", "5", "--step-pct", str(s19.FP_STEP_PCT)]) == 0
    result = json.loads(next(out.glob("s19_count_*.json")).read_text())
    assert result["min_levels"] == 5 and result["step_pct"] == s19.FP_STEP_PCT and result["version"] == "0.3"
    assert "ab 5 gehandelten Stufen" in next(out.glob("s19_count_*.md")).read_text()
