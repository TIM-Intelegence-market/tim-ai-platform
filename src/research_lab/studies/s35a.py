"""S35a - Level plus Orderflow-Bestaetigung (Delta), Rueckprall und Ausbruch, BTC/ETH/SOL (Praeregistrierung 1.0).

Rules frozen in docs/research_lab/studien/S35A_LEVEL_ORDERFLOW_PRAEREGISTRIERUNG.md. Gamma/GEX is not part of this study.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from src.research_lab.orderflow_ml.profile import value_area
from src.research_lab.studies.minute_sim import (MINUTE_MS, Funding, Minutes, Trade, bootstrap_lower, days, leave_one_year_out, mean,
                                                 simulate, summary)

GRID = 0.001
TOL = 0.0005             # touch tolerance around a level
BREAK = 0.0005           # close beyond the level for a breakout
DELTA_MIN = 0.10         # |candle delta| / candle volume
STOP_PAD_BOUNCE = 0.0005
STOP_PAD_BREAK = 0.001
MIN_RISK = 0.005
TARGET_R = 2.0
TIME_STOP_MIN = 360
SIGMA = 2.0
MIN_DAY_MIN = 60
CLASSES = ("E", "V", "P")   # Extremmarken, VWAP-Baender, Volumenprofil Vortag
MODES = ("bounce", "break")
TFS = (5, 15)
CONFIGS = [f"{c}-{m}-{t}m" for c in CLASSES for m in MODES for t in TFS]   # 12
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SOL_START = date(2020, 9, 1)         # perpetual funding exists from Sep 2020
TRAIN = (date(2020, 1, 1), date(2022, 12, 31))
VALID = (date(2023, 1, 1), date(2024, 12, 31))


def gidx(p: float) -> int:
    return math.floor(math.log(p) / GRID)


def hl(m: Minutes, i0: int, i1: int):
    """(high, low) of minutes [i0, i1) or None when fewer than 90 % of them traded (or outside the grid)."""
    if i0 < 0 or i1 > m.n or sum(m.valid[i0:i1]) < 0.9 * (i1 - i0):
        return None
    return max(m.high[i0:i1]), min(m.low[i0:i1])


def month_start(d: date) -> date:
    return d.replace(day=1)


def static_levels(m: Minutes, d: date) -> list[float]:
    """Previous-day, previous-week (Mon-Sun) and previous-month high/low, all complete before ``d``."""
    out: list[float] = []

    def idx(day: date) -> int:
        return (day - m.first).days * 1440

    def add(a: date, b: date):          # [a, b)
        r = hl(m, idx(a), idx(b))
        if r:
            out.extend(r)
    add(d - timedelta(days=1), d)
    wk = d - timedelta(days=d.weekday())
    add(wk - timedelta(days=7), wk)
    ms = month_start(d)
    add(month_start(ms - timedelta(days=1)), ms)
    return out


def profile_levels(m: Minutes, d: date) -> list[float]:
    """POC, VAH (upper edge) and VAL (lower edge) of the previous UTC day's volume profile on the 0.1 % log grid."""
    hist: dict[int, int] = {}
    for _min, price, vol in m.day_profile(d - timedelta(days=1)):
        k = gidx(price)
        hist[k] = hist.get(k, 0) + int(round(vol * 1e4))
    va = value_area(hist)
    if va is None:
        return []
    poc, val, vah = va
    return [math.exp((poc + 0.5) * GRID), math.exp((vah + 1) * GRID), math.exp(val * GRID)]


