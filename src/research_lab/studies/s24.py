"""S24: all indicators TIM has history for, as one feature table per 1h moment (BTCUSDT, 2020 to 2024).

Packages 1 and 2 of "TIM soll alle Indikatoren nutzen" (Uzi, 11.11.2026). Rules:
docs/research_lab/studien/S24_ALLE_INDIKATOREN_PRAEREGISTRIERUNG.md (version 1.0, frozen 2026-11-11). The holdout from 2025-01-01 is never
loaded.

    python -m src.research_lab.studies.s24 count  --root data/research_lab --out DIR [--fetch] [--workers N] [--footprint S8_ROOT --fp-cache DIR]
    python -m src.research_lab.studies.s24 export --root data/research_lab --out DIR [--fetch] [--workers N] [--footprint S8_ROOT --fp-cache DIR]
    python -m src.research_lab.studies.s24 evaluate --root data/research_lab --out DIR --workers N --footprint S8_ROOT --fp-cache DIR

Moments and trades are S22's, unchanged: every closed 1h candle with enough warm-up, a Long and a Short at the close,
stop 1 ATR14, target 2 ATR14, at most 48 h (``s22.moments``; the outcome here adds Bitunix costs and funding). Per moment and direction S24 records
every indicator family that can be rebuilt from history with only what was known at the close. Every value is
signed so that above 0 speaks for the trade's direction (funding: above 0 = this side already pays):

    C  Chart-Urteil chart-urteil/1.0, rules R1-R5 (live code, candles only; as S22)
    K  candle order flow over the last 10 hours: CVD share, CVD-price co-movement, volume trend (S21 family K)
    F  engine footprint flags I/A/C/T/H/E over the 8 quarter hours up to the close (S8 store, S21 family F)
    G  funding: last published rate and its z-score over 90 rates (USD-M archive, S21 family G)
    T  direction of day / week / month: last completed close against its mean (OFX filter, ofx.trend)
    V  distance of the close to the 24h VWAP and to the VWAP anchored at the week's start, in ATR

Live-only sources have no history and go into the live shadow only (``SHADOW_ONLY``). ``count`` and ``export`` are
results-blind: no outcome is computed or written. ``evaluate`` tests two models (M1 votes, nothing fitted; M2
logistic regression fitted once on the training) on the validation 2023-2024 and refuses to run on a draft.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import multiprocessing
import time
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.research_lab.bitunix.contract import FEE_TAKER
from src.research_lab.bitunix.leverage import SLIPPAGE, STOP_SLIPPAGE
from src.research_lab.data.parse import Kline
from src.research_lab.studies import s22
from src.research_lab.studies.s20 import DOWN, HOUR, UP, atr_series, week_of
from src.research_lab.studies.s21 import _correlation

VERSION = "1.0"  # frozen 2026-11-11 on Uzi's word ("ok"); a change needs a new version
SEED = 24
FAMILIES = ("C", "K", "F", "G", "T", "V")
FAMILY_NAMES = {"C": "Chart-Urteil R1-R5", "K": "Kerzen-Orderflow", "F": "Footprint-Orderflow", "G": "Funding",
                "T": "Richtung Tag/Woche/Monat", "V": "VWAP-Abstand"}
FEATURES = {
    "C": ("r1_value", "r2_struktur", "r3_stop", "r4_level", "r5_trendlinie"),
    "K": ("cvd_anteil", "cvd_gleichlauf", "volumentrend"),
    "F": ("fp_I", "fp_A", "fp_C", "fp_T", "fp_H", "fp_E"),
    "G": ("funding_letzt", "funding_z"),
    "T": ("trend_d", "trend_w", "trend_m"),
    "V": ("vwap_24h_atr", "vwap_woche_atr"),
}
SHADOW_ONLY = {
    "Orderbuch (Tiefe, Imbalance)": "nicht aufgezeichnet",
    "Liquidationen": "Sammler erst seit 02.11.2026",
    "Open Interest": "kein Monatsarchiv, nur live",
    "Gamma / Optionen": "nur live",
    "Kronos-Prognose": "eigene Studie S18",
    "Chart-Urteil R6-R8 (Absorption, Welle, Tages-CVD)": "braucht die Live-Orderflow-Lage",
    "Bitunix-Trades": "Recorder seit 11.11.2026",
}
FLOW_WINDOW = 10  # hours, S21 family K (the window S20 chose in its training data)
VWAP_HOURS = 24
MIN_TRADES = 300  # complete rows per direction and section before a model may be tested
MIN_WEEKS = 50
WEEK_MS = 7 * 24 * HOUR
MONDAY_MS = 4 * 24 * HOUR  # 1970-01-01 was a Thursday; the first Monday 00:00 UTC is four days later


@dataclass(frozen=True, slots=True)
class Row:
    time: int  # close of the 1h candle = entry, UTC ms
    section: str
    direction: str
    features: dict[str, tuple[float, ...] | None]  # per family; None = not available at this moment
    net_r: float | None = None  # only in evaluate: net R after Bitunix costs and funding


def week_start(time_ms: int) -> int:
    """Monday 00:00 UTC of the week holding ``time_ms``."""
    return time_ms - (time_ms - MONDAY_MS) % WEEK_MS


# -- K: candle order flow ---------------------------------------------------------------------------


def candle_flow(bars: Sequence[Kline], i: int, sign: float, n: int = FLOW_WINDOW) -> tuple[float, float, float]:
    """S21 family K at the close of ``bars[i]``: CVD share in trade direction, CVD-close correlation, log-volume trend."""
    span = bars[i - n:i + 1]
    window = bars[i - n:i]
    total = sum(b.volume for b in span)
    share = sign * sum(b.delta for b in span) / total if total > 0 else 0.0
    path, running = [], 0.0
    for b in span:
        running += b.delta
        path.append(running)
    logs = [math.log(b.volume) if b.volume > 0 else 0.0 for b in window]
    half = n // 2
    trend = sum(logs[n - half:]) / half - sum(logs[:half]) / half
    return share, _correlation(path, [b.close for b in span]), trend


# -- T: day / week / month direction ----------------------------------------------------------------


def daily_closes(bars: Sequence[Kline]) -> dict[date, float]:
    """Close of the last 1h candle of every UTC day."""
    out: dict[date, float] = {}
    for b in bars:
        out[datetime.fromtimestamp(b.open_time / 1000, tz=timezone.utc).date()] = b.close
    return out


def trend_states(bars: Sequence[Kline], days: Sequence[date]) -> dict[date, tuple[int, int, int]]:
    """OFX direction filter per day: only periods that ended before the day began (ofx.trend.Trend)."""
    from src.research_lab.ofx.trend import FRAMES, Trend

    trend = Trend(daily_closes(bars))
    return {d: tuple(trend.state(d, f) for f in FRAMES) for d in days}


# -- V: VWAP ----------------------------------------------------------------------------------------


class Vwap:
    """Prefix sums of price x volume and volume over the 1h candles (typical price (h + l + c) / 3)."""

    def __init__(self, bars: Sequence[Kline]) -> None:
        self.opens = [b.open_time for b in bars]
        self.pv, self.v = [0.0], [0.0]
        for b in bars:
            self.pv.append(self.pv[-1] + (b.high + b.low + b.close) / 3 * b.volume)
            self.v.append(self.v[-1] + b.volume)

    def between(self, first: int, last: int) -> float | None:
        vol = self.v[last + 1] - self.v[first]
        return (self.pv[last + 1] - self.pv[first]) / vol if vol > 0 else None

    def features(self, bars: Sequence[Kline], i: int, sign: float, atr: float) -> tuple[float, float] | None:
        day = self.between(max(0, i - VWAP_HOURS + 1), i)
        week = self.between(bisect_left(self.opens, week_start(bars[i].open_time)), i)
        if day is None or week is None or atr <= 0:
            return None
        close = bars[i].close
        return sign * (close - day) / atr, sign * (close - week) / atr


# -- rows -------------------------------------------------------------------------------------------


# -- outcome after Bitunix costs ---------------------------------------------------------------------


def outcome(bars: Sequence[Kline], i: int, direction: str, atr: float,
            rates: tuple[Sequence[int], Sequence[float]]) -> float | None:
    """Net R of the S22 standard trade at the close of ``bars[i]`` after Bitunix costs (section 3).

    Taker fee and slippage on both sides, extra slippage when the stop fills, funding paid or received at every
    funding time after the entry up to the exit (long pays a positive rate). Stop first when one candle holds both.
    None when the 48 following candles are not all there.
    """
    if i + s22.HORIZON >= len(bars) or bars[i + s22.HORIZON].open_time - bars[i].open_time != s22.HORIZON * HOUR:
        return None
    entry = bars[i].close
    risk = s22.STOP_ATR * atr
    sign = 1.0 if direction == "LONG" else -1.0
    stop, target = entry - sign * risk, entry + sign * s22.TARGET_ATR * atr
    exit_k, exit_price, stopped = i + s22.HORIZON, bars[i + s22.HORIZON].close, False
    for k in range(i + 1, i + s22.HORIZON + 1):
        bar = bars[k]
        if (bar.low <= stop) if sign > 0 else (bar.high >= stop):
            exit_k, exit_price, stopped = k, stop, True
            break
        if (bar.high >= target) if sign > 0 else (bar.low <= target):
            exit_k, exit_price = k, target
            break
    gross = sign * (exit_price - entry) / risk
    side = FEE_TAKER + SLIPPAGE
    cost = entry * side + exit_price * (side + (STOP_SLIPPAGE if stopped else 0.0))
    times, values = rates
    lo = bisect_right(times, bars[i].open_time + HOUR)
    hi = bisect_right(times, bars[exit_k].open_time + HOUR)
    funding = sign * sum(values[lo:hi]) * entry
    return gross - (cost + funding) / risk


_STATE: dict = {}


def _rows_for(i: int) -> list[Row]:
    st = _STATE
    bars, atr = st["bars_1h"], st["atrs"][i]
    close_time = bars[i].open_time + HOUR
    section = s22.section_of(close_time)
    verdicts = s22.verdicts(bars, st["candles_1h"], st["candles_30m"], st["opens_30m"], i, atr)
    day = datetime.fromtimestamp(close_time / 1000, tz=timezone.utc).date()
    trend = st["trend"].get(day)
    rows = []
    for direction in s22.DIRECTIONS:
        sign = 1.0 if direction == "LONG" else -1.0
        feats: dict[str, tuple[float, ...] | None] = {
            "C": tuple(float(x) for x in s22._sides(verdicts[direction])),
            "K": candle_flow(bars, i, sign),
            "F": st["footprint"].get((bars[i].open_time, direction)) if st["footprint"] is not None else None,
            "G": st["funding"].get((bars[i].open_time, direction)) if st["funding"] is not None else None,
            "T": tuple(sign * s for s in trend) if trend is not None else None,
            "V": st["vwap"].features(bars, i, sign, atr),
        }
        net_r = None
        if st["rates"] is not None:
            net_r = outcome(bars, i, direction, atr, st["rates"])
            if net_r is None:
                continue
        rows.append(Row(close_time, section, direction, feats, net_r))
    return rows


def build_rows(bars_1h: Sequence[Kline], bars_30m: Sequence[Kline], *, footprint: Mapping | None = None,
               funding: Mapping | None = None, workers: int = 1,
               rates: Sequence[tuple[int, float]] | None = None) -> list[Row]:
    """Feature rows for every S22 moment, both directions. The outcome is computed only when ``rates`` (funding
    history for the cost) is given, which only ``evaluate`` does."""
    atrs = atr_series(bars_1h)
    todo = s22.moments(bars_1h, atrs)
    days = sorted({datetime.fromtimestamp((bars_1h[i].open_time + HOUR) / 1000, tz=timezone.utc).date() for i in todo})
    _STATE.update(bars_1h=bars_1h, atrs=atrs, candles_1h=s22.candles(bars_1h, "1h", HOUR),
                  candles_30m=s22.candles(bars_30m, "30m", s22.HALF), opens_30m=[b.open_time for b in bars_30m],
                  trend=trend_states(bars_1h, days), vwap=Vwap(bars_1h), footprint=footprint, funding=funding,
                  rates=None if rates is None else ([t for t, _ in rates], [r for _, r in rates]))
    if workers > 1:
        # forked on purpose: Python 3.14 (PS5) defaults to forkserver, which would see an empty _STATE
        with multiprocessing.get_context("fork").Pool(workers) as pool:
            parts = pool.map(_rows_for, todo, chunksize=200)
    else:
        parts = [_rows_for(i) for i in todo]
    return [row for part in parts for row in part]


def moment_events(bars_1h: Sequence[Kline]) -> list[SimpleNamespace]:
    """The S22 moments as S21-style events (open time of the 1h candle, direction up/down) for the loaders."""
    atrs = atr_series(bars_1h)
    return [SimpleNamespace(time=bars_1h[i].open_time, direction=d)
            for i in s22.moments(bars_1h, atrs) for d in (UP, DOWN)]


def _keyed(by_event: Mapping[int, tuple[float, ...]], events: Sequence[SimpleNamespace]) -> dict:
    """Undo the loaders' key (event time only) into (time, LONG/SHORT)."""
    return {(e.time, "LONG" if e.direction == UP else "SHORT"): by_event[(e.time, e.direction)]
            for e in events if (e.time, e.direction) in by_event}


