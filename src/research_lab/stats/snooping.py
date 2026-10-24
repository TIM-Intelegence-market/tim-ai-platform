"""Data-snooping check across many variants: Hansen's SPA and Romano-Wolf's StepM.

Additional evaluation only (PROTOKOLL change log 2026-10-23): it never changes a
verdict. The question it answers is "does the best of the k variants beat doing
nothing (0 R per day), or is it only the luckiest one?" while keeping the
dependence between the variants and between days. Holm (7.2) treats the
variants as independent; these tests resample all variants on the same days.

Built from the papers, in plain Python like the rest of the lab:
- Politis, D. N. and Romano, J. P. (1994). The stationary bootstrap. JASA 89.
- Hansen, P. R. (2005). A test for superior predictive ability. JBES 23.
- Romano, J. P. and Wolf, M. (2005). Stepwise multiple testing as formalized
  data snooping. Econometrica 73. The step-down uses SPA's consistent
  re-centring, i.e. the Step-SPA of Hsu, Hsu and Kuan (2010), as arch does.

``studentize=False`` reproduces ``arch.bootstrap.SPA``/``StepM`` (arch 8.0.0,
non-nested); the default ``studentize=True`` is Hansen's studentized statistic,
which keeps a volatile variant from dominating the maximum.
"""
from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from src.research_lab.backtest.engine import Trade

DAY_MS = 86_400_000
BLOCK_DAYS = 10.0  # fixed before the first run on lab data (change log 2026-10-23)
REPS = 10_000
MIN_DAYS = 30
NOTE = "Zusatzauswertung, keine Regel: ändert kein Urteil (PROTOKOLL, Änderungsprotokoll 2026-10-23)"
_KAPPA_FLOOR = 1e-14


