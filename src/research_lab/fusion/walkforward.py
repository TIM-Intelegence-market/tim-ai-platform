"""P4: test scaffold for the comparison models A0-A6 (plan sections 7 and 8). No real data, no results.

- ``forward_label``: future return from the open of bar i+1 to the open of bar i+1+h (entry after the signal).
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


def forward_label(opens: Sequence[float], i: int, h: int) -> float | None:
    """Log return from open[i+1] to open[i+1+h]; None at the end of the series."""
    if i + 1 + h >= len(opens) or opens[i + 1] <= 0 or opens[i + 1 + h] <= 0:
        return None
    return math.log(opens[i + 1 + h] / opens[i + 1])


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


def compare(rows: Sequence[Mapping], groups: Mapping[str, Sequence[str]], *, label: str, folds: Sequence[Fold],
            lam: float = 1.0, models: Mapping[str, Sequence[str]] = MODELS) -> dict[str, dict]:
    """Out-of-sample predictions of each model on the same folds. ``groups`` maps a group name ('price', ...) to the
    feature keys in ``rows``. Rows need ``t_ms`` and the label; any row in the holdout stops the run."""
    if any(int(r["t_ms"]) >= HOLDOUT_START_MS for r in rows):
        raise ValueError("holdout rows must never reach the comparison")
    out: dict[str, dict] = {}
    preds: dict[str, dict[int, float]] = {}
    for name, gs in models.items():
        keys = [k for g in gs for k in groups.get(g, ())]
        if not keys:
            continue
        p: dict[int, float] = {}
        for fold in folds:
            tr = [i for i in fold.train if rows[i].get(label) is not None]
            te = [i for i in fold.test if rows[i].get(label) is not None]
            if len(tr) <= len(keys) or not te:
                continue
            m = ridge_fit([[float(rows[i][k]) for k in keys] for i in tr], [float(rows[i][label]) for i in tr], lam)
            for i, v in zip(te, predict(m, [[float(rows[i][k]) for k in keys] for i in te])):
                p[i] = v
        preds[name] = p
        idx = sorted(p)
        ys = [float(rows[i][label]) for i in idx]
        out[name] = {"n": len(idx), "features": keys, "ic": spearman_ic([p[i] for i in idx], ys)}
    base = preds.get("A0_price")
    if base:
        for name, p in preds.items():
            if name == "A0_price":
                continue
            idx = sorted(set(p) & set(base))
            out[name]["clark_west_t"] = clark_west([float(rows[i][label]) for i in idx],
                                                   [base[i] for i in idx], [p[i] for i in idx])
    return out