def load_rates(root: Path, *, fetch: bool = False) -> list[tuple[int, float]]:
    """Published funding rates (time, rate) of the USD-M archive, 2020-01 to 2024-12."""
    from src.research_lab.data.archive import ArchiveRef, Dataset, Market
    from src.research_lab.data.store import ArchiveStore, months
    from src.research_lab.studies.s21 import FUNDING_FIRST_MONTH

    store = ArchiveStore(root)
    refs = [ArchiveRef(Market.USDM, Dataset.FUNDING, y, m, symbol=s22.SYMBOL) for y, m in months(FUNDING_FIRST_MONTH, s22.LAST_MONTH)]
    if fetch:
        for ref in refs:
            store.fetch(ref)
    return [(f.time, f.rate) for f in store.load_funding(refs)]


def load_funding(rates: Sequence[tuple[int, float]], events: Sequence[SimpleNamespace]) -> dict:
    from src.research_lab.studies.s21 import FUNDING_LOOKBACK, funding_features

    times = [t for t, _ in rates]
    out = {}
    for e in events:
        cut = bisect_right(times, e.time + HOUR)
        feats = funding_features(rates[max(0, cut - FUNDING_LOOKBACK - 1):cut], e)
        if feats is not None:
            out[(e.time, e.direction)] = feats
    return _keyed(out, events)