def find_signals(m: Minutes, first: date, last: date, tf: int) -> dict[str, list[dict]]:
    """Signals per config key (class-mode) for this timeframe. One signal per config, UTC day and direction."""
    out: dict[str, list[dict]] = {f"{c}-{md}": [] for c in CLASSES for md in MODES}
    for d in days(first, last):
        base = (d - m.first).days * 1440
        if base < 1440 or base + 1440 > m.n:
            continue
        lv_e = static_levels(m, d)
        lv_p = profile_levels(m, d)
        sv = sp = spp = 0.0
        p_ref = m.close[base]
        seen: set[tuple[str, int]] = set()
        prev_close = m.close[base - 1]
        for c in range(1440 // tf):
            a, b = base + c * tf, base + c * tf + tf
            lv_v: list[float] = []
            if c * tf >= MIN_DAY_MIN and sv > 0:
                vw = p_ref + sp / sv
                var = spp / sv - (sp / sv) ** 2
                if var > 0:
                    sd = math.sqrt(var)
                    lv_v = [vw + SIGMA * sd, vw - SIGMA * sd]
            hi, lo, close = max(m.high[a:b]), min(m.low[a:b]), m.close[b - 1]
            bq, sq = sum(m.buy_q[a:b]), sum(m.sell_q[a:b])
            delta = (bq - sq) / (bq + sq) if bq + sq > 0 else 0.0
            for cls, levels in (("E", lv_e), ("V", lv_v), ("P", lv_p)):
                for L in levels:
                    if not (lo <= L * (1 + TOL) and hi >= L * (1 - TOL)):
                        continue
                    support = prev_close > L
                    cand = []
                    if (support and close >= L and delta >= DELTA_MIN) or (not support and close <= L and delta <= -DELTA_MIN):
                        cand.append(("bounce", 1 if support else -1))
                    if support and close <= L * (1 - BREAK) and delta <= -DELTA_MIN:
                        cand.append(("break", -1))
                    if not support and close >= L * (1 + BREAK) and delta >= DELTA_MIN:
                        cand.append(("break", 1))
                    for mode, direction in cand:
                        key = (f"{cls}-{mode}", direction)
                        if key in seen or b >= m.n:
                            continue
                        seen.add(key)
                        if mode == "bounce":
                            raw = lo * (1 - STOP_PAD_BOUNCE) if direction > 0 else hi * (1 + STOP_PAD_BOUNCE)
                        else:
                            raw = L * (1 - STOP_PAD_BREAK) if direction > 0 else L * (1 + STOP_PAD_BREAK)
                        out[key[0]].append({"direction": direction, "i_entry": b, "raw_stop": raw, "signal_ms": m.t0 + b * MINUTE_MS,
                                            "level": L})
            for i in range(a, b):
                v = m.base[i]
                if v > 0:
                    pm = (m.buy_q[i] + m.sell_q[i]) / v - p_ref
                    sv += v
                    sp += v * pm
                    spp += v * pm * pm
            prev_close = close
    return out


def to_trade(m: Minutes, funding: Funding, sym: str, s: dict, tag: str) -> Trade | None:
    e, dr = m.open[s["i_entry"]], s["direction"]
    risk = max(abs(e - s["raw_stop"]) / e, MIN_RISK)
    stop = e * (1 - dr * risk)
    return simulate(m, funding, sym, dr, s["i_entry"], stop, e * (1 + dr * TARGET_R * risk), TIME_STOP_MIN, s["signal_ms"], tag)


def collect(bars_roots: dict[str, str], funding_root: str, first: date, last: date) -> dict[str, list[Trade]]:
    """Trades per config id over all markets for [first, last]."""
    trades: dict[str, list[Trade]] = {c: [] for c in CONFIGS}
    for sym in SYMBOLS:
        f0 = max(first, SOL_START) if sym == "SOLUSDT" else first
        g0 = max(f0 - timedelta(days=70), date(2020, 1, 1) if sym != "SOLUSDT" else date(2020, 8, 11))
        m = Minutes(bars_roots[sym], sym, g0, last)
        fund = Funding(funding_root, sym, g0 if sym != "SOLUSDT" else SOL_START, last)
        for tf in TFS:
            for key, sigs in find_signals(m, f0, last, tf).items():
                for s in sigs:
                    t = to_trade(m, fund, sym, s, f"{key}-{tf}m")
                    if t is not None:
                        trades[f"{key}-{tf}m"].append(t)
    return trades


def holm_adjusted(p: dict[str, float], m: int) -> dict[str, float]:
    order = sorted(p, key=lambda k: (p[k], k))
    adj, run = {}, 0.0
    for r, k in enumerate(order):
        run = max(run, min(1.0, (m - r) * p[k]))
        adj[k] = run
    return adj


def random_p(ms: dict[str, Minutes], fundings: dict[str, Funding], trades: list[Trade], first: date, draws: int = 1000, seed: int = 35) -> dict:
    rng = random.Random(seed)
    el = {s: [i for i in range(max(0, (first - ms[s].first).days * 1440), ms[s].n - TIME_STOP_MIN) if i % 5 == 0] for s in ms}
    real = mean([t.net_r for t in trades])
    means = []
    for _ in range(draws):
        res = []
        for t in trades:
            m = ms[t.symbol]
            for _try in range(20):
                i = el[t.symbol][rng.randrange(len(el[t.symbol]))]
                e = m.open[i]
                x = simulate(m, fundings[t.symbol], t.symbol, t.direction, i, e * (1 - t.direction * t.stop_frac),
                             e * (1 + t.direction * t.target_frac), TIME_STOP_MIN, m.t0 + i * MINUTE_MS)
                if x is not None:
                    res.append(x.net_r)
                    break
        means.append(mean(res))
    return {"real": real, "p": (1 + sum(1 for x in means if x >= real)) / (draws + 1), "draws": draws}


def run(phase: str, bars_roots, funding_root, out: Path, train_result: Path | None = None) -> int:
    first, last = TRAIN if phase == "train" else VALID
    allowed = CONFIGS
    if phase == "valid":
        tr = json.loads(train_result.read_text())
        allowed = [c for c, v in tr["configs"].items() if v.get("training_passed")]
        if not allowed:
            print("Validierung gesperrt: keine Konfiguration hat das Training bestanden.", file=sys.stderr)
            return 2
    trades = collect(bars_roots, funding_root, first, last)
    res: dict = {"studie": "S35a", "phase": phase, "von": first.isoformat(), "bis": last.isoformat(), "configs": {}}
    total_days = (last - first).days + 1
    for c in CONFIGS:
        ts = trades[c]
        v = summary(ts)
        v["signale_pro_tag"] = len(ts) / total_days
        v["n_pro_markt"] = {s: sum(t.symbol == s for t in ts) for s in SYMBOLS}
        v["bootstrap_untergrenze_90"] = bootstrap_lower([t.net_r for t in ts])
        v["leave_one_year_out"] = leave_one_year_out(ts)
        res["configs"][c] = v
    if phase == "train":
        cand = [c for c in CONFIGS if res["configs"][c]["n"] >= 100 and res["configs"][c]["net_mean_r"] > 0.15
                and res["configs"][c]["bootstrap_untergrenze_90"] > 0]
        pv: dict[str, float] = {}
        if cand:
            ms = {s: Minutes(bars_roots[s], s, max(first - timedelta(days=70), date(2020, 1, 1) if s != "SOLUSDT" else date(2020, 8, 11)), last)
                  for s in SYMBOLS}
            fs = {s: Funding(funding_root, s, date(2020, 1, 1) if s != "SOLUSDT" else SOL_START, last) for s in SYMBOLS}
            for c in cand:
                r = random_p(ms, fs, trades[c], first)
                res["configs"][c]["zufallskontrolle"] = r
                pv[c] = r["p"]
        adj = holm_adjusted(pv, len(CONFIGS)) if pv else {}
        for c in CONFIGS:
            v = res["configs"][c]
            v["holm_adjustiert"] = adj.get(c)
            v["training_passed"] = c in adj and adj[c] <= 0.01 and v["leave_one_year_out"]["ok"]
    else:
        for c in CONFIGS:
            v = res["configs"][c]
            v["validation_passed"] = c in allowed and v["n"] >= 60 and v["net_mean_r"] > 0.15 and v["bootstrap_untergrenze_90"] > 0
    out.write_text(json.dumps(res, indent=1, default=str))
    out.with_suffix(".trades.json").write_text(json.dumps({c: [t.__dict__ for t in trades[c]] for c in CONFIGS}, default=str))
    print(json.dumps({c: {k: v[k] for k in ("n", "net_mean_r", "signale_pro_tag") if k in v} for c, v in res["configs"].items()}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("train", "valid"), required=True)
    ap.add_argument("--btc-root", required=True)
    ap.add_argument("--multi-root", required=True, help="dir with ETHUSDT/ and SOLUSDT/ bar roots and funding/")
    ap.add_argument("--train-result")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    roots = {"BTCUSDT": a.btc_root, "ETHUSDT": f"{a.multi_root}/ETHUSDT", "SOLUSDT": f"{a.multi_root}/SOLUSDT"}
    return run(a.phase, roots, f"{a.multi_root}/funding", Path(a.out), Path(a.train_result) if a.train_result else None)


if __name__ == "__main__":
    raise SystemExit(main())
