"""Hit-rate statistics for clustered trades (studies S6 and S7, section 5.2 of each).

Trades entered in the same cluster (S6: calendar day, S7: ISO week across instruments) are
not independent. The design effect D scales the binomial variance of the hit rate; the
effective sample size n / D feeds the exact Clopper-Pearson lower bound.
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def binom_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), summed in log space."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    total = 0.0
    for i in range(k, n + 1):
        total += math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                          + i * math.log(p) + (n - i) * math.log1p(-p))
    return min(total, 1.0)


def clopper_pearson_lower(successes: int, n: int, alpha: float = 0.05) -> float:
    """One-sided (1 - alpha) exact lower bound of a proportion, by bisection."""
    if n <= 0 or successes <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if binom_tail(successes, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return lo


def design_effect(hits: Sequence[bool], clusters: Sequence[str]) -> float:
    """Variance of the hit rate under clustering relative to the binomial variance; at least 1."""
    n = len(hits)
    if n == 0:
        return 1.0
    p = sum(hits) / n
    if p in (0.0, 1.0):
        return 1.0
    groups: dict[str, list[bool]] = {}
    for h, c in zip(hits, clusters):
        groups.setdefault(c, []).append(h)
    if len(groups) < 2:
        return 1.0
    total_var = sum(len(g) ** 2 * (sum(g) / len(g) - p) ** 2 for g in groups.values())
    var_p_hat = total_var / (n * n) * len(groups) / (len(groups) - 1)
    return max(1.0, n * var_p_hat / (p * (1 - p)))


def effective_counts(n: int, losers: int, d: float) -> tuple[int, int]:
    """n_eff = floor(n / D), losers_eff = ceil(losers / D)."""
    return int(math.floor(n / d + 1e-9)), int(math.ceil(losers / d - 1e-9))
