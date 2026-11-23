"""P4: test scaffold for the comparison models A0-A6 (plan sections 7 and 8). No real data, no results.

- ``forward_label``: future return from the first bar that opens after the signal bar was **known** (``known_ms``,
  latest receive time) over h bars; returns the label and the time its last price is known.
- ``purged_splits``: expanding walk-forward; training rows whose label interval reaches into the test fold (minus an
  embargo) are removed.
- ``ridge_fit`` / ``predict``: few features, fixed penalty, plain least squares (standard library).
- ``spearman_ic``, ``clark_west``: out-of-sample ranking skill and the nested-model test.
- ``compare``: runs every model group on the same folds and returns per-model numbers. It refuses rows from the holdout.

Feature groups are names only; which features exist is decided in the S40 pre-registration.
"""
from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.research_lab.fusion.historisch import to_ms
from src.research_lab.protocol import HOLDOUT_START_MS

MODELS: dict[str, tuple[str, ...]] = {
    "A0_price": ("price",),
    "A1_orderflow": ("price", "orderflow"),
    "A2_optionsflow": ("price", "optionsflow"),
    "A3_gamma": ("price", "gamma"),
    "A4_of_gamma": ("price", "orderflow", "gamma"),
    "A5_of_optionsflow": ("price", "orderflow", "optionsflow"),
    "A6_all": ("price", "orderflow", "optionsflow", "gamma"),
}
"""Every model includes the price baseline, so each comparison against A0 is nested (Clark-West applies)."""


def forward_label(bars: Sequence, i: int, h: int) -> tuple[float, int] | None:
    """(log return, end_ms) from the open of the first bar j > i with ``open_ms >= bars[i].known_ms`` to the open of
    bar j+h. None at the end of the series. Bars come from ``of_features.bars_from_trades``.

    ``h`` counts bars, not time: empty intervals make no bar, so the horizon in time can be longer than ``h`` bar
    lengths. ``end_ms`` is the open time of bar j+h; its price is known only after that bar's first trade plus the
    receive latency, so callers add at least ``LATENCY_MS`` to the embargo of ``purged_splits``."""
    known = bars[i].known_ms
    if known is None:
        raise ValueError("bar has no known_ms; build bars with bars_from_trades")
    j = next((k for k in range(i + 1, len(bars)) if bars[k].open_ms >= known), None)
    if j is None or j + h >= len(bars) or bars[j].open <= 0 or bars[j + h].open <= 0:
        return None
    return math.log(bars[j + h].open / bars[j].open), bars[j + h].open_ms


@dataclass(frozen=True, slots=True)
class Fold:
    train: tuple[int, ...]
    test: tuple[int, ...]


def purged_splits(times: Sequence[int], label_end: Sequence[int], *, folds: int, min_train: int, embargo_ms: int
                  ) -> list[Fold]:
    """Expanding-window folds over rows sorted by time. A training row is kept only if its label ended before
    ``test_start - embargo_ms``."""
    n = len(times)
    if n != len(label_end) or any(b < a for a, b in itertools.pairwise(times)):
        raise ValueError("times must be sorted and match label_end")
    if any(to_ms(e) >= HOLDOUT_START_MS for e in label_end):
        raise ValueError("a label reaches into the holdout")
    if folds < 1 or min_train < 1 or min_train >= n:
        raise ValueError("bad fold settings")
    size = (n - min_train) // folds
    if size < 1:
        raise ValueError("too few rows for the requested folds")
    out = []
    for f in range(folds):
        lo = min_train + f * size
        hi = n if f == folds - 1 else lo + size
        cut = times[lo] - embargo_ms
        train = tuple(j for j in range(lo) if label_end[j] < cut)
        out.append(Fold(train, tuple(range(lo, hi))))
    return out


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("singular system")
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


@dataclass(frozen=True, slots=True)
class Ridge:
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float


def ridge_fit(x: Sequence[Sequence[float]], y: Sequence[float], lam: float) -> Ridge:
    """Ridge on standardised features (means and scales from the training rows only)."""
    if not x or len(x) != len(y):
        raise ValueError("x and y must be non-empty and of equal length")
    k = len(x[0])
    mean = [statistics.fmean(r[j] for r in x) for j in range(k)]
    scale = [statistics.pstdev([r[j] for r in x]) or 1.0 for j in range(k)]
    z = [[(r[j] - mean[j]) / scale[j] for j in range(k)] for r in x]
    ym = statistics.fmean(y)
    a = [[sum(r[i] * r[j] for r in z) + (lam if i == j else 0.0) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * (yy - ym) for r, yy in zip(z, y)) for i in range(k)]
    return Ridge(tuple(mean), tuple(scale), tuple(_solve(a, b)), ym)


