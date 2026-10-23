import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.reflection.reader import ReflectionCase
from src.reflection.scorecard import MIN_SAMPLE, READING, binomial_lower, binomial_upper, is_hit, score, wilson

T0 = datetime(2026, 11, 23, 1, tzinfo=timezone.utc)
CHANGE = {"PRICE_INCREASED": Decimal("0.3"), "PRICE_DECREASED": Decimal("-0.3"), "PRICE_SIDEWAYS": Decimal("0")}


def case(i, kind, outcome):
    at = T0 + timedelta(minutes=i)
    return ReflectionCase(f"o{kind}{i}", kind, "BTCUSDT", at, "1.0.0", "1.0.0", outcome,
                          tuple((m, CHANGE[outcome]) for m in (5, 15, 30)), at + timedelta(minutes=30))


def many(kind, outcomes, offset=0):
    return [case(offset + i, kind, outcome) for i, outcome in enumerate(outcomes)]


def by_kind(scores):
    return {item.kind: item for item in scores}


def test_reading_covers_exactly_the_live_observation_kinds():
    source = (Path(__file__).parents[1] / "src" / "orderflow" / "observations.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'\("([A-Z_]+)", "', source))
    assert kinds == set(READING)


def test_hit_definition():
    assert is_hit("UP", "PRICE_INCREASED") and not is_hit("UP", "PRICE_SIDEWAYS")
    assert is_hit("DOWN", "PRICE_DECREASED") and not is_hit("DOWN", "PRICE_INCREASED")
    assert is_hit("MOVE", "PRICE_DECREASED") and not is_hit("MOVE", "PRICE_SIDEWAYS")


def test_binomial_and_wilson_reference_values():
    assert abs(binomial_upper(8, 10, 0.5) - 56 / 1024) < 1e-12
    assert abs(binomial_lower(2, 10, 0.5) - 56 / 1024) < 1e-12
    assert binomial_upper(0, 10, 0.3) == 1.0
    low, high = wilson(5, 10)
    assert abs(low - 0.2366) < 1e-3 and abs(high - 0.7634) < 1e-3


def test_strong_rule_beats_base_rate_after_holm():
    cases = many("STRONG_BUYER_ACTIVITY", ["PRICE_INCREASED"] * 32 + ["PRICE_SIDEWAYS"] * 8)
    cases += many("HIGH_TRADE_FREQUENCY", ["PRICE_INCREASED"] * 8 + ["PRICE_SIDEWAYS"] * 32, offset=100)
    result = by_kind(score(cases))
    buyer = result["STRONG_BUYER_ACTIVITY"]
    assert buyer.sufficient and buyer.significant_above and not buyer.significant_below
    assert buyer.base_rate == 0.2  # other kinds only
    assert buyer.misses_sideways == 8 and buyer.misses_opposite == 0
    assert buyer.horizon_hit_rates == {5: 0.8, 15: 0.8, 30: 0.8}


def test_small_samples_get_no_test():
    cases = many("STRONG_BUYER_ACTIVITY", ["PRICE_INCREASED"] * (MIN_SAMPLE - 1))
    cases += many("HIGH_TRADE_FREQUENCY", ["PRICE_SIDEWAYS"] * 40, offset=100)
    buyer = by_kind(score(cases))["STRONG_BUYER_ACTIVITY"]
    assert not buyer.sufficient and buyer.p_above is None
    assert not buyer.significant_above and not buyer.significant_below


def test_noise_is_not_significant():
    pattern = ["PRICE_INCREASED", "PRICE_DECREASED", "PRICE_SIDEWAYS"] * 14
    cases = many("STRONG_BUYER_ACTIVITY", pattern) + many("STRONG_SELLER_ACTIVITY", pattern, offset=100)
    for item in score(cases):
        assert not item.significant_above and not item.significant_below


def test_previous_week_is_reported_separately():
    now = many("STRONG_BUYER_ACTIVITY", ["PRICE_INCREASED"] * 3)
    before = many("STRONG_BUYER_ACTIVITY", ["PRICE_SIDEWAYS"] * 4, offset=-10000)
    buyer = by_kind(score(now, before))["STRONG_BUYER_ACTIVITY"]
    assert buyer.previous_sample_size == 4 and buyer.previous_hit_rate == 0.0


def test_binomial_handles_large_weeks():
    p = binomial_upper(2600, 5000, 0.5)
    assert 0.002 < p < 0.004
    assert abs(binomial_lower(2400, 5000, 0.5) - p) < 1e-12
