"""Study S15: GARCH(1,1) volatility forecast against the simple rolling 14-day variance (forecast study, no trades).

Preregistration: docs/research_lab/studien/S15_GARCH_VOLATILITAET_PRAEREGISTRIERUNG.md. Pure Python (stdlib).

Per instrument and horizon (4h, 1d) the 5m bars are grouped into complete periods. For every period t the
three models forecast the variance of period t using only periods before t:
- B1 rolling: mean of r^2 over the previous 14 days of periods (84 periods at 4h, 14 at 1d);
- B2 EWMA (RiskMetrics, lambda 0.94), descriptive only;
- G GARCH(1,1), Gaussian QMLE on all periods before the last refit point (expanding window,
  refit every 30 days), recursion run over all periods before t.
Target: realized variance RV_t = sum of squared 5m log returns inside period t. Loss: QLIKE
(Patton 2011), MSE descriptive. Test: Diebold-Mariano with Newey-West variance on the loss
difference B1 - G, pooled as the cross-sectional mean per period start.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from src.research_lab.data.parse import Kline

FIVE_MIN_MS = 5 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
SCALE = 100.0  # returns in percent for the optimizer
EWMA_LAMBDA = 0.94
ROLLING_DAYS = 14
REFIT_DAYS = 30
BURN_IN_DAYS = 365
MAX_PERSISTENCE = 0.9999


@dataclass(frozen=True, slots=True)
class Horizon:
    variant_id: str
    minutes: int

    @property
    def period_ms(self) -> int:
        return self.minutes * 60 * 1000

    @property
    def per_day(self) -> int:
        return 1440 // self.minutes

    @property
    def bars(self) -> int:
        return self.minutes // 5


S15_VARIANTS = (Horizon("S15-4h", 240), Horizon("S15-1d", 1440))


@dataclass(frozen=True, slots=True)
class Period:
    start: int  # UTC ms
    ret: float  # ln(close / open) of the period, in percent
    rv: float  # sum of squared 5m log returns inside the period, percent^2


def periods(bars: Sequence[Kline], horizon: Horizon) -> list[Period]:
    """Complete periods only: all 5m bars present and contiguous; UTC-aligned starts."""
    out: list[Period] = []
    i, n, p = 0, len(bars), horizon.period_ms
    while i < n:
        start = bars[i].open_time - bars[i].open_time % p
        j = i
        while j < n and bars[j].open_time < start + p:
            j += 1
        group = bars[i:j]
        i = j
        if len(group) != horizon.bars or any(b.open_time != start + k * FIVE_MIN_MS for k, b in enumerate(group)):
            continue
        if any(b.open <= 0 or b.close <= 0 for b in group):
            continue
        rets = [math.log(group[0].close / group[0].open)]
        rets += [math.log(group[k].close / group[k - 1].close) for k in range(1, len(group))]
        out.append(Period(start, SCALE * math.log(group[-1].close / group[0].open), sum((SCALE * r) ** 2 for r in rets)))
    return out


# ---------------------------------------------------------------- GARCH(1,1)


@dataclass(frozen=True, slots=True)
class Garch:
    omega: float
    alpha: float
    beta: float

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    @property
    def unconditional(self) -> float:
        return self.omega / (1 - self.persistence)

    @property
    def half_life(self) -> float:
        p = self.persistence
        return math.log(0.5) / math.log(p) if 0 < p < 1 else math.inf


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x)) if x > -700 else 0.0


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _unpack(x: Sequence[float]) -> Garch:
    persistence = MAX_PERSISTENCE * _sigmoid(x[1])
    share = _sigmoid(x[2])
    return Garch(math.exp(max(min(x[0], 50.0), -50.0)), persistence * share, persistence * (1 - share))


def _pack(g: Garch) -> list[float]:
    p = g.alpha + g.beta
    return [math.log(g.omega), _logit(p / MAX_PERSISTENCE), _logit(g.alpha / p if p > 0 else 0.5)]


def neg_loglik(g: Garch, returns: Sequence[float], h0: float) -> float:
    """Gaussian quasi log-likelihood (constants dropped), first variance h0."""
    h, total = h0, 0.0
    for k, r in enumerate(returns):
        if k:
            h = g.omega + g.alpha * returns[k - 1] ** 2 + g.beta * h
        if h <= 0 or not math.isfinite(h):
            return math.inf
        total += math.log(h) + r * r / h
    return total


def nelder_mead(f: Callable[[list[float]], float], x0: Sequence[float], step: float = 0.5,
                max_evals: int = 400, tol: float = 1e-7) -> list[float]:
    """Deterministic Nelder-Mead minimizer (standard coefficients)."""
    dim = len(x0)
    simplex = [list(x0)] + [[x0[j] + (step if j == i else 0.0) for j in range(dim)] for i in range(dim)]
    values = [f(x) for x in simplex]
    evals = len(simplex)
    while evals < max_evals:
        order = sorted(range(dim + 1), key=lambda i: values[i])
        simplex = [simplex[i] for i in order]
        values = [values[i] for i in order]
        if abs(values[-1] - values[0]) <= tol * (abs(values[0]) + tol):
            break
        centroid = [sum(simplex[i][j] for i in range(dim)) / dim for j in range(dim)]
        worst = simplex[-1]
        reflected = [c + (c - w) for c, w in zip(centroid, worst)]
        fr = f(reflected)
        evals += 1
        if fr < values[0]:
            expanded = [c + 2 * (c - w) for c, w in zip(centroid, worst)]
            fe = f(expanded)
            evals += 1
            simplex[-1], values[-1] = (expanded, fe) if fe < fr else (reflected, fr)
        elif fr < values[-2]:
            simplex[-1], values[-1] = reflected, fr
        else:
            contracted = [c + 0.5 * (w - c) for c, w in zip(centroid, worst)]
            fc = f(contracted)
            evals += 1
            if fc < values[-1]:
                simplex[-1], values[-1] = contracted, fc
            else:
                best = simplex[0]
                simplex = [best] + [[b + 0.5 * (x - b) for b, x in zip(best, s)] for s in simplex[1:]]
                values = [values[0]] + [f(s) for s in simplex[1:]]
                evals += dim
    return simplex[min(range(dim + 1), key=lambda i: values[i])]


def fit_garch(returns: Sequence[float], start: Garch | None = None) -> Garch:
    """QMLE fit; the first variance is the sample mean of r^2 of the fit data (zero-mean returns)."""
    h0 = statistics.fmean(r * r for r in returns)
    x0 = _pack(start) if start else _pack(Garch(0.05 * h0, 0.10, 0.85))
    best = nelder_mead(lambda x: neg_loglik(_unpack(x), returns, h0), x0)
    return _unpack(best)


# ---------------------------------------------------------------- forecasts


@dataclass(frozen=True, slots=True)
class Forecast:
    start: int
    rv: float
    rolling: float
    ewma: float
    garch: float


def forecasts(series: Sequence[Period], horizon: Horizon, start_ms: int, end_ms: int,
              refits: list | None = None) -> list[Forecast]:
    """One-step forecasts for every period with start in [start_ms, end_ms), using only earlier periods.

    The series is the list of complete periods in time order; a missing period is skipped (the
    recursion runs over the available periods). Evaluation begins only after the burn-in of
    ``BURN_IN_DAYS`` of periods. ``refits`` (optional) collects (time, Garch) of every refit."""
    burn = BURN_IN_DAYS * horizon.per_day
    window = ROLLING_DAYS * horizon.per_day
    refit_every = REFIT_DAYS * horizon.per_day
    out: list[Forecast] = []
    if len(series) <= burn:
        return out
    rets = [p.ret for p in series]
    ewma = [0.0] * len(series)  # ewma[t]: forecast for period t from periods before t
    ewma[window] = statistics.fmean(r * r for r in rets[:window])
    for k in range(window + 1, len(series)):
        ewma[k] = EWMA_LAMBDA * ewma[k - 1] + (1 - EWMA_LAMBDA) * rets[k - 1] ** 2
    model: Garch | None = None
    fitted_at = -1
    h, h_index, h0 = 0.0, 0, 0.0
    for t in range(burn, len(series)):
        if model is None or t - fitted_at >= refit_every:
            model = fit_garch(rets[:t], model)
            fitted_at = t
            if refits is not None:
                refits.append((series[t].start, model))
            h0 = statistics.fmean(r * r for r in rets[:t])
            h, h_index = h0, 0  # restart the recursion with the new parameters
        while h_index < t:
            h = model.omega + model.alpha * rets[h_index] ** 2 + model.beta * h
            h_index += 1
        p = series[t]
        if start_ms <= p.start < end_ms:
            rolling = statistics.fmean(r * r for r in rets[t - window:t])
            out.append(Forecast(p.start, p.rv, rolling, ewma[t], h))
    return out


# ---------------------------------------------------------------- losses and test


def qlike(rv: float, h: float) -> float:
    q = rv / h
    return q - math.log(q) - 1


def mse(rv: float, h: float) -> float:
    return (rv - h) ** 2


def newey_west_lag(n: int) -> int:
    return max(1, math.floor(4 * (n / 100) ** (2 / 9)))


def diebold_mariano(d: Sequence[float]) -> dict:
    """Mean of d, Newey-West t value and one-sided p (H1: mean d > 0) from the normal distribution."""
    n = len(d)
    if n < 2:
        return {"n": n, "mean": statistics.fmean(d) if d else 0.0, "t": 0.0, "p_one_sided": 1.0, "lag": 0}
    m = statistics.fmean(d)
    e = [x - m for x in d]
    lag = newey_west_lag(n)
    var = sum(x * x for x in e) / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        var += 2 * w * sum(e[i] * e[i - k] for i in range(k, n)) / n
    t = m / math.sqrt(var / n) if var > 0 else 0.0
    return {"n": n, "mean": m, "t": t, "p_one_sided": 0.5 * math.erfc(t / math.sqrt(2)), "lag": lag}


def usable(f: Forecast) -> bool:
    return f.rv > 0 and f.rolling > 0 and f.ewma > 0 and f.garch > 0


def pooled_differences(by_symbol: Mapping[str, Sequence[Forecast]], benchmark: str = "rolling",
                       loss: Callable[[float, float], float] = qlike) -> list[float]:
    """Cross-sectional mean of loss(benchmark) - loss(garch) per period start, in time order."""
    acc: dict[int, list[float]] = {}
    for fs in by_symbol.values():
        for f in fs:
            if usable(f):
                acc.setdefault(f.start, []).append(loss(f.rv, getattr(f, benchmark)) - loss(f.rv, f.garch))
    return [statistics.fmean(acc[k]) for k in sorted(acc)]


# ---------------------------------------------------------------- verdict (preregistration section 5)

GATE = {"train": 500, "validation": 250}
P_MAX = {"train": 0.10, "validation": 0.05}
MIN_SYMBOLS_BETTER = 2


def verdict(train: Mapping, validation: Mapping, validation_by_symbol: Mapping[str, float],
            validation_by_year: Mapping[str, float]) -> dict:
    """``train``/``validation``: diebold_mariano() of the pooled QLIKE difference rolling - garch.
    ``validation_by_symbol``/``validation_by_year``: mean difference per symbol / per calendar year."""
    checks = {
        "train_n": train["n"] >= GATE["train"],
        "train_better": train["mean"] > 0 and train["p_one_sided"] < P_MAX["train"],
        "validation_n": validation["n"] >= GATE["validation"],
        "validation_better": validation["mean"] > 0 and validation["p_one_sided"] < P_MAX["validation"],
        "symbols": sum(1 for v in validation_by_symbol.values() if v > 0) >= MIN_SYMBOLS_BETTER,
        "years": bool(validation_by_year) and all(v > 0 for v in validation_by_year.values()),
    }
    return {"checks": checks, "passed": all(checks.values())}