def load_footprint(root: Path, events: Sequence[SimpleNamespace], *, workers: int = 1, cache: Path | None = None) -> dict:
    from src.research_lab.studies import s19
    from src.research_lab.studies.s21 import footprint_features

    readings, _ = s19.read_range(root, date(2020, 1, 1), date(2024, 12, 31), workers=workers, cache=cache)
    by_start = {r.start: r for r in readings}
    out = {}
    for e in events:
        feats = footprint_features(by_start, e.time, e.direction, s19.TODAY_KEYS)
        if feats is not None:
            out[(e.time, e.direction)] = feats
    return _keyed(out, events)


# -- models (section 4) -----------------------------------------------------------------------------

M1_TAKE_AT, M1_SKIP_AT = 4, -4
M1_AGAINST = {"G"}  # funding: the paying side is crowded, so its sign votes against the trade
M1_SILENT = {("K", 1), ("K", 2)}  # co-movement and volume trend have no direction
M2_LAMBDA = 1.0  # L2 penalty on the summed log-loss, intercept free
M2_ITERATIONS = 25
M2_TAKE_Q, M2_SKIP_Q = 2 / 3, 1 / 3  # NEHMEN top third, AUSLASSEN bottom third of the training predictions


def m1_score(row: Row) -> int:
    """Sum of the votes: every directional feature counts with its sign (funding against)."""
    score = 0
    for fam in FAMILIES:
        for k, value in enumerate(row.features[fam] or ()):
            if (fam, k) in M1_SILENT:
                continue
            vote = (value > 0) - (value < 0)
            score += -vote if fam in M1_AGAINST else vote
    return score


