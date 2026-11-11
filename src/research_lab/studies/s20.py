"""S20: flip probability from candle structure at a swing level (BTCUSDT spot, 1h, 2017-08 to 2024).

Rules: docs/research_lab/studien/S20_FLIP_WAHRSCHEINLICHKEIT_PRAEREGISTRIERUNG_ENTWURF.md (version 1.0, frozen 2026-11-11).
Observation study without trades and without a register slot; the holdout from 2025-01-01 is never loaded.

    python -m src.research_lab.studies.s20 count    --root data/research_lab --out DIR [--fetch]
    python -m src.research_lab.studies.s20 evaluate --root data/research_lab --out DIR [--workers N]

A *level* is a confirmed swing high or low (``PIVOT_K`` closed 1h candles on each side). A *break* (the
event) is the first close at least ``BREAK_ATR`` x ATR14 beyond an active level; closes just beyond leave the
level alive. The *flip* label says whether the level then held for ``HOLD_BARS`` candles (no close back on the old
side). Features are read at the close of the break candle only. The window grid ``WINDOWS`` gives the number of
candles before the break that feed the window features; the event set is the same for every window.

``count`` is the results-blind feasibility gate (section 5.1): events and weeks per section and direction, drop
reasons, never a label. ``evaluate`` (section 5) refuses to run while ``VERSION`` is a draft: window choice by
forward-chained cross-validation inside training only, one fit, one look at validation, block bootstrap, Holm over
the two hypotheses and the shift test ("Glückstest") that repeats the whole pipeline, window choice included.
Stdlib only.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

from src.research_lab.data.parse import Kline
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.stats.inference import holm

VERSION = "1.0"
SEED = 20
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
HOUR = 3_600_000
WEEK = 7 * 24 * HOUR
MONDAY_OFFSET = 4 * 24 * HOUR  # 1970-01-05 00:00 UTC is a Monday
FIRST_MONTH = (2017, 8)
LAST_MONTH = (2024, 12)

# -- event rules (section 3) --------------------------------------------------------------------------
PIVOT_K = 24  # a swing high needs 24 closed candles on each side; it is known only 24 candles after the pivot
LEVEL_MAX_AGE = 720  # a level stays active for 30 days after its confirmation
ATR_PERIOD = 14
BREAK_ATR = 0.25  # "klar jenseits": close at least 0.25 x ATR14 beyond the level
HOLD_BARS = 24  # flip = no close back on the old side in the next 24 candles
TOUCH_ATR = 0.25  # a window candle "tests" the level when it comes this close
WINDOWS = (5, 10, 20, 50)
MAX_WINDOW = max(WINDOWS)
UP, DOWN = "up", "down"

# -- model and tests (section 4 and 5) ----------------------------------------------------------------
MECHANICS_FEATURE = 2  # index of "abstand_atr": under a random walk the hold chance depends on this distance alone
CANDLE_FEATURES = ("koerper", "docht_gegen", "abstand_atr", "spanne_atr", "taker_saldo", "level_alter", "richtung_up")
WINDOW_FEATURES = ("volumen_log", "beruehrungen", "momentum", "kompression", "abweisung")
RIDGE = 1.0  # L2 penalty on standardised slopes, intercept free; fixed, never tuned
NEWTON_STEPS = 25
CV_YEARS = (2019, 2020, 2021, 2022)  # forward chaining: fit on everything before the year, score the year
TIE_MARGIN = 0.0005  # smallest window whose CV log-loss is within this of the best one wins
MIN_EVENTS = {"training": 400, "validierung": 150}
MIN_WEEKS = {"training": 100, "validierung": 50}
MIN_REL_GAIN = 0.01  # validation log-loss at least 1 % below the mechanics model
MIN_AUC = 0.55
MIN_QUINTILE_SPREAD_PP = 10.0
ALPHA = 0.05
HOLM_M = 2  # H1 (model against mechanics) and H2 (window against candle only)
BOOT_DRAWS = 9_999
BLOCK_WEEKS = 4
SHIFT_DRAWS = 199
MIN_SHIFT = 100
EPS = 1e-12

SECTIONS = {"training": (0, VALIDATION_START_MS), "validierung": (VALIDATION_START_MS, HOLDOUT_START_MS)}


def section_of(time_ms: int) -> str | None:
    return next((name for name, (lo, hi) in SECTIONS.items() if lo <= time_ms < hi), None)


def week_of(time_ms: int) -> int:
    return (time_ms - MONDAY_OFFSET) // WEEK


def year_of(time_ms: int) -> int:
    return datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc).year


# -- events -------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Event:
    index: int  # break candle
    time: int  # open time of the break candle
    direction: str
    level: float
    pivot: int  # index of the pivot candle
    atr: float
    section: str


@dataclass(frozen=True, slots=True)
class Level:
    price: float
    pivot: int
    confirmed: int  # index of the candle whose close confirms the pivot


def _gap_prefix(bars: Sequence[Kline]) -> list[int]:
    prefix = [0] * len(bars)
    for i in range(1, len(bars)):
        prefix[i] = prefix[i - 1] + (bars[i].open_time - bars[i - 1].open_time != HOUR)
    return prefix


def _true_ranges(bars: Sequence[Kline]) -> list[float]:
    out = [bars[0].high - bars[0].low] if bars else []
    for prev, bar in itertools.pairwise(bars):
        out.append(max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close)))
    return out


def atr_series(bars: Sequence[Kline], n: int = ATR_PERIOD) -> list[float | None]:
    """Simple mean of the last n true ranges up to and including the candle (same as backtest.indicators.atr)."""
    tr = _true_ranges(bars)
    out: list[float | None] = [None] * len(bars)
    running = 0.0
    for i in range(1, len(bars)):
        running += tr[i]
        if i > n:
            running -= tr[i - n]
        if i >= n:
            out[i] = running / n
    return out


def pivots(bars: Sequence[Kline], k: int = PIVOT_K) -> tuple[list[Level], list[Level]]:
    """Swing highs and lows. Strictly above the k candles before, at least as high as the k after (first one wins)."""
    gaps = _gap_prefix(bars)
    highs: list[Level] = []
    lows: list[Level] = []
    for i in range(k, len(bars) - k):
        if gaps[i + k] != gaps[i - k]:
            continue
        h, lo = bars[i].high, bars[i].low
        if h > max(b.high for b in bars[i - k:i]) and h >= max(b.high for b in bars[i + 1:i + k + 1]):
            highs.append(Level(h, i, i + k))
        if lo < min(b.low for b in bars[i - k:i]) and lo <= min(b.low for b in bars[i + 1:i + k + 1]):
            lows.append(Level(lo, i, i + k))
    return highs, lows


def find_events(bars: Sequence[Kline]) -> tuple[list[Event], Counter]:
    """Walk the candles once. A level dies at its first clear close beyond it (BREAK_ATR x ATR14); closes just
    beyond leave it alive. That clear close is the event.

    Uses nothing after the break candle except the check that the label window lies in the same section and has
    no gap (the label itself is not computed here)."""
    gaps = _gap_prefix(bars)
    atr = atr_series(bars)
    highs, lows = pivots(bars)
    by_confirm: dict[int, list[tuple[str, Level]]] = {}
    for lvl in highs:
        by_confirm.setdefault(lvl.confirmed, []).append((UP, lvl))
    for lvl in lows:
        by_confirm.setdefault(lvl.confirmed, []).append((DOWN, lvl))
    active: dict[str, list[Level]] = {UP: [], DOWN: []}
    drops: Counter = Counter()
    events: list[Event] = []
    last_event: dict[str, int] = {}
    lookback = MAX_WINDOW + ATR_PERIOD + 1
    for t, bar in enumerate(bars):
        for direction, lvl in by_confirm.get(t - 1, ()):
            active[direction].append(lvl)
        for direction in (UP, DOWN):
            active[direction] = [lv for lv in active[direction] if t - lv.confirmed <= LEVEL_MAX_AGE]
            width = atr[t]
            if width is None or width <= 0:
                continue
            reach = BREAK_ATR * width
            if direction == UP:
                broken = [lv for lv in active[UP] if bar.close >= lv.price + reach]
            else:
                broken = [lv for lv in active[DOWN] if bar.close <= lv.price - reach]
            if not broken:
                continue
            active[direction] = [lv for lv in active[direction] if lv not in broken]
            nearest = max(broken, key=lambda lv: lv.price) if direction == UP else min(broken, key=lambda lv: lv.price)
            drops["mitgenommen"] += len(broken) - 1
            section = section_of(bar.open_time)
            if section is None:
                drops["ausserhalb"] += 1
                continue
            if t - lookback < 0 or t + HOLD_BARS >= len(bars) or gaps[t + HOLD_BARS] != gaps[t - lookback]:
                drops["luecke_oder_rand"] += 1
                continue
            if section_of(bars[t + HOLD_BARS].open_time) != section:
                drops["abschnittsende"] += 1
                continue
            if direction in last_event and t <= last_event[direction] + HOLD_BARS:
                drops["entprellt"] += 1
                continue
            last_event[direction] = t
            events.append(Event(t, bar.open_time, direction, nearest.price, nearest.pivot, width, section))
    return events, drops


def label(bars: Sequence[Kline], event: Event) -> int:
    """1 = flip: no close back on the old side in the next HOLD_BARS candles."""
    after = bars[event.index + 1:event.index + 1 + HOLD_BARS]
    if len(after) < HOLD_BARS:
        raise ValueError("label window incomplete")
    if event.direction == UP:
        return int(all(b.close > event.level for b in after))
    return int(all(b.close < event.level for b in after))


# -- features (section 4.1) ----------------------------------------------------------------------------


def candle_features(bars: Sequence[Kline], event: Event) -> list[float]:
    bar = bars[event.index]
    s = 1.0 if event.direction == UP else -1.0
    rng = bar.high - bar.low
    if event.direction == UP:
        wick = bar.high - max(bar.open, bar.close)
    else:
        wick = min(bar.open, bar.close) - bar.low
    taker = (2 * bar.taker_buy_volume - bar.volume) / bar.volume if bar.volume > 0 else 0.0
    return [
        s * (bar.close - bar.open) / rng if rng > 0 else 0.0,
        wick / rng if rng > 0 else 0.0,
        s * (bar.close - event.level) / event.atr,
        rng / event.atr,
        s * taker,
        (event.index - event.pivot) / (LEVEL_MAX_AGE + PIVOT_K),
        1.0 if event.direction == UP else 0.0,
    ]


def window_features(bars: Sequence[Kline], event: Event, n: int) -> list[float]:
    t = event.index
    window = bars[t - n:t]
    bar = bars[t]
    a = event.atr
    s = 1.0 if event.direction == UP else -1.0
    mean_vol = sum(b.volume for b in window) / n
    vol = math.log(bar.volume / mean_vol) if bar.volume > 0 and mean_vol > 0 else 0.0
    if event.direction == UP:
        touches = sum(1 for b in window if b.high >= event.level - TOUCH_ATR * a)
        rejection = sum(b.high - max(b.open, b.close) for b in window) / (n * a)
    else:
        touches = sum(1 for b in window if b.low <= event.level + TOUCH_ATR * a)
        rejection = sum(min(b.open, b.close) - b.low for b in window) / (n * a)
    root = math.sqrt(n)
    return [
        vol,
        touches / n,
        s * (bar.close - bars[t - n].close) / (a * root),
        (max(b.high for b in window) - min(b.low for b in window)) / (a * root),
        rejection,
    ]


@dataclass(frozen=True, slots=True)
class Row:
    time: int
    week: int
    year: int
    section: str
    direction: str
    y: int
    candle: tuple[float, ...]
    window: dict[int, tuple[float, ...]]


def build_rows(bars: Sequence[Kline], events: Sequence[Event]) -> list[Row]:
    return [Row(e.time, week_of(e.time), year_of(e.time), e.section, e.direction, label(bars, e),
                tuple(candle_features(bars, e)), {n: tuple(window_features(bars, e, n)) for n in WINDOWS})
            for e in events]


def matrix(rows: Sequence[Row], n: int | None) -> list[list[float]]:
    """n=None: candle-only model; otherwise candle plus window features for window n."""
    return [list(r.candle) + (list(r.window[n]) if n is not None else []) for r in rows]


def mechanics_matrix(rows: Sequence[Row]) -> list[list[float]]:
    """Baseline of H1: only the distance of the close beyond the level in ATR (what a random walk already explains)."""
    return [[r.candle[MECHANICS_FEATURE]] for r in rows]


# -- ridge logistic regression (stdlib) ----------------------------------------------------------------


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        if abs(m[col][col]) < 1e-15:
            raise ValueError("singular system")
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass(frozen=True, slots=True)
class Model:
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    beta: tuple[float, ...]  # intercept first, then standardised slopes

    def predict(self, x: Sequence[float]) -> float:
        z = self.beta[0] + sum(b * (v - m) / s for b, v, m, s in zip(self.beta[1:], x, self.mean, self.scale))
        return _sigmoid(z)


def fit(x: Sequence[Sequence[float]], y: Sequence[int], ridge: float = RIDGE) -> Model:
    """Newton steps on the penalised log-likelihood; features standardised on the fitting rows only."""
    n, d = len(x), len(x[0])
    mean = [sum(r[j] for r in x) / n for j in range(d)]
    scale = []
    for j in range(d):
        var = sum((r[j] - mean[j]) ** 2 for r in x) / n
        scale.append(math.sqrt(var) if var > 1e-18 else 1.0)
    z = [[1.0] + [(r[j] - mean[j]) / scale[j] for j in range(d)] for r in x]
    beta = [0.0] * (d + 1)
    rate = min(max(sum(y) / n, 1e-6), 1 - 1e-6)
    beta[0] = math.log(rate / (1 - rate))
    for _ in range(NEWTON_STEPS):
        grad = [0.0] * (d + 1)
        hess = [[0.0] * (d + 1) for _ in range(d + 1)]
        for row, target in zip(z, y):
            p = _sigmoid(sum(b * v for b, v in zip(beta, row)))
            w = p * (1 - p)
            err = target - p
            for i in range(d + 1):
                grad[i] += err * row[i]
                wi = w * row[i]
                hrow = hess[i]
                for k in range(i, d + 1):
                    hrow[k] += wi * row[k]
        for i in range(d + 1):
            for k in range(i):
                hess[i][k] = hess[k][i]
        for i in range(1, d + 1):
            grad[i] -= ridge * beta[i]
            hess[i][i] += ridge
        step = _solve(hess, grad)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return Model(tuple(mean), tuple(scale), tuple(beta))


def log_loss(y: int, p: float) -> float:
    p = min(max(p, EPS), 1 - EPS)
    return -math.log(p) if y else -math.log(1 - p)


def mean_log_loss(ys: Sequence[int], ps: Sequence[float]) -> float:
    return sum(log_loss(y, p) for y, p in zip(ys, ps)) / len(ys)


def auc(ys: Sequence[int], ps: Sequence[float]) -> float | None:
    """Mann-Whitney AUC with average ranks for ties."""
    pos = sum(ys)
    neg = len(ys) - pos
    if not pos or not neg:
        return None
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    ranks = [0.0] * len(ps)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and ps[order[j + 1]] == ps[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    rank_pos = sum(r for r, y in zip(ranks, ys) if y)
    return (rank_pos - pos * (pos + 1) / 2) / (pos * neg)


def quintile_spread_pp(ys: Sequence[int], ps: Sequence[float]) -> float | None:
    """Flip share of the top fifth by prediction minus the bottom fifth, in percentage points."""
    k = len(ys) // 5
    if k == 0:
        return None
    order = sorted(range(len(ps)), key=lambda i: (ps[i], i))
    low = sum(ys[i] for i in order[:k]) / k
    high = sum(ys[i] for i in order[-k:]) / k
    return (high - low) * 100.0


# -- window choice inside training (section 4.2) -------------------------------------------------------


def cv_loss(rows: Sequence[Row], n: int | None) -> float | None:
    """Forward-chained CV over CV_YEARS: pooled log-loss of the out-of-fold predictions."""
    losses: list[float] = []
    for year in CV_YEARS:
        past = [r for r in rows if r.year < year]
        test = [r for r in rows if r.year == year]
        if len(past) < 50 or not test or len({r.y for r in past}) < 2:
            continue
        model = fit(matrix(past, n), [r.y for r in past])
        losses += [log_loss(r.y, model.predict(x)) for r, x in zip(test, matrix(test, n))]
    return sum(losses) / len(losses) if losses else None


def choose_window(train: Sequence[Row]) -> tuple[int, dict[int, float | None]]:
    scores = {n: cv_loss(train, n) for n in WINDOWS}
    valid = {n: s for n, s in scores.items() if s is not None}
    if not valid:
        raise ValueError("no CV score for any window")
    best = min(valid.values())
    chosen = min(n for n, s in valid.items() if s <= best + TIE_MARGIN)
    return chosen, scores


@dataclass(frozen=True, slots=True)
class Pipeline:
    window: int
    cv: dict[int, float | None]
    base_rate: float
    p_model: tuple[float, ...]
    p_candle: tuple[float, ...]
    p_mechanics: tuple[float, ...]
    model: Model
    candle_model: Model


def run_pipeline(train: Sequence[Row], valid: Sequence[Row], labels_train: Sequence[int] | None = None,
                 labels_valid: Sequence[int] | None = None) -> Pipeline:
    """Everything that touches training, then one prediction per validation event. Labels can be swapped for the
    shift test; features never move."""
    if labels_train is not None:
        train = [_relabel(r, y) for r, y in zip(train, labels_train)]
    if labels_valid is not None:
        valid = [_relabel(r, y) for r, y in zip(valid, labels_valid)]
    window, scores = choose_window(train)
    ys = [r.y for r in train]
    model = fit(matrix(train, window), ys)
    candle_model = fit(matrix(train, None), ys)
    mechanics = fit(mechanics_matrix(train), ys)
    return Pipeline(window, scores, sum(ys) / len(ys),
                    tuple(model.predict(x) for x in matrix(valid, window)),
                    tuple(candle_model.predict(x) for x in matrix(valid, None)),
                    tuple(mechanics.predict(x) for x in mechanics_matrix(valid)), model, candle_model)


def _relabel(row: Row, y: int) -> Row:
    return Row(row.time, row.week, row.year, row.section, row.direction, y, row.candle, row.window)


def rel_gain(ys: Sequence[int], p_model: Sequence[float], p_reference: Sequence[float]) -> float:
    """Relative log-loss gain of the model over a reference prediction (base rate or mechanics model)."""
    base = mean_log_loss(ys, p_reference)
    return (base - mean_log_loss(ys, p_model)) / base


# -- tests (section 5) ---------------------------------------------------------------------------------


def block_bootstrap_p(weeks: Sequence[int], diffs: Sequence[float], *, seed: str, draws: int = BOOT_DRAWS,
                      block: int = BLOCK_WEEKS) -> float | None:
    """One-sided p for H0 mean(diff) <= 0: moving blocks of ``block`` consecutive event weeks."""
    cells: dict[int, list[float]] = {}
    for w, d in zip(weeks, diffs):
        cell = cells.setdefault(w, [0.0, 0.0])
        cell[0] += 1
        cell[1] += d
    rows = [cells[w] for w in sorted(cells)]
    if len(rows) < 2:
        return None
    width = min(block, len(rows))
    starts = len(rows) - width + 1
    rng = random.Random(f"{SEED}:{seed}")
    at_or_below = 0
    for _ in range(draws):
        n = total = 0.0
        covered = 0
        while covered < len(rows):
            s = rng.randrange(starts)
            for count, value in rows[s:s + width]:
                n += count
                total += value
            covered += width
        if n == 0 or total <= 0:
            at_or_below += 1
    return (at_or_below + 1) / (draws + 1)


def _shift_one(args: tuple) -> float:
    train, valid, offset_t, offset_v = args
    yt = [r.y for r in train]
    yv = [r.y for r in valid]
    yt = yt[-offset_t:] + yt[:-offset_t]
    yv = yv[-offset_v:] + yv[:-offset_v]
    run = run_pipeline(train, valid, yt, yv)
    return rel_gain(yv, run.p_model, run.p_mechanics)


def shift_offsets(n_train: int, n_valid: int, draws: int = SHIFT_DRAWS) -> list[tuple[int, int]]:
    rng = random.Random(f"{SEED}:verschiebung")
    if n_train < 2 * MIN_SHIFT or n_valid < 2 * MIN_SHIFT // 2:
        raise ValueError("too few events for the shift test")
    return [(rng.randint(MIN_SHIFT, n_train - MIN_SHIFT), rng.randint(MIN_SHIFT // 2, n_valid - MIN_SHIFT // 2))
            for _ in range(draws)]


def shift_test(train: Sequence[Row], valid: Sequence[Row], observed: float, *, draws: int = SHIFT_DRAWS,
               workers: int = 1) -> dict:
    """Glückstest: labels shifted in a circle against the features (per section), whole pipeline again."""
    jobs = [(list(train), list(valid), a, b) for a, b in shift_offsets(len(train), len(valid), draws)]
    if workers > 1:
        with Pool(workers) as pool:
            gains = pool.map(_shift_one, jobs)
    else:
        gains = [_shift_one(job) for job in jobs]
    at_or_above = sum(1 for g in gains if g >= observed)
    ordered = sorted(gains)
    return {"ziehungen": draws, "p": (at_or_above + 1) / (draws + 1),
            "q95_zufall": ordered[int(0.95 * len(ordered)) - 1] if ordered else None}


def split(rows: Sequence[Row]) -> tuple[list[Row], list[Row]]:
    return [r for r in rows if r.section == "training"], [r for r in rows if r.section == "validierung"]


# -- count (5.1) and evaluate (5) ----------------------------------------------------------------------


def count(events: Sequence[Event], drops: Mapping[str, int]) -> dict:
    """Results-blind: numbers of events and weeks, no label."""
    out: dict = {"abschnitte": {}, "verworfen": dict(sorted(drops.items()))}
    for name in SECTIONS:
        evs = [e for e in events if e.section == name]
        weeks = {week_of(e.time) for e in evs}
        out["abschnitte"][name] = {
            "ereignisse": len(evs), "wochen": len(weeks),
            "je_richtung": {d: sum(1 for e in evs if e.direction == d) for d in (UP, DOWN)},
            "je_jahr": dict(sorted(Counter(year_of(e.time) for e in evs).items())),
            "gate": len(evs) >= MIN_EVENTS[name] and len(weeks) >= MIN_WEEKS[name],
        }
    out["gate_bestanden"] = all(s["gate"] for s in out["abschnitte"].values())
    return out


def verdict(h1: Mapping, h2: Mapping, shift: Mapping, holm_passed: set[str]) -> dict:
    h1_ok = ("H1" in holm_passed and h1["rel_gewinn"] >= MIN_REL_GAIN and (h1["auc"] or 0) >= MIN_AUC
             and (h1["quintil_spanne_pp"] or 0) >= MIN_QUINTILE_SPREAD_PP and shift["p"] < ALPHA)
    h2_ok = h1_ok and "H2" in holm_passed and h2["rel_gewinn"] > 0
    if not h1_ok:
        text = ("NICHT BESTANDEN: Kerzenstruktur sagt den Flip in der Validierung nicht verlässlich besser voraus "
                "als der Abstand zur Linie allein")
    elif h2_ok:
        text = "BESTANDEN (Kandidat): Flip-Wahrscheinlichkeit trägt, das gewählte Fenster bringt mehr als die Ausbruchskerze allein"
    else:
        text = "BESTANDEN (Kandidat), aber das Fenster bringt nichts über die Ausbruchskerze hinaus"
    return {"urteil": text, "H1_bestanden": h1_ok, "H2_bestanden": h2_ok}


def evaluate(rows: Sequence[Row], *, workers: int = 1, shift_draws: int = SHIFT_DRAWS, boot_draws: int = BOOT_DRAWS,
             version: str = VERSION) -> dict:
    if not version.startswith("1."):
        raise PermissionError("evaluate runs only after the rules are frozen as 1.0 (section 7)")
    train, valid = split(rows)
    run = run_pipeline(train, valid)
    yv = [r.y for r in valid]
    weeks = [r.week for r in valid]
    base = [run.base_rate] * len(yv)
    d1 = [log_loss(y, m) - log_loss(y, p) for y, m, p in zip(yv, run.p_mechanics, run.p_model)]
    d2 = [log_loss(y, c) - log_loss(y, p) for y, c, p in zip(yv, run.p_candle, run.p_model)]
    h1 = {"rel_gewinn": rel_gain(yv, run.p_model, run.p_mechanics), "auc": auc(yv, run.p_model),
          "quintil_spanne_pp": quintile_spread_pp(yv, run.p_model),
          "p": block_bootstrap_p(weeks, d1, seed="H1", draws=boot_draws),
          "rel_gewinn_gegen_basisrate": rel_gain(yv, run.p_model, base),
          "rel_gewinn_mechanik_gegen_basisrate": rel_gain(yv, run.p_mechanics, base)}
    cand_loss = mean_log_loss(yv, run.p_candle)
    h2 = {"rel_gewinn": (cand_loss - mean_log_loss(yv, run.p_model)) / cand_loss,
          "p": block_bootstrap_p(weeks, d2, seed="H2", draws=boot_draws)}
    passed = holm({"H1": h1["p"] if h1["p"] is not None else 1.0, "H2": h2["p"] if h2["p"] is not None else 1.0},
                  HOLM_M, ALPHA)
    shift = shift_test(train, valid, h1["rel_gewinn"], draws=shift_draws, workers=workers)
    return {
        "fenster_gewaehlt": run.window,
        "cv_logloss_je_fenster": {str(n): s for n, s in run.cv.items()},
        "cv_logloss_nur_kerze": cv_loss(train, None),
        "basisrate_training": run.base_rate,
        "H1_gegen_mechanik": h1, "H2_fenster_gegen_nur_kerze": h2, "holm_bestanden": sorted(passed),
        "glueckstest": shift, **verdict(h1, h2, shift, passed),
        "beschreibend": describe(train, valid, run),
    }


def describe(train: Sequence[Row], valid: Sequence[Row], run: Pipeline) -> dict:
    """Section 5.2: no verdict hangs on these numbers."""
    def share(rows: Sequence[Row]) -> float | None:
        return sum(r.y for r in rows) / len(rows) if rows else None
    yv = [r.y for r in valid]
    order = sorted(range(len(yv)), key=lambda i: (run.p_model[i], i))
    deciles = []
    for k in range(10):
        idx = order[k * len(order) // 10:(k + 1) * len(order) // 10]
        if idx:
            deciles.append({"vorhersage": sum(run.p_model[i] for i in idx) / len(idx), "flip_anteil": sum(yv[i] for i in idx) / len(idx), "n": len(idx)})
    names = list(CANDLE_FEATURES) + list(WINDOW_FEATURES)
    return {
        "flip_anteil": {"training": share(train), "validierung": share(valid)},
        "flip_anteil_je_jahr": {str(y): share([r for r in list(train) + list(valid) if r.year == y])
                                for y in sorted({r.year for r in list(train) + list(valid)})},
        "flip_anteil_je_richtung": {d: {s: share([r for r in rs if r.direction == d]) for s, rs in (("training", train), ("validierung", valid))} for d in (UP, DOWN)},
        "kalibrierung_validierung": deciles,
        "koeffizienten_standardisiert": dict(zip(["achsenabschnitt"] + names, run.model.beta)),
        "brier_skill_validierung": 1 - (sum((y - p) ** 2 for y, p in zip(yv, run.p_model)) / max(sum((y - run.base_rate) ** 2 for y in yv), EPS)),
    }


# -- data and CLI --------------------------------------------------------------------------------------


def refs():
    from src.research_lab.data.archive import ArchiveRef, Dataset, Market
    from src.research_lab.data.store import months
    return [ArchiveRef(Market.SPOT, Dataset.KLINES, y, m, interval=INTERVAL, symbol=SYMBOL) for y, m in months(FIRST_MONTH, LAST_MONTH)]


def load(root: Path, *, fetch: bool = False) -> tuple[list[Kline], str]:
    from src.research_lab.data.store import ArchiveStore
    store = ArchiveStore(root)
    rs = refs()
    if fetch:
        for ref in rs:
            store.fetch(ref)
    bars = [k for k in store.load_klines(rs) if k.open_time < HOLDOUT_START_MS]
    return bars, store.dataset_hash(rs)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s20")
    parser.add_argument("step", choices=("count", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fehlende Monatsdateien von data.binance.vision laden (nur bis 2024-12)")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    bars, digest = load(args.root, fetch=args.fetch)
    events, drops = find_events(bars)
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    result = {"studie": "S20", "version": VERSION, "seed": SEED, "datensatz_sha256": digest, "kerzen": len(bars),
              "zaehllauf": count(events, drops)}
    if args.step == "evaluate":
        result["auswertung"] = evaluate(build_rows(bars, events), workers=args.workers)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"s20_{args.step}_{stamp}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)
    print(json.dumps(result["zaehllauf"], ensure_ascii=False))
    if "auswertung" in result:
        print(result["auswertung"]["urteil"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
