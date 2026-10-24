"""Power-Simulation S2 für die Zusatzstudie S-K.

Frage: Reichen die Mindestzahlen der Spezifikation (300 Fenster pro Klasse,
30 pro Regimestufe), um einen Unterschied zwischen Positiv- und
Negativfenstern eines Signaltyps zu erkennen?

Ergebnisvariable wie in der Kampagne: PRICE_INCREASED / PRICE_DECREASED /
PRICE_SIDEWAYS. Test: Chi-Quadrat 2x3 (POSITIVE gegen NEGATIVE), df = 2,
p = exp(-X²/2). Bonferroni über alle Signaltypen und Horizonte.

Es werden keine Marktdaten gelesen: Die Grundverteilung wird über eine
Spanne von Seitwärtsanteilen variiert. Damit bleibt die Simulation frei von
Ergebnissen aus der Zeit vor T0. Reines Python mit festem Seed, deterministisch.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

OUTCOMES = ("PRICE_INCREASED", "PRICE_DECREASED", "PRICE_SIDEWAYS")
SEED = 20261022


def chi2_2x3_pvalue(a: Sequence[int], b: Sequence[int]) -> float:
    """p-Wert des Chi-Quadrat-Tests für zwei Zeilen mit drei Kategorien (df = 2)."""
    n_a, n_b = sum(a), sum(b)
    total = n_a + n_b
    if not n_a or not n_b:
        return 1.0
    stat = 0.0
    for i in range(3):
        col = a[i] + b[i]
        if not col:
            continue
        for row, n_row in ((a, n_a), (b, n_b)):
            expected = n_row * col / total
            stat += (row[i] - expected) ** 2 / expected
    return math.exp(-stat / 2.0)


def _draw(rng: random.Random, n: int, probs: Sequence[float]) -> list[int]:
    """Multinomiale Ziehung über zwei Binomialziehungen."""
    up = rng.binomialvariate(n, probs[0]) if probs[0] > 0 else 0
    rest = n - up
    p_down = probs[1] / (1.0 - probs[0]) if probs[0] < 1 else 0.0
    down = rng.binomialvariate(rest, min(max(p_down, 0.0), 1.0)) if rest and p_down > 0 else 0
    return [up, down, n - up - down]


def baseline(sideways: float) -> tuple[float, float, float]:
    """Symmetrische Grundverteilung: Rest zu gleichen Teilen auf- und abwärts."""
    move = (1.0 - sideways) / 2.0
    return (move, move, sideways)


def shifted(base: Sequence[float], effect: str, delta: float) -> tuple[float, float, float]:
    """Verteilung der Positivfenster.

    DIRECTIONAL: delta mehr Aufwärts, delta weniger Abwärts (Richtungssignal).
    VOLATILITY: delta weniger Seitwärts, je zur Hälfte auf- und abwärts (Bewegungssignal).
    """
    up, down, side = base
    if effect == "DIRECTIONAL":
        delta = min(delta, down)
        return (up + delta, down - delta, side)
    if effect == "VOLATILITY":
        delta = min(delta, side)
        return (up + delta / 2, down + delta / 2, side - delta)
    raise ValueError(f"unknown effect {effect}")


def power(
    *, n_pos: int, n_neg: int, base: Sequence[float], effect: str, delta: float,
    alpha: float, reps: int, rng: random.Random,
) -> float:
    pos_probs = shifted(base, effect, delta)
    hits = 0
    for _ in range(reps):
        if chi2_2x3_pvalue(_draw(rng, n_pos, pos_probs), _draw(rng, n_neg, base)) < alpha:
            hits += 1
    return hits / reps


def false_positive_rate(*, n_pos: int, n_neg: int, base: Sequence[float], alpha: float, reps: int, rng: random.Random) -> float:
    return power(n_pos=n_pos, n_neg=n_neg, base=base, effect="DIRECTIONAL", delta=0.0, alpha=alpha, reps=reps, rng=rng)


def minimum_detectable_effect(
    *, n_pos: int, n_neg: int, base: Sequence[float], effect: str, alpha: float,
    target: float, reps: int, rng: random.Random, step: float = 0.01, limit: float = 0.40,
) -> float | None:
    """Kleinster Effekt (als Anteil, 0.05 = 5 Prozentpunkte), der mit Power >= target erkannt wird.

    Binäre Suche auf dem Raster step..limit; die Power steigt mit dem Effekt.
    """
    steps = round(limit / step)

    def ok(i: int) -> bool:
        delta = i * step
        return power(n_pos=n_pos, n_neg=n_neg, base=base, effect=effect, delta=delta, alpha=alpha, reps=reps, rng=rng) >= target

    if not ok(steps):
        return None
    lo, hi = 0, steps  # ok(hi) gilt, ok(lo) gilt nicht (Effekt 0)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return round(hi * step, 4)


def run(
    *,
    kinds: int = 5,
    horizons: int = 3,
    n_pos: int = 1200,
    n_neg_values: Sequence[int] = (30, 100, 300, 500, 850),
    sideways_values: Sequence[float] = (0.2, 0.45, 0.7),
    effects: Sequence[str] = ("DIRECTIONAL", "VOLATILITY"),
    target_power: float = 0.8,
    reps: int = 1000,
    seed: int = SEED,
) -> dict[str, Any]:
    """Simuliert die kleinste erkennbare Wirkung pro Stichprobengröße der Negativklasse."""
    alpha_family = 0.05
    alpha = alpha_family / (kinds * horizons)
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for sideways in sideways_values:
        base = baseline(sideways)
        for n_neg in n_neg_values:
            fpr = false_positive_rate(n_pos=n_pos, n_neg=n_neg, base=base, alpha=alpha, reps=reps, rng=rng)
            for effect in effects:
                mde = minimum_detectable_effect(
                    n_pos=n_pos, n_neg=n_neg, base=base, effect=effect, alpha=alpha,
                    target=target_power, reps=reps, rng=rng,
                )
                rows.append({
                    "sideways_share": sideways, "n_neg": n_neg, "effect": effect,
                    "minimum_detectable_effect": mde, "false_positive_rate_at_zero_effect": fpr,
                })
    return {
        "study_id": "V2_SK_CONTROL_REGIME_V1",
        "simulation": "S2_POWER",
        "test": "chi-square 2x3 POSITIVE vs NEGATIVE, df=2",
        "alpha_family": alpha_family,
        "alpha_per_test_bonferroni": alpha,
        "tests_in_family": kinds * horizons,
        "target_power": target_power,
        "n_pos": n_pos,
        "reps_per_point": reps,
        "seed": seed,
        "market_data_read": False,
        "effects": {
            "DIRECTIONAL": "positives: +delta PRICE_INCREASED, -delta PRICE_DECREASED",
            "VOLATILITY": "positives: -delta PRICE_SIDEWAYS, split evenly to up and down",
        },
        "rows": rows,
    }
