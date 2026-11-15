"""S36 - Fade-Checkliste (Flowread), Teil a ohne Gamma, BTC/ETH/SOL (Praeregistrierung 1.0).

Rules frozen in docs/research_lab/studien/S36_FADE_CHECKLISTE_PRAEREGISTRIERUNG.md. Gamma/DEX is not part of this study.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import median

from src.research_lab.studies.minute_sim import (MINUTE_MS, Funding, Minutes, Trade, bootstrap_lower, days, leave_one_year_out, mean,
                                                 simulate, summary)
from src.research_lab.studies.s35a import (SOL_START, SYMBOLS, TOL, TRAIN, VALID, holm_adjusted, profile_levels)

SIGMA = 2.0
MIN_DAY_MIN = 60
LOOKBACK = 20            # candles for the median volume / range
VOL_MULT = 1.5
RANGE_MULT = 0.8
DELTA_MIN = 0.10
STOP_PAD = 0.001
MIN_RISK = 0.005
TIME_STOP_MIN = 240
TFS = (5, 15)
CONFIGS = [f"F-{t}m-{v}" for t in TFS for v in ("vaOn", "vaOff")]   # 4
SEED = 36


def find_signals(m: Minutes, first: date, last: date, tf: int) -> dict[str, list[dict]]:
    """Signals per variant (vaOn / vaOff). One signal per UTC day and direction. Candle k = absorption, k+1 = confirmation,
    entry at the open of k+2."""
    out: dict[str, list[dict]] = {"vaOn": [], "vaOff": []}
    for d in days(first, last):
        base = (d - m.first).days * 1440
        if base < 1440 or base + 1440 > m.n:
            continue
        lv = profile_levels(m, d)                 # [POC, VAH, VAL]
        if len(lv) < 3:
            continue
        vah, val = lv[1], lv[2]
        open_inside = val <= m.open[base] <= vah   # check 3: open at 00:00 UTC inside the previous day's value area
        sv = sp = spp = 0.0
        p_ref = m.close[base]
        seen: set[tuple[str, int]] = set()
        recs: list[dict] = []
        n_c = 1440 // tf
        for c in range(n_c):
            a, b = base + c * tf, base + c * tf + tf
            vw_pre = sd = None
            if c * tf >= MIN_DAY_MIN and sv > 0:
                vw_pre = p_ref + sp / sv
                var = spp / sv - (sp / sv) ** 2
                sd = math.sqrt(var) if var > 0 else None
            op, hi, lo, close = m.open[a], max(m.high[a:b]), min(m.low[a:b]), m.close[b - 1]
            bq, sq = sum(m.buy_q[a:b]), sum(m.sell_q[a:b])
            vol = bq + sq
            delta = (bq - sq) / vol if vol > 0 else 0.0
            for i in range(a, b):
                v = m.base[i]
                if v > 0:
                    pm = (m.buy_q[i] + m.sell_q[i]) / v - p_ref
                    sv += v
                    sp += v * pm
                    spp += v * pm * pm
            vw_end = p_ref + sp / sv if sv > 0 else None
            rec = {"open": op, "hi": hi, "lo": lo, "close": close, "vol": vol, "delta": delta, "rng": hi - lo,
                   "vw": vw_pre, "sd": sd, "vw_end": vw_end, "a": a, "b": b}
            # candle c confirms candle c-1 (k)
            if recs and c * tf >= MIN_DAY_MIN + tf and b < m.n:
                k = recs[-1]
                hist = recs[-LOOKBACK - 1:-1]
                if len(hist) >= LOOKBACK and k["vw"] is not None and k["sd"] and vw_end:
                    mv, mr = median(h["vol"] for h in hist), median(h["rng"] for h in hist)
                    absorbed = k["vol"] >= VOL_MULT * mv and k["rng"] <= RANGE_MULT * mr
                    for direction in (1, -1):
                        if (b < m.n and absorbed and
                                ((direction > 0 and k["close"] <= k["vw"] - SIGMA * k["sd"] and k["lo"] <= val * (1 + TOL) and k["hi"] >= val * (1 - TOL)
                                  and k["delta"] < 0 and close >= op and delta >= DELTA_MIN)
                                 or (direction < 0 and k["close"] >= k["vw"] + SIGMA * k["sd"] and k["hi"] >= vah * (1 - TOL) and k["lo"] <= vah * (1 + TOL)
                                     and k["delta"] > 0 and close <= op and delta <= -DELTA_MIN))):
                            raw = k["lo"] * (1 - STOP_PAD) if direction > 0 else k["hi"] * (1 + STOP_PAD)
                            for var_name in ("vaOff", "vaOn"):
                                if var_name == "vaOn" and not open_inside:
                                    continue
                                key = (var_name, direction)
                                if key in seen:
                                    continue
                                seen.add(key)
                                out[var_name].append({"direction": direction, "i_entry": b, "raw_stop": raw, "target": vw_end,
                                                      "signal_ms": m.t0 + b * MINUTE_MS})
            recs.append(rec)
    return out


def to_trade(m: Minutes, funding: Funding, sym: str, s: dict, tag: str) -> Trade | None:
    e, dr = m.open[s["i_entry"]], s["direction"]
    risk = max(abs(e - s["raw_stop"]) / e, MIN_RISK)
    stop = e * (1 - dr * risk)
    return simulate(m, funding, sym, dr, s["i_entry"], stop, s["target"], TIME_STOP_MIN, s["signal_ms"], tag)


def collect(bars_roots: dict[str, str], funding_root: str, first: date, last: date) -> tuple[dict[str, list[Trade]], dict[str, int]]:
    trades: dict[str, list[Trade]] = {c: [] for c in CONFIGS}
    skipped = {c: 0 for c in CONFIGS}      # entry already beyond stop/target
    for sym in SYMBOLS:
        f0 = max(first, SOL_START) if sym == "SOLUSDT" else first
        g0 = max(f0 - timedelta(days=70), date(2020, 1, 1) if sym != "SOLUSDT" else date(2020, 8, 11))
        m = Minutes(bars_roots[sym], sym, g0, last)
        fund = Funding(funding_root, sym, g0 if sym != "SOLUSDT" else SOL_START, last)
        for tf in TFS:
            for var_name, sigs in find_signals(m, f0, last, tf).items():
                cid = f"F-{tf}m-{var_name}"
                for s in sigs:
                    t = to_trade(m, fund, sym, s, cid)
                    if t is None:
                        skipped[cid] += 1
                    else:
                        trades[cid].append(t)
    return trades, skipped


def random_p(ms: dict[str, Minutes], fundings: dict[str, Funding], trades: list[Trade], first: date, draws: int = 1000, seed: int = SEED) -> dict:
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
    trades, skipped = collect(bars_roots, funding_root, first, last)
    res: dict = {"studie": "S36", "phase": phase, "von": first.isoformat(), "bis": last.isoformat(), "configs": {}}
    total_days = (last - first).days + 1
    for c in CONFIGS:
        ts = trades[c]
        v = summary(ts)
        v["signale_pro_tag"] = len(ts) / total_days
        v["entfallen_einstieg_jenseits"] = skipped[c]
        v["n_pro_markt"] = {s: sum(t.symbol == s for t in ts) for s in SYMBOLS}
        v["bootstrap_untergrenze_90"] = bootstrap_lower([t.net_r for t in ts], seed=SEED)
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
        for tf in TFS:   # Ausweis, keine Bestehensbedingung
            on, off = res["configs"][f"F-{tf}m-vaOn"], res["configs"][f"F-{tf}m-vaOff"]
            on["schlaegt_vaOff"] = on["n"] > 0 and (off["n"] == 0 or on["net_mean_r"] > off["net_mean_r"])
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
