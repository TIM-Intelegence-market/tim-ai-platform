"""Scores each orderflow observation kind against the base rate of its window.

Orderflow observations are descriptive and carry no direction. To measure
them, the reflection uses one fixed, versioned reading (``READING``): buyer
kinds are read as "price rises", seller kinds as "price falls", activity kinds
as "price moves". A kind's hit rate is compared with how often that outcome
happened for all other kinds in the same window (the base rate), never with
50 %. The base rate is itself conditional on "some rule fired"; a rate over
random moments would need data the reflection does not read.

Statistics: exact one-sided binomial test per kind and direction, Holm
correction over every test made, 95 % Wilson interval. Observations of one
window overlap and follow each other closely, so the cases are not
independent; p-values are therefore optimistic and only open a question for
the Research Lab, they never settle one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from src.research_lab.stats.inference import holm

from .reader import ReflectionCase

READING_VERSION = "1.0.0"
READING = {
    "STRONG_BUYER_ACTIVITY": "UP",
    "RISING_CVD_ACTIVITY": "UP",
    "EXTREME_BUY_RATIO_ACTIVITY": "UP",
    "STRONG_SELLER_ACTIVITY": "DOWN",
    "FALLING_CVD_ACTIVITY": "DOWN",
    "EXTREME_SELL_RATIO_ACTIVITY": "DOWN",
    "HIGH_TRADE_FREQUENCY": "MOVE",
    "LARGE_INDIVIDUAL_TRADE_ACTIVITY": "MOVE",
}
MIN_SAMPLE = 30
ALPHA = 0.05
HORIZONS = (5, 15, 30)


def is_hit(reading: str, outcome: str | None) -> bool:
    if reading == "UP":
        return outcome == "PRICE_INCREASED"
    if reading == "DOWN":
        return outcome == "PRICE_DECREASED"
    return outcome in {"PRICE_INCREASED", "PRICE_DECREASED"}


def _log_pmf(i: int, n: int, p: float) -> float:
    return math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)


def _tail(indices: range, n: int, p: float) -> float:
    """Sum of binomial probabilities in log space; safe for thousands of cases."""
    logs = [_log_pmf(i, n, p) for i in indices]
    if not logs:
        return 0.0
    peak = max(logs)
    return min(1.0, math.exp(peak) * sum(math.exp(value - peak) for value in logs))


def binomial_upper(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), 0 < p < 1."""
    if k <= 0:
        return 1.0
    return _tail(range(k, n + 1), n, p)


def binomial_lower(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p), 0 < p < 1."""
    if k >= n:
        return 1.0
    return _tail(range(0, k + 1), n, p)


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    phat = k / n
    denominator = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denominator
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


@dataclass(frozen=True, slots=True)
class RuleScore:
    kind: str
    reading: str
    sample_size: int
    hits: int
    hit_rate: float | None
    base_rate: float | None
    interval: tuple[float, float] | None
    p_above: float | None
    p_below: float | None
    significant_above: bool
    significant_below: bool
    sufficient: bool
    misses_opposite: int
    misses_sideways: int
    horizon_hit_rates: dict[int, float | None]
    previous_hit_rate: float | None
    previous_sample_size: int

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "reading": self.reading,
            "sample_size": self.sample_size,
            "hits": self.hits,
            "hit_rate": _round(self.hit_rate),
            "base_rate": _round(self.base_rate),
            "interval_95": None if self.interval is None else [_round(self.interval[0]), _round(self.interval[1])],
            "p_above_base": _round(self.p_above),
            "p_below_base": _round(self.p_below),
            "significant_above": self.significant_above,
            "significant_below": self.significant_below,
            "sufficient": self.sufficient,
            "misses": {"opposite": self.misses_opposite, "sideways": self.misses_sideways},
            "horizon_hit_rates": {str(key): _round(value) for key, value in sorted(self.horizon_hit_rates.items())},
            "previous_week": {"sample_size": self.previous_sample_size, "hit_rate": _round(self.previous_hit_rate)},
        }


def base_rate(cases: Sequence[ReflectionCase], reading: str) -> float | None:
    if not cases:
        return None
    return sum(1 for case in cases if is_hit(reading, case.outcome)) / len(cases)


def _hit_rate(cases: Sequence[ReflectionCase], reading: str) -> float | None:
    return None if not cases else sum(1 for case in cases if is_hit(reading, case.outcome)) / len(cases)


def _rate_at(cases: Sequence[ReflectionCase], reading: str, minutes: int) -> float | None:
    known = [outcome for outcome in (case.outcome_at(minutes) for case in cases) if outcome is not None]
    return None if not known else sum(1 for outcome in known if is_hit(reading, outcome)) / len(known)


def score(cases: Iterable[ReflectionCase], previous: Iterable[ReflectionCase] = ()) -> list[RuleScore]:
    """One score per known kind, in a fixed order; tests are Holm-corrected together."""
    cases, previous = list(cases), list(previous)
    raw: list[dict] = []
    pvalues: dict[str, float] = {}
    for kind in sorted(READING):
        reading = READING[kind]
        own = [case for case in cases if case.kind == kind]
        n, hits = len(own), sum(1 for case in own if is_hit(reading, case.outcome))
        base = base_rate([case for case in cases if case.kind != kind], reading)
        sufficient = n >= MIN_SAMPLE and base is not None and 0 < base < 1
        p_above = binomial_upper(hits, n, base) if sufficient else None
        p_below = binomial_lower(hits, n, base) if sufficient else None
        if sufficient:
            pvalues[f"{kind}:above"] = p_above
            pvalues[f"{kind}:below"] = p_below
        opposite = {"UP": "PRICE_DECREASED", "DOWN": "PRICE_INCREASED"}.get(reading)
        prev = [case for case in previous if case.kind == kind]
        raw.append({
            "kind": kind, "reading": reading, "n": n, "hits": hits, "base": base, "sufficient": sufficient,
            "p_above": p_above, "p_below": p_below,
            "opposite": sum(1 for case in own if opposite and case.outcome == opposite),
            "sideways": sum(1 for case in own if case.outcome == "PRICE_SIDEWAYS"),
            "horizons": {minutes: _rate_at(own, reading, minutes) for minutes in HORIZONS},
            "prev_rate": _hit_rate(prev, reading), "prev_n": len(prev),
        })
    # Every possible test counts in m, also the ones without enough data (p = 1).
    significant = holm(pvalues, 2 * len(READING), ALPHA)
    return [
        RuleScore(
            kind=item["kind"], reading=item["reading"], sample_size=item["n"], hits=item["hits"],
            hit_rate=(item["hits"] / item["n"]) if item["n"] else None,
            base_rate=item["base"],
            interval=wilson(item["hits"], item["n"]) if item["n"] else None,
            p_above=item["p_above"], p_below=item["p_below"],
            significant_above=f"{item['kind']}:above" in significant,
            significant_below=f"{item['kind']}:below" in significant,
            sufficient=item["sufficient"],
            misses_opposite=item["opposite"], misses_sideways=item["sideways"],
            horizon_hit_rates=item["horizons"],
            previous_hit_rate=item["prev_rate"], previous_sample_size=item["prev_n"],
        )
        for item in raw
    ]

