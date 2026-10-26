"""Clustered hit-rate statistics shared by S6 and S7."""
from __future__ import annotations

import math

from src.research_lab.stats.clustered import binom_tail, clopper_pearson_lower, design_effect, effective_counts


def test_binomial_tail_matches_direct_sum() -> None:
    n, p = 12, 0.3
    direct = sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(5, n + 1))
    assert abs(binom_tail(5, n, p) - direct) < 1e-12
    assert binom_tail(0, n, p) == 1.0 and binom_tail(13, n, p) == 0.0


def test_clopper_pearson_lower_bound() -> None:
    lower = clopper_pearson_lower(30, 100)
    assert 0.22 < lower < 0.30  # exact one-sided 95 % bound for 30/100 is about 0.226
    assert abs(binom_tail(30, 100, lower) - 0.05) < 1e-6
    assert clopper_pearson_lower(0, 100) == 0.0
    assert clopper_pearson_lower(100, 100) > 0.97


def test_design_effect_grows_with_clustered_outcomes() -> None:
    hits = [True] * 20 + [False] * 20
    independent = design_effect(hits, [str(i) for i in range(40)])
    clustered = design_effect(hits, ["a"] * 20 + ["b"] * 20)
    assert independent == 1.0 or independent < clustered
    assert clustered > 5
    assert design_effect([True] * 5, ["a", "a", "b", "b", "c"]) == 1.0
    assert effective_counts(100, 70, 2.5) == (40, 28)