def predict(model: Ridge, x: Sequence[Sequence[float]]) -> list[float]:
    return [model.intercept + sum(c * (v - m) / s for c, v, m, s in zip(model.coef, r, model.mean, model.scale))
            for r in x]


def _ranks(v: Sequence[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2.0
        i = j + 1
    return r


def spearman_ic(pred: Sequence[float], y: Sequence[float]) -> float | None:
    if len(pred) < 3:
        return None
    a, b = _ranks(pred), _ranks(y)
    sa, sb = statistics.pstdev(a), statistics.pstdev(b)
    if sa == 0 or sb == 0:
        return None
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    return sum((x - ma) * (z - mb) for x, z in zip(a, b)) / (len(a) * sa * sb)


def clark_west(y: Sequence[float], small: Sequence[float], big: Sequence[float]) -> float | None:
    """t-statistic of the Clark-West (2007) adjusted MSPE difference; > 1.645 = big model better at 5 % one-sided.
    Plain standard error: for overlapping labels use non-overlapping rows or a HAC error in the study."""
    f = [(yy - s) ** 2 - ((yy - b) ** 2 - (s - b) ** 2) for yy, s, b in zip(y, small, big)]
    if len(f) < 3:
        return None
    sd = statistics.stdev(f)
    return statistics.fmean(f) / (sd / math.sqrt(len(f))) if sd > 0 else None


def _finite(v) -> bool:
    try:
        return v is not None and not isinstance(v, bool) and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def compare(rows: Sequence[Mapping], groups: Mapping[str, Sequence[str]], *, label: str, folds: Sequence[Fold],
            lam: float = 1.0, models: Mapping[str, Sequence[str]] = MODELS) -> dict[str, dict]:
    """Out-of-sample predictions of each model on the same folds and the **same rows**. ``groups`` maps a group name
    ('price', ...) to feature keys in ``rows``. Rows need ``t_ms``, ``label_end_ms`` and the label. Any signal time or
    label end in the holdout stops the run. Rows where the label or any feature of any model is missing or not finite
    are left out for all models alike; their number is reported as ``_excluded``."""
    for r in rows:
        if to_ms(r["t_ms"]) >= HOLDOUT_START_MS or to_ms(r["label_end_ms"]) >= HOLDOUT_START_MS:
            raise ValueError("holdout rows must never reach the comparison")
    for fold in folds:  # folds must fit the rows and be purged: no train label may overlap the test span
        if any(not 0 <= i < len(rows) for i in (*fold.train, *fold.test)):
            raise ValueError("fold index outside rows")
        if fold.test:
            lo = min(to_ms(rows[i]["t_ms"]) for i in fold.test)
            hi = max(to_ms(rows[i]["label_end_ms"]) for i in fold.test)
            if any(to_ms(rows[i]["t_ms"]) <= hi and to_ms(rows[i]["label_end_ms"]) >= lo for i in fold.train):
                raise ValueError("fold is not purged: a train label overlaps the test span")
    used = {name: [k for g in gs for k in groups.get(g, ())] for name, gs in models.items()}
    used = {name: keys for name, keys in used.items() if keys}
    all_keys = {k for keys in used.values() for k in keys}
    ok = {i for i, r in enumerate(rows) if _finite(r.get(label)) and all(_finite(r.get(k)) for k in all_keys)}
    out: dict[str, dict] = {"_excluded": {"rows": len(rows) - len(ok), "of": len(rows)}}
    preds: dict[str, dict[int, float]] = {}
    for name, keys in used.items():
        p: dict[int, float] = {}
        for fold in folds:
            tr = [i for i in fold.train if i in ok]
            te = [i for i in fold.test if i in ok]
            if len(tr) <= len(keys) or not te:
                continue
            m = ridge_fit([[float(rows[i][k]) for k in keys] for i in tr], [float(rows[i][label]) for i in tr], lam)
            for i, v in zip(te, predict(m, [[float(rows[i][k]) for k in keys] for i in te]), strict=True):
                p[i] = v
        preds[name] = p
    common = set.intersection(*(set(p) for p in preds.values())) if preds else set()
    idx = sorted(common)
    ys = [float(rows[i][label]) for i in idx]
    for name, keys in used.items():
        out[name] = {"n": len(idx), "features": keys, "ic": spearman_ic([preds[name][i] for i in idx], ys)}
    base = preds.get("A0_price")
    if base:
        for name, p in preds.items():
            if name != "A0_price":
                out[name]["clark_west_t"] = clark_west(ys, [base[i] for i in idx], [p[i] for i in idx])
    return out
