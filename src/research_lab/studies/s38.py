"""S38 - Enger Vortag, danach Ausbruch, BTC/ETH/SOL (Praeregistrierung 1.0).

Rules frozen in docs/research_lab/studien/S38_TIGHT_DAY_AUSBRUCH_PRAEREGISTRIERUNG.md.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from src.research_lab.studies.minute_sim import (MINUTE_MS, Funding, Minutes, Trade, bootstrap_lower, days, leave_one_year_out, mean,
                                                 simulate, summary)
from src.research_lab.studies.s35a import SOL_START, SYMBOLS, TRAIN, VALID, holm_adjusted

BREAK = 0.0005
STOP_PAD = 0.0005
MIN_RISK = 0.005
TARGET_R = 2.0
HOLD_MIN = 1440
LOOKBACK = 20
THRESHOLDS = {"T-045": 0.45, "T-060": 0.60, "T-075": 0.75}
CONFIGS = list(THRESHOLDS)          # Holm over 3
REF = "T-alle"                      # reference: no tight-day filter, not part of Holm
ALL = CONFIGS + [REF]
SEED = 38


def day_range(m: Minutes, d: date):
    """(high, low, open) of UTC day d, None when fewer than 90 % of its minutes traded or d is outside the grid."""
    a = (d - m.first).days * 1440
    if a < 0 or a + 1440 > m.n or sum(m.valid[a:a + 1440]) < 0.9 * 1440:
        return None
    return max(m.high[a:a + 1440]), min(m.low[a:a + 1440]), m.open[a]


def rel_range(m: Minutes, d: date):
    r = day_range(m, d)
    return None if r is None or r[2] <= 0 else (r[0] - r[1]) / r[2]


def breakout_signal(m: Minutes, d: date):
    """First breakout of the previous day's high/low during UTC day d.
    Returns {direction, i_entry, entry, raw_stop} or None; "both" when both sides break in the same minute."""
    prev = day_range(m, d - timedelta(days=1))
    if prev is None:
        return None
    hi, lo, _ = prev
    up, dn = hi * (1 + BREAK), lo * (1 - BREAK)
    a = (d - m.first).days * 1440
    if a < 0 or a + 1440 > m.n:
        return None
    for i in range(a, a + 1440):
        u, w = m.high[i] >= up, m.low[i] <= dn
        if u and w:
            return "both"
        if u:
            return {"direction": 1, "i_entry": i, "entry": up, "raw_stop": lo * (1 - STOP_PAD)}
        if w:
            return {"direction": -1, "i_entry": i, "entry": dn, "raw_stop": hi * (1 + STOP_PAD)}
    return None


def tight_days(m: Minutes, first: date, last: date) -> dict[date, float]:
    """Day d -> ratio of its relative range to the mean relative range of the LOOKBACK days before it (only complete days)."""
    out: dict[date, float] = {}
    for d in days(first - timedelta(days=1), last - timedelta(days=1)):
        r = rel_range(m, d)
        hist = [rel_range(m, d - timedelta(days=k)) for k in range(1, LOOKBACK + 1)]
        hist = [h for h in hist if h is not None]
        if r is None or len(hist) < LOOKBACK * 0.9:
            continue
        mu = sum(hist) / len(hist)
        if mu > 0:
            out[d + timedelta(days=1)] = r / mu      # keyed by the trading day d+1
    return out


def to_trade(m: Minutes, funding: Funding, sym: str, s: dict, tag: str) -> Trade | None:
    e, dr = s["entry"], s["direction"]
    risk = max(abs(e - s["raw_stop"]) / e, MIN_RISK)
    stop = e * (1 - dr * risk)
    return simulate(m, funding, sym, dr, s["i_entry"], stop, e * (1 + dr * TARGET_R * risk), HOLD_MIN,
                    m.t0 + s["i_entry"] * MINUTE_MS, tag, entry_override=e)


def collect(bars_roots: dict[str, str], funding_root: str, first: date, last: date):
    trades: dict[str, list[Trade]] = {c: [] for c in ALL}
    skipped = {c: {"beide_seiten": 0, "einstieg_jenseits": 0} for c in ALL}
    expansion: dict[str, list[float]] = {"eng": [], "alle": []}
    for sym in SYMBOLS:
        f0 = max(first, SOL_START) if sym == "SOLUSDT" else first
        g0 = max(f0 - timedelta(days=LOOKBACK + 5), date(2020, 1, 1) if sym != "SOLUSDT" else date(2020, 8, 11))
        m = Minutes(bars_roots[sym], sym, g0, last)
        fund = Funding(funding_root, sym, g0 if sym != "SOLUSDT" else SOL_START, last)
        ratio = tight_days(m, f0, last)
        for d in days(f0, last):
            sig = breakout_signal(m, d)
            rd, rp = rel_range(m, d), rel_range(m, d - timedelta(days=1))
            if rd is not None and rp:
                expansion["alle"].append(rd / rp)
                if d in ratio and ratio[d] <= THRESHOLDS["T-075"]:
                    expansion["eng"].append(rd / rp)
            if sig is None:
                continue
            for c in ALL:
                if c != REF and not (d in ratio and ratio[d] <= THRESHOLDS[c]):
                    continue
                if sig == "both":
                    skipped[c]["beide_seiten"] += 1
                    continue
                t = to_trade(m, fund, sym, sig, c)
                if t is None:
                    skipped[c]["einstieg_jenseits"] += 1
                else:
                    trades[c].append(t)
    return trades, skipped, expansion


def random_p(ms: dict[str, Minutes], fundings: dict[str, Funding], trades: list[Trade], first: date, draws: int = 1000, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    el = {s: [i for i in range(max(0, (first - ms[s].first).days * 1440), ms[s].n - HOLD_MIN) if i % 5 == 0] for s in ms}
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
                             e * (1 + t.direction * t.target_frac), HOLD_MIN, m.t0 + i * MINUTE_MS)
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
    trades, skipped, expansion = collect(bars_roots, funding_root, first, last)
    res: dict = {"studie": "S38", "phase": phase, "von": first.isoformat(), "bis": last.isoformat(), "configs": {},
                 "ausdehnung_mittel": {k: mean(v) for k, v in expansion.items()},
                 "ausdehnung_n": {k: len(v) for k, v in expansion.items()}}
    for c in ALL:
        ts = trades[c]
        v = summary(ts)
        v["entfallen"] = skipped[c]
        v["n_pro_markt"] = {s: sum(t.symbol == s for t in ts) for s in SYMBOLS}
        v["bootstrap_untergrenze_90"] = bootstrap_lower([t.net_r for t in ts], seed=SEED)
        v["leave_one_year_out"] = leave_one_year_out(ts)
        res["configs"][c] = v
    if phase == "train":
        cand = [c for c in CONFIGS if res["configs"][c]["n"] >= 100 and res["configs"][c]["net_mean_r"] > 0.15
                and res["configs"][c]["bootstrap_untergrenze_90"] > 0]
        pv: dict[str, float] = {}
        if cand:
            ms = {s: Minutes(bars_roots[s], s, max(first - timedelta(days=LOOKBACK + 5), date(2020, 1, 1) if s != "SOLUSDT" else date(2020, 8, 11)), last)
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
    out.with_suffix(".trades.json").write_text(json.dumps({c: [t.__dict__ for t in trades[c]] for c in ALL}, default=str))
    print(json.dumps({c: {k: v[k] for k in ("n", "net_mean_r") if k in v} for c, v in res["configs"].items()}, indent=1))
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