def daily_r(trades: Sequence[Trade], start_ms: int, end_ms: int) -> list[float]:
    """Net R per UTC day in [start_ms, end_ms).

    A trade belongs to the period in which its signal fired (as in the runner)
    and is booked on the day it closed; a close after the period end is booked
    on the last day. Days without a closed trade are 0 R.
    """
    first = start_ms // DAY_MS
    days = (end_ms - 1) // DAY_MS - first + 1
    if days < 1:
        raise ValueError("empty period")
    series = [0.0] * days
    for trade in trades:
        if start_ms <= trade.signal_time < end_ms:
            day = min(max(trade.exit_time // DAY_MS - first, 0), days - 1)
            series[day] += trade.r
    return series


def stationary_blocks(n: int, block_size: float, reps: int, seed: int) -> list[list[tuple[int, int]]]:
    """Stationary bootstrap draws as blocks (start, length) with circular wrap.

    Each block starts at a uniform index and continues with probability
    1 - 1/block_size, so block lengths are geometric with mean block_size.
    """
    if n < 1 or reps < 1:
        raise ValueError("need n >= 1 and reps >= 1")
    if block_size < 1:
        raise ValueError("block_size must be >= 1")
    p = 1.0 / block_size
    log_q = math.log1p(-p) if p < 1 else None
    rng = random.Random(seed)
    draws = []
    for _ in range(reps):
        blocks, filled = [], 0
        while filled < n:
            length = 1 if log_q is None else 1 + int(math.log(1.0 - rng.random()) / log_q)
            length = min(length, n - filled)
            blocks.append((rng.randrange(n), length))
            filled += length
        draws.append(blocks)
    return draws


def _prefix(series: Sequence[float]) -> list[float]:
    total, out = 0.0, [0.0]
    for value in list(series) + list(series):
        total += value
        out.append(total)
    return out


def bootstrap_means(series: Sequence[float], draws: Sequence[Sequence[tuple[int, int]]]) -> list[float]:
    prefix, n = _prefix(series), len(series)
    return [sum(prefix[s + length] - prefix[s] for s, length in blocks) / n for blocks in draws]


def long_run_variance(series: Sequence[float], block_size: float) -> float:
    """Variance of sqrt(n) * mean under the stationary bootstrap (Politis-Romano kernel).

    Same estimator as arch's non-nested SPA. Lags whose kernel weight is below
    1e-14 are skipped; they change the result by less than rounding.
    """
    n = len(series)
    mean = math.fsum(series) / n
    x = [v - mean for v in series]
    q = 1.0 - 1.0 / block_size
    variance = math.fsum(v * v for v in x) / n
    for lag in range(1, n):
        kappa = (1.0 - lag / n) * q ** lag + (lag / n) * q ** (n - lag)
        if kappa < _KAPPA_FLOOR:
            continue
        variance += 2.0 * kappa * math.fsum(a * b for a, b in zip(x, x[lag:])) / n
    return variance


def _percentile(values: Sequence[float], share: float) -> float:
    """Linear-interpolation percentile (numpy's default), share in [0, 1]."""
    ordered = sorted(values)
    position = share * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True, slots=True)
class SnoopingResult:
    variants: tuple[str, ...]
    days: int
    block_size: float
    reps: int
    seed: int
    studentize: bool
    pvalues: dict[str, float]  # lower, consistent, upper (Hansen 2005)
    superior: tuple[str, ...]  # StepM at alpha, consistent re-centring
    alpha: float
    best: str
    best_mean_r: float

    def as_dict(self) -> dict:
        return {
            "note": NOTE, "variants": len(self.variants), "days": self.days, "block_days": self.block_size,
            "reps": self.reps, "seed": self.seed, "studentized": self.studentize, "benchmark": "0 R pro Tag",
            "spa_p": self.pvalues, "stepm_alpha": self.alpha, "stepm_superior": list(self.superior),
            "best": self.best, "best_mean_r_per_day": self.best_mean_r,
        }


class _Prepared:
    """Statistics and bootstrap values shared by SPA and StepM."""

    def __init__(self, series: Mapping[str, Sequence[float]], block_size: float, reps: int, seed: int, studentize: bool):
        if not series:
            raise ValueError("no variants")
        lengths = {len(v) for v in series.values()}
        if len(lengths) != 1:
            raise ValueError("all variants need the same days")
        self.n = lengths.pop()
        if self.n < 3:
            raise ValueError("need at least 3 days")
        self.names = tuple(sorted(series))
        n = self.n
        self.means = [math.fsum(series[k]) / n for k in self.names]
        variances = [long_run_variance(series[k], block_size) for k in self.names]
        threshold = [-math.sqrt(max(v, 0.0) / n * 2.0 * math.log(math.log(n))) for v in variances]
        valid = [m >= t for m, t in zip(self.means, threshold)]
        # Scale per variant: 1 (raw means, as arch) or sqrt(n) / omega (Hansen).
        self.scale = [
            (math.sqrt(n / v) if v > 0 else 0.0) if studentize else 1.0 for v in variances
        ]
        self.observed = [m * s for m, s in zip(self.means, self.scale)]
        centres = {
            "lower": [max(m, 0.0) for m in self.means],
            "consistent": [m if ok else 0.0 for m, ok in zip(self.means, valid)],
            "upper": list(self.means),
        }
        draws = stationary_blocks(n, block_size, reps, seed)
        boot = [bootstrap_means(series[k], draws) for k in self.names]
        # sim[kind][k][b]: re-centred, scaled bootstrap statistic of variant k in draw b.
        self.sim = {
            kind: [[(value - c) * s for value in column] for column, c, s in zip(boot, centre, self.scale)]
            for kind, centre in centres.items()
        }
        self.reps = reps
        self.studentize = studentize

    def max_over(self, kind: str, active: Sequence[int]) -> list[float]:
        columns = [self.sim[kind][k] for k in active]
        floor = 0.0 if self.studentize else -math.inf
        return [max(floor, *(column[b] for column in columns)) for b in range(self.reps)]


def _pvalues(prep: _Prepared, active: Sequence[int]) -> dict[str, float]:
    stat = max(prep.observed[k] for k in active)
    if prep.studentize and stat <= 0:
        # No variant is above the benchmark: no evidence against the null. (Counting
        # draws above a floored 0 would give p near 0 when every variant loses.)
        return {"lower": 1.0, "consistent": 1.0, "upper": 1.0}
    return {kind: sum(v > stat for v in prep.max_over(kind, active)) / prep.reps for kind in ("lower", "consistent", "upper")}


def _stepm(prep: _Prepared, alpha: float, kind: str) -> list[int]:
    remaining = list(range(len(prep.names)))
    superior: list[int] = []
    while remaining:
        critical = _percentile(prep.max_over(kind, remaining), 1.0 - alpha)
        found = [k for k in remaining if prep.observed[k] > critical]
        if not found:
            break
        superior.extend(found)
        remaining = [k for k in remaining if k not in found]
    return sorted(superior)


def snooping_test(series: Mapping[str, Sequence[float]], *, block_size: float = BLOCK_DAYS, reps: int = REPS,
                  seed: int, alpha: float = 0.05, studentize: bool = True) -> SnoopingResult:
    """SPA p-values (null: no variant beats 0 R per day) and the StepM superior set."""
    prep = _Prepared(series, block_size, reps, seed, studentize)
    everyone = list(range(len(prep.names)))
    best = max(everyone, key=lambda k: (prep.observed[k], prep.means[k], prep.names[k]))  # the variant SPA tests
    return SnoopingResult(
        variants=prep.names, days=prep.n, block_size=block_size, reps=reps, seed=seed, studentize=studentize,
        pvalues=_pvalues(prep, everyone), superior=tuple(prep.names[k] for k in _stepm(prep, alpha, "consistent")),
        alpha=alpha, best=prep.names[best], best_mean_r=prep.means[best],
    )


def period_report(trades: Mapping[str, Sequence[Trade]], start_ms: int, end_ms: int, *, seed: int,
                  reps: int = REPS, block_size: float = BLOCK_DAYS, alpha: float = 0.05) -> dict | None:
    """Report block for one period, or None when it is shorter than MIN_DAYS."""
    if not trades or (end_ms - start_ms) // DAY_MS < MIN_DAYS:
        return None
    series = {name: daily_r(items, start_ms, end_ms) for name, items in trades.items()}
    result = snooping_test(series, block_size=block_size, reps=reps, seed=seed, alpha=alpha)
    out = result.as_dict()
    out["start"] = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).date().isoformat()
    out["end"] = datetime.fromtimestamp((end_ms - 1) / 1000, tz=timezone.utc).date().isoformat()  # last day
    return out
