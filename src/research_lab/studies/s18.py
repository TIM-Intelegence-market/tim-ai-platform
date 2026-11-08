"""Study S18: Kronos path fan for BTC, 24 hours ahead, against simple bands (forecast study, no trades).

Preregistration: docs/research_lab/studien/S18_KRONOS_PFADFAECHER_KALIBRIERUNG_PRAEREGISTRIERUNG_ENTWURF.md.
Pure Python (stdlib). The Kronos model itself runs outside this module (scripts/research_lab_s18.py
`forecast`, in its own environment); here are the schedule, the two baselines, the scores, the gate
and the verdict.

Forward study: forecasts are written before their target exists (append-only log). Outcomes and both
baselines are computed at evaluation time from 1h klines that closed before the forecast time, so the
log only ever holds what Kronos said.

Unit: the 24-hour log return in percent, y = 100 * ln(close(t0 + 24h) / close(t0)), where close(t0) is
the close of the last 1h candle that closed at t0.
"""
from __future__ import annotations

import bisect
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

HOUR_MS = 60 * 60 * 1000
STEP_MS = 4 * HOUR_MS          # one forecast every 4 hours, aligned to 00/04/.../20 UTC
HORIZON_H = 24
CONTEXT_H = 512                 # Kronos-small max context
N_PATHS = 100
TEMPERATURE = 1.0
TOP_P = 0.9
TOP_K = 0
SEED = 0

EWMA_LAMBDA = 0.94
EWMA_START_H = 14 * 24          # EWMA starts from the mean r^2 of the first 14 days of its window
EWMA_WINDOW_H = 30 * 24 + 24    # hourly candles B1 uses before t0
HIST_DAYS = 30
HIST_N = HIST_DAYS * 24 // 4    # 180 overlapping 24h returns, 4h apart
HIST_WINDOW_H = HIST_DAYS * 24 + HORIZON_H
LOOKBACK_H = max(CONTEXT_H, EWMA_WINDOW_H, HIST_WINDOW_H) + 1  # candles needed before t0

PRIMARY = "BTCUSDT"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

GATE_MIN_FORECASTS = 500
DM_MIN_LAG = 6                  # 24h windows overlap every 4h
ALPHA = 0.05
COVERAGE_BOUNDS = {0.80: (0.72, 0.88), 0.95: (0.90, 0.99)}
DESCRIPTIVE_LEVELS = (0.50, 0.80, 0.95)

# Pins (section 4.1). Changing any of them is a new study version.
KRONOS_COMMIT = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
MODEL_REPO = "NeoQuasar/Kronos-small"
MODEL_REVISION = "901c26c1332695a2a8f243eb2f37243a37bea320"
MODEL_SHA256 = "b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020"
TOKENIZER_REPO = "NeoQuasar/Kronos-Tokenizer-base"
TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"
TOKENIZER_SHA256 = "59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee"

# First forecast time of the forward part: first full UTC day after freezing 1.0.
FORWARD_START_MS = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp() * 1000)
# Forward window ends after at most 180 days.
FORWARD_MAX_DAYS = 180
# Late start tolerance: a forecast written later than this after t0 does not count (no backfill).
MAX_LATE_MS = 2 * HOUR_MS


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: int   # ms, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float    # quote volume

    @property
    def close_time(self) -> int:
        return self.open_time + HOUR_MS


