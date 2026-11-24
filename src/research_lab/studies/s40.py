"""S40: does order flow or option flow predict the next 1 h / 4 h beyond price? (pre-registration 1.0, frozen 24.11.2026)

Spec: ``docs/research_lab/studien/S40_ORDERFLOW_OPTIONSFLOW_HISTORISCH_PRAEREGISTRIERUNG.md``. Input is the
output of ``s40_daten`` (5-minute bars, Deribit option trades, funding, ``datenreife.json``). Training 2020-2022,
validation 2023-2024 exactly once; the holdout from 2025-01-01 never enters (rows and label ends are checked).

    python -m src.research_lab.studies.s40 --phase train --daten ~/Documents/TIM/s40-data --aus ~/Documents/TIM/s40-out
    python -m src.research_lab.studies.s40 --phase validate --daten ... --aus ...   # only after a passed training

Standard library only. Nothing here places orders or touches a live service.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import itertools
import json
import math
import random
import re
import statistics
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.research_lab.fusion import of_features as off
from src.research_lab.fusion.historisch import LATENCY_MS, to_ms
from src.research_lab.fusion.of_features import Bar
from src.research_lab.fusion.walkforward import (
    Fold,
    predict,
    purged_splits,
    ridge_fit,
    spearman_ic,
)
from src.research_lab.options_flow.contract import Rejected, normalize_trade
from src.research_lab.options_flow.features_q import trade_greeks
from src.research_lab.protocol import (
    HOLDOUT_START_MS,
    STRESS_COSTS,
    VALIDATION_START_MS,
)
from src.research_lab.stats.deflated import deflated_sharpe

BAR_MS = 5 * 60_000
H_MS = 3_600_000
DAY_MS = 86_400_000
HORIZONS = {"1h": 1, "4h": 4}              # hours
Z_WINDOW, Z_MIN = 720, 480                 # previous full hours for z-scores, minimum valid values
MAX_LABEL_STRETCH = 1.10
FOLDS = 6
MIN_TRAIN_ROWS = {"1h": 4_320, "4h": 1_080}
MIN_OOS_ROWS = {"1h": 10_000, "4h": 2_500}
MIN_YEAR_ROWS = {"1h": 2_000, "4h": 500}
MAX_YEAR_SHARE = 0.60
RIDGE_LAMBDA = 1.0
ALPHA = 0.05
N_TESTS = 12
TRADE_THRESHOLD = 0.0020
BASE_ROUND_TRIP = 2 * (0.0006 + 0.0003)
STRESS_ROUND_TRIP = 2 * BASE_ROUND_TRIP
DSR_TRIALS = 8_106_956
MIN_TRADES = 300
BOOT_DRAWS, BOOT_SEED = 10_000, 40
CVD = {"lookback": 24, "right": 3, "k_sigma": 1.0}
SWEEP = {"lookback": 24, "m": 3, "min_excess": 0.001, "vol_mult": 2.0}
EVENT_BARS = 12
OPTIONS_START_MONTH: str | None = "2020-01"  # from S40_DATENREIFE.md (24.11.2026): Deribit 60/60 months valid

PRICE = ("ret_1h", "ret_4h", "ret_24h", "rv_24h", "hour_sin", "hour_cos")
ORDERFLOW = ("ai_1h", "ai_4h", "cvd_div", "sweep")
OPTIONSFLOW = ("daf_1h", "daf_24h", "gaf_1h", "gaf_24h")
RAW = {"hour_sin", "hour_cos", "cvd_div", "sweep"}   # not z-scored
GROUPS = {"price": PRICE, "orderflow": ORDERFLOW, "optionsflow": OPTIONSFLOW}
MODELS = {"A0": ("price",), "A1": ("price", "orderflow"), "A2": ("price", "optionsflow"),
          "A5": ("price", "orderflow", "optionsflow")}
TESTS = {  # id: (market, small, big, horizon)
    "T1": ("BTCUSDT", "A0", "A1", "1h"), "T2": ("BTCUSDT", "A0", "A1", "4h"),
    "T3": ("ETHUSDT", "A0", "A1", "1h"), "T4": ("ETHUSDT", "A0", "A1", "4h"),
    "T5": ("SOLUSDT", "A0", "A1", "1h"), "T6": ("SOLUSDT", "A0", "A1", "4h"),
    "T7": ("BTCUSDT", "A0", "A2", "1h"), "T8": ("BTCUSDT", "A0", "A2", "4h"),
    "T9": ("BTCUSDT", "A1", "A5", "1h"), "T10": ("BTCUSDT", "A1", "A5", "4h"),
    "T11": ("BTCUSDT", "A0", "A5", "1h"), "T12": ("BTCUSDT", "A0", "A5", "4h"),
}


def keys_of(model: str) -> tuple[str, ...]:
    return tuple(k for g in MODELS[model] for k in GROUPS[g])


def _month(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m")


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


# Loading -----------------------------------------------------------------------------------------------------------
def _before_holdout(name: str) -> bool:
    """File names carry their day or month (``2024-12-31...``/``...-2024-12.zip``); 2025 or later is never opened."""
    m = re.search(r"(\d{4})-(\d{2})", name)
    return bool(m) and int(m.group(1)) < 2025


def load_bars(root: Path, symbol: str) -> list[Bar]:
    out: list[Bar] = []
    for p in sorted((root / "bars" / symbol).glob("*.csv.gz")):
        if not _before_holdout(p.name):
            continue
        for r in csv.DictReader(io.StringIO(gzip.decompress(p.read_bytes()).decode())):
            t = to_ms(int(r["open_ms"]))
            if t >= HOLDOUT_START_MS:
                raise ValueError("holdout bar in the S40 data")
            known = max(int(r["last_ts_ms"]) + LATENCY_MS, t + BAR_MS)
            out.append(Bar(t, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                           float(r["buy"]), float(r["sell"]), known))
    out.sort(key=lambda b: b.open_ms)
    return out


@dataclass(frozen=True, slots=True)
class OptionFlow:
    """Per-trade taker delta and gamma (USD) at trade time, as prefix sums over exchange time."""
    ts: list[int]
    cum_delta: list[float]
    cum_gamma: list[float]
    valid_days: frozenset[str]

    def window(self, t_ms: int, span_ms: int) -> tuple[float, float]:
        """Sums over trades with ``t - span < ts`` and ``recv = ts + LATENCY_MS <= t`` (``features.visible``)."""
        lo = bisect.bisect_right(self.ts, t_ms - span_ms)
        hi = bisect.bisect_right(self.ts, t_ms - LATENCY_MS)
        if hi <= lo:
            return 0.0, 0.0
        return self.cum_delta[hi] - self.cum_delta[lo], self.cum_gamma[hi] - self.cum_gamma[lo]


def option_contributions(raw_rows: Sequence[Mapping[str, Any]]) -> list[tuple[int, float, float]]:
    """(ts, delta USD, gamma USD per 1 %) per usable trade. Blocks/combos, liquidations, no IV: left out."""
    out = []
    for raw in raw_rows:
        try:
            r = normalize_trade({k: v for k, v in raw.items() if k != "recv_ms"}, int(raw["recv_ms"]))
        except Rejected:
            continue
        if r["group_id"] or r["liquidation"]:
            continue
        g = trade_greeks(r)
        if g is None:
            continue
        s, a, sign = r["index_price"], r["amount"], 1 if r["side"] == "buy" else -1
        out.append((r["ts_ms"], sign * g[0] * a * s, sign * g[1] * a * s * s * 0.01))
    return out


def build_option_flow(contribs: Sequence[tuple[int, float, float]], valid_days: set[str]) -> OptionFlow:
    contribs = sorted(contribs)
    cd, cg = [0.0], [0.0]
    for _, d, g in contribs:
        cd.append(cd[-1] + d)
        cg.append(cg[-1] + g)
    return OptionFlow([c[0] for c in contribs], cd, cg, frozenset(valid_days))


def load_option_flow(root: Path, start_month: str) -> OptionFlow:
    valid_days: set[str] = set()
    buckets: dict[int, tuple[float, float]] = {}
    status = root / "status" / "deribit"
    for p in sorted((root / "deribit").glob("*.jsonl.gz")):
        if not _before_holdout(p.name):
            continue
        day = p.name.split(".")[0]
        st_path = status / f"{day}.json"
        st = json.loads(st_path.read_text()) if st_path.exists() else {}
        if st.get("ok") and st.get("trades", 0) >= 50 and day[:7] >= start_month:
            valid_days.add(day)
        rows = [json.loads(x) for x in gzip.decompress(p.read_bytes()).splitlines() if x.strip()]
        for ts, d, g in option_contributions(rows):  # one bucket per second keeps memory small and stays exact
            k = -(-ts // 1000) * 1000                    # ceil to the second: lo < ts <= hi  <=>  lo < k <= hi
            prev = buckets.get(k, (0.0, 0.0))
            buckets[k] = (prev[0] + d, prev[1] + g)
    return build_option_flow([(k, d, g) for k, (d, g) in buckets.items()], valid_days)


def load_funding(root: Path, symbol: str) -> list[tuple[int, float]]:
    out = []
    for p in sorted((root / "funding" / symbol).glob("*.zip")):
        if not _before_holdout(p.name):
            continue
        with zipfile.ZipFile(p) as z:
            for name in z.namelist():
                for row in csv.reader(io.StringIO(z.read(name).decode())):
                    if row and row[0].strip().isdigit():
                        out.append((to_ms(int(row[0])), float(row[2])))
    return sorted(out)


# Features ----------------------------------------------------------------------------------------------------------
class FastOF:
    """Incremental versions of ``of_features.cvd_divergence`` (prefix CVD, precomputed swings); tested equal."""

    def __init__(self, bars: Sequence[Bar], right: int = CVD["right"]) -> None:
        self.bars, self.right = bars, right
        self.cvd = list(itertools.accumulate(b.delta for b in bars))
        n = len(bars)
        sh, sl = [False] * n, [False] * n
        for j in range(right, n - right):
            hi, lo = bars[j].high, bars[j].low
            side = [k for k in range(j - right, j + right + 1) if k != j]
            sh[j] = all(hi > bars[k].high for k in side)
            sl[j] = all(lo < bars[k].low for k in side)
        self.last_sh, self.last_sl = [-1] * n, [-1] * n
        a = b_ = -1
        for i in range(n):
            j = i - right
            if j >= 0:
                a = j if sh[j] else a
                b_ = j if sl[j] else b_
            self.last_sh[i], self.last_sl[i] = a, b_

    def cvd_divergence(self, i: int, *, lookback: int = CVD["lookback"], k_sigma: float = CVD["k_sigma"]) -> int:
        bars = self.bars
        if i < lookback + 1:
            return 0
        deltas = [b.delta for b in bars[max(0, i - lookback): i + 1]]
        sd = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
        now = self.cvd[i]
        prev_high = max(b.high for b in bars[i - lookback: i])
        prev_low = min(b.low for b in bars[i - lookback: i])
        if bars[i].high > prev_high and self.last_sh[i] >= 0 and now < self.cvd[self.last_sh[i]] - k_sigma * sd:
            return -1
        if bars[i].low < prev_low and self.last_sl[i] >= 0 and now > self.cvd[self.last_sl[i]] + k_sigma * sd:
            return 1
        return 0


def last_event(fn, i: int, n_bars: int = EVENT_BARS) -> int:
    """Value of the most recent of the last ``n_bars`` bars (ending at i) where ``fn`` is non-zero, else 0."""
    for j in range(i, max(-1, i - n_bars), -1):
        v = fn(j)
        if v:
            return v
    return 0


def raw_features(bars: Sequence[Bar], opens: Sequence[int], t_ms: int, fast: FastOF, opt: OptionFlow | None
                 ) -> dict[str, float | None] | None:
    """Unnormalised features at prediction time t (only bars known by t). None if no bar is known."""
    i = bisect.bisect_right(opens, t_ms - BAR_MS) - 1
    while i >= 0 and bars[i].known_ms > t_ms:
        i -= 1
    if i < 0 or bars[i].open_ms < t_ms - 3 * BAR_MS:  # last known bar older than 10 min: no row
        return None
    out: dict[str, float | None] = {}
    c = bars[i].close
    for name, w in (("ret_1h", H_MS), ("ret_4h", 4 * H_MS), ("ret_24h", DAY_MS)):
        k = bisect.bisect_right(opens, t_ms - w - BAR_MS) - 1
        out[name] = math.log(c / bars[k].close) if 0 <= k < i and bars[k].close > 0 and c > 0 else None
    lo = i - 287
    if lo >= 1:
        out["rv_24h"] = math.sqrt(sum(math.log(bars[j].close / bars[j - 1].close) ** 2 for j in range(lo, i + 1)))
    else:
        out["rv_24h"] = None
    hour = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).hour
    out["hour_sin"], out["hour_cos"] = math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)
    for name, w in (("ai_1h", H_MS), ("ai_4h", 4 * H_MS)):
        k0 = bisect.bisect_left(opens, t_ms - w)
        buy = sum(b.buy for b in bars[k0: i + 1])
        sell = sum(b.sell for b in bars[k0: i + 1])
        out[name] = (buy - sell) / (buy + sell) if buy + sell > 0 else None
    out["cvd_div"] = float(last_event(fast.cvd_divergence, i))
    out["sweep"] = float(last_event(lambda j: off.sweep(bars, j, **SWEEP), i))
    if opt is not None:
        days_needed = {_day(t_ms - DAY_MS), _day(t_ms - 1)}
        if days_needed <= opt.valid_days:
            for span, tag in ((H_MS, "1h"), (DAY_MS, "24h")):
                d, g = opt.window(t_ms, span)
                out[f"daf_{tag}"], out[f"gaf_{tag}"] = d, g
    return out


def zscore_series(times: Sequence[int], values: Sequence[float | None]) -> list[float | None]:
    """z-value of each hourly value against the previous ``Z_WINDOW`` hours (t itself excluded)."""
    out: list[float | None] = []
    for n, (t, v) in enumerate(zip(times, values, strict=True)):
        lo = bisect.bisect_left(times, t - Z_WINDOW * H_MS, 0, n)
        hist = [x for x in values[lo:n] if x is not None]
        if v is None or len(hist) < Z_MIN:
            out.append(None)
            continue
        sd = statistics.pstdev(hist)
        out.append((v - statistics.fmean(hist)) / sd if sd > 0 else None)
    return out


def label(bars: Sequence[Bar], opens: Sequence[int], t_ms: int, hours: int) -> tuple[float, int, int] | None:
    """(log return, entry open_ms, exit open_ms): entry at the first bar opening at or after t (all features are
    known by t) and before t + 5 min, exit at the open h hours of bars later; the stretch is measured from t.
    None if missing or stretched by gaps more than 10 %."""
    j = bisect.bisect_left(opens, t_ms)
    n_bars = hours * H_MS // BAR_MS
    if j + n_bars >= len(bars):
        return None
    a, b = bars[j], bars[j + n_bars]
    if a.open_ms >= t_ms + BAR_MS:  # the bar right after t is missing: no entry
        return None
    if a.open <= 0 or b.open <= 0 or b.open_ms - t_ms > MAX_LABEL_STRETCH * hours * H_MS:
        return None
    return math.log(b.open / a.open), a.open_ms, b.open_ms


def build_rows(bars: Sequence[Bar], opt: OptionFlow | None, valid_months: set[str], start_ms: int, end_ms: int
               ) -> dict[str, list[dict[str, Any]]]:
    """Hourly feature rows (z-scored) and the 1 h / 4 h label rows. Rows touching an invalid month are dropped."""
    fast = FastOF(bars)
    opens = [b.open_ms for b in bars]
    times = list(range(start_ms - start_ms % H_MS, min(end_ms, HOLDOUT_START_MS), H_MS))
    raw = [raw_features(bars, opens, t, fast, opt) or {} if _month(t) in valid_months and _month(t - DAY_MS)
           in valid_months else {} for t in times]  # values from invalid months never enter a z window
    keys = PRICE + ORDERFLOW + (OPTIONSFLOW if opt is not None else ())
    cols = {k: [r.get(k) for r in raw] for k in keys}
    for k in keys:
        if k not in RAW:
            cols[k] = zscore_series(times, cols[k])
    out: dict[str, list[dict[str, Any]]] = {"1h": [], "4h": []}
    dropped = {h: {"no_label": 0, "past_end": 0, "invalid_month": 0} for h in HORIZONS}
    for n, t in enumerate(times):
        for h, hours in HORIZONS.items():
            if hours == 4 and datetime.fromtimestamp(t / 1000, tz=timezone.utc).hour % 4:
                continue
            lab = label(bars, opens, t, hours)
            if lab is None:
                dropped[h]["no_label"] += 1
                continue
            y, entry, exit_ = lab
            if exit_ >= min(end_ms, HOLDOUT_START_MS) or t >= HOLDOUT_START_MS:
                dropped[h]["past_end"] += 1
                continue
            if not {_month(t - DAY_MS), _month(t), _month(exit_)} <= valid_months:
                dropped[h]["invalid_month"] += 1
                continue
            out[h].append({"t_ms": t, "entry_ms": entry, "label_end_ms": exit_, "y": y,
                           **{k: cols[k][n] for k in keys}})
    out["_dropped"] = dropped  # type: ignore[assignment]
    return out


# Evaluation --------------------------------------------------------------------------------------------------------
def _ok(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def usable(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[Mapping[str, Any]]:
    return [r for r in rows if _ok(r["y"]) and all(_ok(r.get(k)) for k in keys)]


def oos_predictions(rows: Sequence[Mapping[str, Any]], keys: Sequence[str], folds: Sequence[Fold]) -> dict[int, float]:
    p: dict[int, float] = {}
    for f in folds:
        if len(f.train) <= len(keys) or not f.test:
            continue
        m = ridge_fit([[float(rows[i][k]) for k in keys] for i in f.train], [rows[i]["y"] for i in f.train], RIDGE_LAMBDA)
        for i, v in zip(f.test, predict(m, [[float(rows[i][k]) for k in keys] for i in f.test]), strict=True):
            p[i] = v
    return p


def newey_west_lag(n: int) -> int:
    return int(4 * (n / 100) ** (2 / 9))


def cw_terms(y: Sequence[float], small: Sequence[float], big: Sequence[float]) -> list[float]:
    return [(a - s) ** 2 - ((a - b) ** 2 - (s - b) ** 2) for a, s, b in zip(y, small, big, strict=True)]


def clark_west_hac(y: Sequence[float], small: Sequence[float], big: Sequence[float]) -> tuple[float | None, float | None]:
    """(t, one-sided p) of Clark-West with a Newey-West (Bartlett) standard error, lag ``newey_west_lag(n)``."""
    f = cw_terms(y, small, big)
    n = len(f)
    if n < 10:
        return None, None
    mu = statistics.fmean(f)
    d = [x - mu for x in f]
    var = sum(x * x for x in d) / n
    for lag in range(1, newey_west_lag(n) + 1):
        w = 1 - lag / (newey_west_lag(n) + 1)
        var += 2 * w * sum(d[i] * d[i - lag] for i in range(lag, n)) / n
    if var <= 0:
        return None, None
    t = mu / math.sqrt(var / n)
    return t, 0.5 * math.erfc(t / math.sqrt(2))


def year_rule(times: Sequence[int], f: Sequence[float], min_rows: int) -> dict[str, Any]:
    by: dict[int, list[float]] = {}
    for t, x in zip(times, f, strict=True):
        by.setdefault(datetime.fromtimestamp(t / 1000, tz=timezone.utc).year, []).append(x)
    years = {y: sum(v) for y, v in by.items() if len(v) >= min_rows}
    total = sum(f)
    positive = sum(1 for v in years.values() if v > 0)
    need = min(len(years), 2)
    share_ok = total > 0 and all(v / total <= MAX_YEAR_SHARE for v in years.values() if v > 0) if years else False
    return {"years": {str(k): v for k, v in sorted(years.items())}, "positive": positive,
            "ok": len(years) >= 2 and positive >= need and share_ok}


def holm_p(p: Mapping[str, float | None], m: int = N_TESTS) -> dict[str, float]:
    """Holm-adjusted p-values; missing tests count as p = 1."""
    items = sorted(((v if v is not None else 1.0), k) for k, v in p.items())
    out, running = {}, 0.0
    for rank, (v, k) in enumerate(items):
        running = max(running, min(1.0, (m - rank) * v))
        out[k] = running
    return out


def evaluate_train(rows: Sequence[Mapping[str, Any]], small: str, big: str, h: str) -> dict[str, Any]:
    ks, kb = keys_of(small), keys_of(big)
    rows = usable(rows, kb)  # big model holds every key of the small one
    for r in rows:
        if r["t_ms"] >= VALIDATION_START_MS or r["label_end_ms"] >= VALIDATION_START_MS:
            raise ValueError("training evaluation got a validation or holdout row")
    if len(rows) <= MIN_TRAIN_ROWS[h] + FOLDS:
        return {"status": "nicht prüfbar", "n_rows": len(rows)}
    times = [r["t_ms"] for r in rows]
    folds = purged_splits(times, [r["label_end_ms"] for r in rows], folds=FOLDS, min_train=MIN_TRAIN_ROWS[h],
                          embargo_ms=HORIZONS[h] * H_MS + DAY_MS + LATENCY_MS)
    ps, pb = oos_predictions(rows, ks, folds), oos_predictions(rows, kb, folds)
    idx = sorted(set(ps) & set(pb))
    y = [rows[i]["y"] for i in idx]
    s, b = [ps[i] for i in idx], [pb[i] for i in idx]
    t, p = clark_west_hac(y, s, b)
    ic_s, ic_b = spearman_ic(s, y), spearman_ic(b, y)
    yr = year_rule([rows[i]["t_ms"] for i in idx], cw_terms(y, s, b), MIN_YEAR_ROWS[h])
    return {"n_oos": len(idx), "cw_t": t, "cw_p": p, "ic_small": ic_s, "ic_big": ic_b, "years": yr,
            "testable": len(idx) >= MIN_OOS_ROWS[h]}


def train_verdicts(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    adj = holm_p({k: (v.get("cw_p") if v.get("testable") else None) for k, v in results.items()})
    out = {}
    for k, v in results.items():
        if not v.get("testable"):
            out[k] = {"verdict": "nicht prüfbar", "holm_p": adj.get(k)}
            continue
        ok = (adj[k] <= ALPHA and v["ic_big"] is not None and v["ic_small"] is not None
              and v["ic_big"] > v["ic_small"] and v["ic_big"] > 0 and v["years"]["ok"])
        out[k] = {"verdict": "bestanden" if ok else "nicht bestanden", "holm_p": adj[k]}
    return out


def coef_hash(model) -> str:
    return hashlib.sha256(json.dumps([model.mean, model.scale, model.coef, model.intercept]).encode()).hexdigest()


def evaluate_validation(rows: Sequence[Mapping[str, Any]], small: str, big: str, h: str) -> dict[str, Any]:
    ks, kb = keys_of(small), keys_of(big)
    rows = usable(rows, kb)
    emb = HORIZONS[h] * H_MS + DAY_MS + LATENCY_MS
    train = [r for r in rows if r["label_end_ms"] < VALIDATION_START_MS - emb]
    valid = [r for r in rows if VALIDATION_START_MS <= r["t_ms"] and r["label_end_ms"] < HOLDOUT_START_MS]
    if any(r["t_ms"] >= HOLDOUT_START_MS for r in valid):
        raise ValueError("holdout row reached the validation")
    if len(valid) < MIN_OOS_ROWS[h] or len(train) <= len(kb):
        return {"status": "nicht prüfbar", "n_valid": len(valid)}
    ms = ridge_fit([[r[k] for k in ks] for r in train], [r["y"] for r in train], RIDGE_LAMBDA)
    mb = ridge_fit([[r[k] for k in kb] for r in train], [r["y"] for r in train], RIDGE_LAMBDA)
    s = predict(ms, [[r[k] for k in ks] for r in valid])
    b = predict(mb, [[r[k] for k in kb] for r in valid])
    y = [r["y"] for r in valid]
    t, p = clark_west_hac(y, s, b)
    return {"n_valid": len(valid), "cw_t": t, "cw_p": p, "ic_small": spearman_ic(s, y), "ic_big": spearman_ic(b, y),
            "coef_sha256": {small: coef_hash(ms), big: coef_hash(mb)}, "predictions": b, "rows": valid}


# Trading check -----------------------------------------------------------------------------------------------------
def trade_returns(rows: Sequence[Mapping[str, Any]], preds: Sequence[float], funding: Sequence[tuple[int, float]],
                  round_trip: float, credits: bool) -> list[tuple[int, float]]:
    """(entry_ms, net return) per trade: |prediction| > threshold, direction = sign, exit after h, no stop.
    Funding at every funding time with entry < time <= exit; long pays a positive rate."""
    times = [f[0] for f in funding]
    out = []
    for r, p in zip(rows, preds, strict=True):
        if abs(p) <= TRADE_THRESHOLD:
            continue
        side = 1 if p > 0 else -1
        gross = side * (math.exp(r["y"]) - 1)
        lo, hi = bisect.bisect_right(times, r["entry_ms"]), bisect.bisect_right(times, r["label_end_ms"])
        flows = [-side * rate for _, rate in funding[lo:hi]]
        fund = sum(flows) if credits else sum(min(0.0, x) for x in flows)
        out.append((r["entry_ms"], gross - round_trip + fund))
    return out


def week_bootstrap_lower(trades: Sequence[tuple[int, float]], draws: int = BOOT_DRAWS, seed: int = BOOT_SEED,
                         q: float = 0.05) -> float | None:
    weeks: dict[tuple[int, int], list[float]] = {}
    for t, x in trades:
        iso = datetime.fromtimestamp(t / 1000, tz=timezone.utc).isocalendar()
        weeks.setdefault((iso[0], iso[1]), []).append(x)
    blocks = list(weeks.values())
    if len(blocks) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        pick = [rng.choice(blocks) for _ in blocks]
        flat = [x for b in pick for x in b]
        means.append(statistics.fmean(flat))
    means.sort()
    return means[int(q * draws)]


def trading_check(rows, preds, funding) -> dict[str, Any]:
    base = trade_returns(rows, preds, funding, BASE_ROUND_TRIP, credits=True)
    stress = trade_returns(rows, preds, funding, STRESS_ROUND_TRIP, credits=False)
    proto = trade_returns(rows, preds, funding, 2 * (STRESS_COSTS.fee + STRESS_COSTS.slippage), credits=False)
    if len(base) < MIN_TRADES:
        return {"verdict": "nicht prüfbar", "n": len(base)}
    xs = [x for _, x in base]
    lower = week_bootstrap_lower(base)
    try:
        dsr: float | None = deflated_sharpe(xs, DSR_TRIALS).dsr
    except ValueError:  # degenerate moments: counted as not passed
        dsr = None
    ok = statistics.fmean(xs) > 0 and lower is not None and lower > 0 and statistics.fmean(x for _, x in stress) > 0 \
        and dsr is not None and dsr >= 0.95
    return {"n": len(base), "mean": statistics.fmean(xs), "boot_lower_90": lower,
            "mean_stress": statistics.fmean(x for _, x in stress),
            "mean_protocol_stress": statistics.fmean(x for _, x in proto), "dsr": dsr,
            "verdict": "bestanden" if ok else "nicht bestanden"}


# CLI ---------------------------------------------------------------------------------------------------------------
def _valid_months(report: Mapping[str, Any], symbol: str) -> set[str]:
    return {k for k, v in report["binance"][symbol]["months"].items() if v["valid"]}


def options_start(report: Mapping[str, Any]) -> str | None:
    """Start month of the option-flow tests, or None when Deribit fails the 70 % rule (T7-T12 not testable)."""
    d = report.get("deribit", {})
    if not d.get("testable"):
        return None
    return OPTIONS_START_MONTH or d.get("first_valid_month")


def _rows_for(root: Path, report: Mapping[str, Any], symbol: str, with_options: bool, end_ms: int):
    bars = load_bars(root, symbol)
    start = options_start(report) if with_options else None
    opt = load_option_flow(root, start) if start else None
    return build_rows(bars, opt, _valid_months(report, symbol), bars[0].open_ms + 21 * DAY_MS, end_ms)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="S40 study run")
    ap.add_argument("--phase", choices=["train", "validate"], required=True)
    ap.add_argument("--daten", type=Path, required=True)
    ap.add_argument("--aus", type=Path, required=True)
    a = ap.parse_args(argv)
    root, out = a.daten.expanduser(), a.aus.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    report = json.loads((root / "datenreife.json").read_text())
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    data_sha = hashlib.sha256((root / "datenreife.json").read_bytes()).hexdigest()
    if a.phase == "train" and (out / "s40_train.json").exists():
        raise SystemExit("training already ran; a new run needs a new study version")
    if a.phase == "validate":
        train = json.loads((out / "s40_train.json").read_text())
        if train.get("code_sha256") != code_sha or train.get("data_sha256") != data_sha:
            raise SystemExit("code or data changed since the training run; validation refused")
        if (out / "s40_validate.json").exists():
            raise SystemExit("validation already ran once; S40 allows exactly one run")
        passed = [k for k, v in train["verdicts"].items() if v["verdict"] == "bestanden"]
        if not passed:
            print("keine Tests im Training bestanden, Validierung entfällt")
            return 0
    end = VALIDATION_START_MS if a.phase == "train" else HOLDOUT_START_MS
    cache: dict[str, dict[str, list]] = {}
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        if report["binance"][sym]["testable"]:
            cache[sym] = _rows_for(root, report, sym, sym == "BTCUSDT", end)
    if a.phase == "train":
        res = {}
        for tid, (sym, small, big, h) in TESTS.items():
            if sym not in cache or (big in ("A2", "A5") and options_start(report) is None):
                res[tid] = {"status": "nicht prüfbar"}
                continue
            res[tid] = evaluate_train(cache[sym][h], small, big, h)
        verdicts = train_verdicts(res)
        (out / "s40_train.json").write_text(json.dumps({"code_sha256": code_sha, "data_sha256": data_sha,
                                                        "options_start": options_start(report),
                                                        "dropped": {k: v["_dropped"] for k, v in cache.items()},
                                                        "tests": res, "verdicts": verdicts},
                                                       indent=2, default=str) + "\n")
        print(json.dumps(verdicts, indent=2))
        return 0
    res = {}
    for tid in passed:
        sym, small, big, h = TESTS[tid]
        res[tid] = evaluate_validation(cache[sym][h], small, big, h)
    adj = holm_p({k: v.get("cw_p") for k, v in res.items()}, m=len(passed))
    for k, v in res.items():
        tr = train["tests"][k]
        same_dir = (v.get("ic_big") or 0) - (v.get("ic_small") or 0) > 0 and (tr["ic_big"] - tr["ic_small"]) > 0
        v["holm_p"] = adj[k]
        v["verdict"] = "bestanden" if "cw_p" in v and adj[k] <= ALPHA and same_dir else "nicht bestanden"
        if v["verdict"] == "bestanden":
            v["trading"] = trading_check(v["rows"], v["predictions"], load_funding(root, TESTS[k][0]))
        v.pop("rows", None)
        v.pop("predictions", None)
    (out / "s40_validate.json").write_text(json.dumps({"code_sha256": code_sha, "data_sha256": data_sha, "tests": res}, indent=2, default=str) + "\n")
    print(json.dumps({k: v["verdict"] for k, v in res.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