def m1_decision(row: Row) -> str:
    from src.dashboard.chart_verdict import NEUTRAL, SKIP, TAKE

    score = m1_score(row)
    return TAKE if score >= M1_TAKE_AT else SKIP if score <= M1_SKIP_AT else NEUTRAL


def vector(row: Row) -> list[float]:
    return [v for fam in FAMILIES for v in row.features[fam]]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (small dense system)."""
    n = len(b)
    m = [row[:] + [b[k]] for k, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            if f:
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


@dataclass(frozen=True)
class Logit:
    mean: tuple[float, ...]
    sd: tuple[float, ...]
    weights: tuple[float, ...]  # intercept first

    def prob(self, row: Row) -> float:
        x = vector(row)
        z = self.weights[0] + sum(w * (v - m) / s for w, v, m, s in zip(self.weights[1:], x, self.mean, self.sd))
        return _sigmoid(z)


def fit_logit(rows: Sequence[Row], lam: float = M2_LAMBDA, iterations: int = M2_ITERATIONS) -> Logit:
    """Newton steps on the L2-penalised log-loss, target net R > 0, features standardised on these rows."""
    xs = [vector(r) for r in rows]
    ys = [1.0 if r.net_r > 0 else 0.0 for r in rows]
    d = len(xs[0])
    n = len(xs)
    mean = [sum(x[k] for x in xs) / n for k in range(d)]
    sd = [math.sqrt(sum((x[k] - mean[k]) ** 2 for x in xs) / n) or 1.0 for k in range(d)]
    zs = [[1.0] + [(x[k] - mean[k]) / sd[k] for k in range(d)] for x in xs]
    w = [0.0] * (d + 1)
    for _ in range(iterations):
        grad = [lam * w[k] if k else 0.0 for k in range(d + 1)]
        hess = [[(lam if (j == k and j) else 0.0) for k in range(d + 1)] for j in range(d + 1)]
        for z, y in zip(zs, ys):
            p = _sigmoid(sum(a * b for a, b in zip(w, z)))
            g, h = p - y, p * (1.0 - p)
            for j in range(d + 1):
                zj = z[j]
                grad[j] += g * zj
                hz = h * zj
                row = hess[j]
                for k in range(j, d + 1):
                    row[k] += hz * z[k]
        for j in range(d + 1):
            for k in range(j):
                hess[j][k] = hess[k][j]
        step = _solve(hess, grad)
        w = [a - b for a, b in zip(w, step)]
        if max(abs(b) for b in step) < 1e-8:
            break
    return Logit(tuple(mean), tuple(sd), tuple(w))


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def m2_rule(train: Sequence[Row]) -> tuple[Logit, float, float]:
    model = fit_logit(train)
    probs = [model.prob(r) for r in train]
    return model, _quantile(probs, M2_TAKE_Q), _quantile(probs, M2_SKIP_Q)


def as_s22(rows: Sequence[Row], decide) -> list:
    """Rows in S22's shape, so S22's bootstrap and luck test run unchanged."""
    return [s22.Row(r.time, r.section, r.direction, 0, decide(r), (), r.net_r) for r in rows]


def _cell(values: Sequence[float]) -> dict:
    return {"n": len(values), "mittel_netto_r": round(sum(values) / len(values), 4) if values else None}


def describe(rows: Sequence) -> dict:
    from src.dashboard.chart_verdict import NEUTRAL, SKIP, TAKE

    return {"alle": _cell([r.net_r for r in rows]),
            "entscheidung": {d: _cell([r.net_r for r in rows if r.decision == d]) for d in (TAKE, NEUTRAL, SKIP)},
            "wochen": len({week_of(r.time) for r in rows})}


def families(rows: Sequence[Row]) -> dict:
    """Per family, no test: mean net R where its votes (M1 reading) are for, and where against."""
    out = {}
    for fam in FAMILIES:
        pro, con = [], []
        for r in rows:
            votes = sum(((v > 0) - (v < 0)) * (-1 if fam in M1_AGAINST else 1)
                        for k, v in enumerate(r.features[fam]) if (fam, k) not in M1_SILENT)
            (pro if votes > 0 else con if votes < 0 else []).append(r.net_r)
        out[fam] = {"name": FAMILY_NAMES[fam], "dafuer": _cell(pro), "dagegen": _cell(con)}
    return out


def evaluate(rows: Sequence[Row], loaded: Sequence[str], *, boot_draws: int = s22.BOOT_DRAWS,
             shift_draws: int = s22.SHIFT_DRAWS) -> dict:
    from src.dashboard.chart_verdict import SKIP, TAKE
    from src.research_lab.stats.inference import holm

    if VERSION.startswith("0"):
        raise SystemExit(f"S24 {VERSION} ist ein Entwurf: erst nach dem Einfrieren als 1.0 auswerten")
    if set(loaded) != set(FAMILIES):
        raise SystemExit(f"S24 braucht alle Familien, geladen: {loaded}")
    full = [r for r in rows if complete(r, FAMILIES) and r.net_r is not None]
    train = [r for r in full if r.section == "training"]
    valid = [r for r in full if r.section == "validierung"]
    gate = count(rows, loaded)
    result: dict = {"gate": gate, "kosten": {"taker": FEE_TAKER, "schlupf": SLIPPAGE, "stop_schlupf": STOP_SLIPPAGE,
                                             "funding": "veröffentlichte Raten"},
                    "familien": {"training": families(train), "validierung": families(valid)}}
    if not gate["gate"]:
        result["urteil"] = "nicht testbar (Gate)"
        return result
    logit, take_at, skip_at = m2_rule(train)

    def m2(r: Row) -> str:
        p = logit.prob(r)
        return TAKE if p >= take_at else SKIP if p <= skip_at else "NEUTRAL"

    result["m2_modell"] = {"gewichte": [round(w, 5) for w in logit.weights],
                           "merkmale": ["achse"] + [n for f in FAMILIES for n in FEATURES[f]],
                           "nehmen_ab": round(take_at, 5), "auslassen_bis": round(skip_at, 5)}
    models = {"M1": m1_decision, "M2": m2}
    per, p = {}, {}
    for name, decide in models.items():
        t, v = as_s22(train, decide), as_s22(valid, decide)
        h = s22.diff(v, TAKE, SKIP)
        p[name] = s22.diff_bootstrap_p(v, TAKE, SKIP, seed=f"S24:{name}", draws=boot_draws) if h is not None else None
        per[name] = {"training": describe(t), "validierung": describe(v), "abstand_r": None if h is None else round(h, 4),
                     "abstand_training_r": s22.diff(t, TAKE, SKIP), "p": p[name],
                     "glueckstest": s22.shift_test(v, h, draws=shift_draws) if h is not None else {"getestet": False}}
    passed = holm({k: v for k, v in p.items() if v is not None}, 2, s22.ALPHA)
    verdicts = {}
    for name, info in per.items():
        take_mean = info["validierung"]["entscheidung"][TAKE]["mittel_netto_r"]
        checks = {"holm": name in passed,
                  "abstand": info["abstand_r"] is not None and info["abstand_r"] >= s22.MIN_DIFF_R,
                  "training_gleiches_vorzeichen": (info["abstand_training_r"] or 0) > 0,
                  "glueckstest": bool(info["glueckstest"].get("getestet")) and info["glueckstest"]["p"] < s22.ALPHA,
                  "nehmen_positiv_nach_kosten": take_mean is not None and take_mean > 0}
        info["kriterien"] = checks
        verdicts[name] = "BESTANDEN (Kandidat)" if all(checks.values()) else "NICHT BESTANDEN"
    result["modelle"] = per
    result["urteil_je_modell"] = verdicts
    result["urteil"] = ("BESTANDEN (Kandidat für den Live-Schatten)" if "BESTANDEN (Kandidat)" in verdicts.values()
                        else "NO ROBUST EDGE PROVEN")
    return result


# -- count and export -------------------------------------------------------------------------------


def complete(row: Row, families: Sequence[str]) -> bool:
    return all(row.features.get(f) is not None for f in families)


def count(rows: Sequence[Row], loaded: Sequence[str]) -> dict:
    """Results-blind: moments, coverage per family and complete rows per section. No outcome is read."""
    out: dict = {}
    for name in s22.SECTIONS:
        part = [r for r in rows if r.section == name]
        cover = {f: (sum(1 for r in part if r.features.get(f) is not None) if f in loaded else "nicht geladen")
                 for f in FAMILIES}
        full = [r for r in part if complete(r, loaded)]
        per_dir = {d: sum(1 for r in full if r.direction == d) for d in s22.DIRECTIONS}
        weeks = len({week_of(r.time) for r in full})
        out[name] = {"momente": len({r.time for r in part}), "zeilen": len(part), "abdeckung": cover,
                     "vollstaendig": len(full), "vollstaendig_je_richtung": per_dir, "wochen": weeks,
                     "gate": min(per_dir.values(), default=0) >= MIN_TRADES}
    out["familien_geladen"] = list(loaded)
    out["gate"] = all(out[n]["gate"] for n in s22.SECTIONS) and out["validierung"]["wochen"] >= MIN_WEEKS
    return out


def export(rows: Sequence[Row], path: Path) -> int:
    """One JSON line per row with all features (gzip), for package 2. Contains no outcome."""
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            line = {"zeit": r.time, "abschnitt": r.section, "richtung": r.direction}
            for f in FAMILIES:
                vals = r.features.get(f)
                for k, name in enumerate(FEATURES[f]):
                    line[name] = None if vals is None else round(vals[k], 6)
            fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    return len(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s24")
    parser.add_argument("step", choices=("count", "export", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fehlende Monatsdateien laden (nur bis 2024-12)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--footprint", type=Path, help="S8-Speicher; ohne ihn fehlt Familie F")
    parser.add_argument("--fp-cache", type=Path)
    parser.add_argument("--no-funding", action="store_true")
    args = parser.parse_args(argv)
    if args.step == "evaluate" and VERSION.startswith("0"):
        raise SystemExit(f"S24 {VERSION} ist ein Entwurf: erst nach dem Einfrieren als 1.0 auswerten")
    bars_1h, bars_30m, digest = s22.load(args.root, fetch=args.fetch)
    events = moment_events(bars_1h)
    rates = None if args.no_funding else load_rates(args.root, fetch=args.fetch)
    funding = None if rates is None else load_funding(rates, events)
    footprint = load_footprint(args.footprint, events, workers=args.workers, cache=args.fp_cache) if args.footprint else None
    loaded = [f for f in FAMILIES if not ((f == "F" and footprint is None) or (f == "G" and funding is None))]
    rows = build_rows(bars_1h, bars_30m, footprint=footprint, funding=funding, workers=args.workers,
                      rates=rates if args.step == "evaluate" else None)
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    args.out.mkdir(parents=True, exist_ok=True)
    result = {"studie": "S24", "version": VERSION, "seed": SEED, "datensatz_sha256": digest,
              "merkmale": {f: list(FEATURES[f]) for f in FAMILIES}, "nur_schatten": SHADOW_ONLY,
              "zaehllauf": count(rows, loaded)}
    if args.step == "export":
        table = args.out / f"s24_merkmale_{stamp}.jsonl.gz"
        result["tabelle"] = {"datei": table.name, "zeilen": export(rows, table)}
    if args.step == "evaluate":
        result["auswertung"] = evaluate(rows, loaded)
    path = args.out / f"s24_{args.step}_{stamp}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)
    print(json.dumps(result["zaehllauf"], ensure_ascii=False))
    if "auswertung" in result:
        print(result["auswertung"]["urteil"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