def forecast_times(start_ms: int, end_ms: int) -> list[int]:
    """All forecast times t0 in [start, end), on the 4h UTC grid."""
    first = -(-start_ms // STEP_MS) * STEP_MS
    return list(range(first, end_ms, STEP_MS))


def slot_of(now_ms: int) -> int:
    return now_ms // STEP_MS * STEP_MS


def is_forward_time(t0: int) -> bool:
    return FORWARD_START_MS <= t0 < FORWARD_START_MS + FORWARD_MAX_DAYS * 24 * HOUR_MS and t0 % STEP_MS == 0


def history_before(candles: Sequence[Candle], t0: int, n: int) -> list[Candle] | None:
    """The last n candles closed at or before t0, or None if any is missing (gap rule, section 3)."""
    opens = [c.open_time for c in candles]
    end = bisect.bisect_left(opens, t0)  # candles with open_time < t0 close at or before t0
    if end < n:
        return None
    out = list(candles[end - n:end])
    if out[-1].open_time != t0 - HOUR_MS:
        return None
    for a, b in zip(out, out[1:]):
        if b.open_time - a.open_time != HOUR_MS:
            return None
    return out


def outcome(candles: Sequence[Candle], t0: int) -> float | None:
    """y = 100 * ln(close at t0+24h / close at t0); None if a candle in between is missing."""
    hist = history_before(candles, t0, 1)
    future = history_before(candles, t0 + HORIZON_H * HOUR_MS, HORIZON_H)
    if hist is None or future is None:
        return None
    return 100 * math.log(future[-1].close / hist[-1].close)


def log_returns(closes: Sequence[float]) -> list[float]:
    return [100 * math.log(b / a) for a, b in zip(closes, closes[1:])]


def ewma_sigma_24h(hist: Sequence[Candle]) -> float:
    """B1: sigma of the 24h return in percent, sqrt(24 * h) with EWMA lambda 0.94 on hourly returns."""
    r = log_returns([c.close for c in hist[-EWMA_WINDOW_H - 1:]])
    h = statistics.fmean(x * x for x in r[:EWMA_START_H])
    for x in r[EWMA_START_H:]:
        h = EWMA_LAMBDA * h + (1 - EWMA_LAMBDA) * x * x
    return math.sqrt(HORIZON_H * h)


def historical_returns(hist: Sequence[Candle]) -> list[float]:
    """B2: the last 180 overlapping 24h log returns (percent), 4h apart, ending at t0."""
    closes = [c.close for c in hist]
    out = []
    for k in range(HIST_N):
        end = len(closes) - 1 - 4 * k
        start = end - HORIZON_H
        out.append(100 * math.log(closes[end] / closes[start]))
    return out


# --- scores -----------------------------------------------------------------------------------

def crps_samples(samples: Sequence[float], y: float) -> float:
    """CRPS of the empirical distribution: E|X - y| - 0.5 E|X - X'| (exact, O(n log n))."""
    xs = sorted(samples)
    n = len(xs)
    first = sum(abs(x - y) for x in xs) / n
    # sum_{i,j} |x_i - x_j| = 2 * sum_i (2i - n + 1) x_i for sorted x (0-based)
    pair = 2 * sum((2 * i - n + 1) * x for i, x in enumerate(xs)) / (n * n)
    return first - 0.5 * pair


def _phi(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _Phi(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2))


def crps_normal(sigma: float, y: float, mu: float = 0.0) -> float:
    """Closed form CRPS of N(mu, sigma^2) (Gneiting and Raftery 2007)."""
    z = (y - mu) / sigma
    return sigma * (z * (2 * _Phi(z) - 1) + 2 * _phi(z) - 1 / math.sqrt(math.pi))


def quantile(samples: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics (numpy default)."""
    xs = sorted(samples)
    pos = q * (len(xs) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def inside_samples(samples: Sequence[float], y: float, level: float) -> bool:
    a = (1 - level) / 2
    return quantile(samples, a) <= y <= quantile(samples, 1 - a)


def _normal_ppf(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _Phi(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def inside_normal(sigma: float, y: float, level: float) -> bool:
    z = _normal_ppf(1 - (1 - level) / 2)
    return -z * sigma <= y <= z * sigma


def dm_lag(n: int) -> int:
    return max(DM_MIN_LAG, math.floor(4 * (n / 100) ** (2 / 9)))


def diebold_mariano(d: Sequence[float]) -> dict:
    """Mean of d, Newey-West t with lag max(6, rule) and one-sided p for H1: mean d > 0."""
    n = len(d)
    if n < 2:
        return {"n": n, "mean": statistics.fmean(d) if d else 0.0, "t": 0.0, "p_one_sided": 1.0, "lag": 0}
    m = statistics.fmean(d)
    e = [x - m for x in d]
    lag = min(dm_lag(n), n - 1)
    var = sum(x * x for x in e) / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        var += 2 * w * sum(e[i] * e[i - k] for i in range(k, n)) / n
    t = m / math.sqrt(var / n) if var > 0 else 0.0
    return {"n": n, "mean": m, "t": t, "p_one_sided": 0.5 * math.erfc(t / math.sqrt(2)), "lag": lag}


# --- evaluation ---------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Scored:
    t0: int
    y: float
    crps_k: float
    crps_b1: float
    crps_b2: float
    inside_k: Mapping[float, bool]
    inside_b1: Mapping[float, bool]
    inside_b2: Mapping[float, bool]


def valid_record(rec: Mapping) -> bool:
    """A logged forecast counts only if it is a forward time, on time, pinned and complete."""
    try:
        t0 = int(rec["t0_ms"])
        paths = rec["kronos_final_logret"]
    except (KeyError, TypeError, ValueError):
        return False
    return (is_forward_time(t0)
            and int(rec.get("written_ms", 1 << 62)) - t0 <= MAX_LATE_MS
            and rec.get("model_sha256") == MODEL_SHA256
            and rec.get("tokenizer_sha256") == TOKENIZER_SHA256
            and rec.get("kronos_commit") == KRONOS_COMMIT
            and len(paths) == N_PATHS
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in paths))


def score(rec: Mapping, candles: Sequence[Candle]) -> Scored | None:
    """Scores one logged forecast; None if the outcome or baseline history is incomplete."""
    t0 = int(rec["t0_ms"])
    y = outcome(candles, t0)
    hist = history_before(candles, t0, LOOKBACK_H)
    if y is None or hist is None:
        return None
    if abs(hist[-1].close - float(rec["close0"])) > 1e-6 * hist[-1].close:
        return None  # log was written from different data than the evaluation sees
    k = [float(x) for x in rec["kronos_final_logret"]]
    sigma = ewma_sigma_24h(hist)
    h2 = historical_returns(hist)
    levels = DESCRIPTIVE_LEVELS
    return Scored(t0, y, crps_samples(k, y), crps_normal(sigma, y), crps_samples(h2, y),
                  {lv: inside_samples(k, y, lv) for lv in levels},
                  {lv: inside_normal(sigma, y, lv) for lv in levels},
                  {lv: inside_samples(h2, y, lv) for lv in levels})


def gate(n_scored: int) -> bool:
    return n_scored >= GATE_MIN_FORECASTS


def verdict(scored: Sequence[Scored]) -> dict:
    """Section 5 for the primary symbol. Refuses to compute any score below the gate."""
    s = sorted(scored, key=lambda x: x.t0)
    if not gate(len(s)):
        return {"n": len(s), "gate": False, "verdict": "KEIN URTEIL (Gate nicht erreicht)"}
    d1 = [x.crps_b1 - x.crps_k for x in s]
    d2 = [x.crps_b2 - x.crps_k for x in s]
    dm1, dm2 = diebold_mariano(d1), diebold_mariano(d2)
    half = len(s) // 2
    halves = [statistics.fmean(d1[:half]), statistics.fmean(d1[half:])]
    cov = {lv: statistics.fmean(1.0 if x.inside_k[lv] else 0.0 for x in s) for lv in COVERAGE_BOUNDS}
    crit = {
        "1_gate": True,
        "2_vs_b1": dm1["mean"] > 0 and dm1["p_one_sided"] < ALPHA,
        "3_vs_b2": statistics.fmean(x.crps_k for x in s) < statistics.fmean(x.crps_b2 for x in s),
        "4_calibrated": all(lo <= cov[lv] <= hi for lv, (lo, hi) in COVERAGE_BOUNDS.items()),
        "5_halves": all(h > 0 for h in halves),
    }
    if all(crit.values()):
        text = "BESTANDEN"
    elif not crit["4_calibrated"]:
        text = "NICHT BESTANDEN (nicht kalibriert)"
    else:
        text = "NICHT BESTANDEN"
    return {"n": len(s), "gate": True, "dm_vs_b1": dm1, "dm_vs_b2": dm2, "halves_mean_d_b1": halves,
            "coverage_k": cov, "criteria": crit, "verdict": text}


def describe(scored: Sequence[Scored]) -> dict:
    """Section 5.2, no verdict: coverage per level and model, mean CRPS."""
    if not scored:
        return {"n": 0}
    out: dict = {"n": len(scored), "mean_crps": {
        "kronos": statistics.fmean(x.crps_k for x in scored),
        "b1_ewma": statistics.fmean(x.crps_b1 for x in scored),
        "b2_hist": statistics.fmean(x.crps_b2 for x in scored)}, "coverage": {}}
    for name, attr in (("kronos", "inside_k"), ("b1_ewma", "inside_b1"), ("b2_hist", "inside_b2")):
        out["coverage"][name] = {str(lv): statistics.fmean(1.0 if getattr(x, attr)[lv] else 0.0 for x in scored)
                                 for lv in DESCRIPTIVE_LEVELS}
    return out
