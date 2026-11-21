"""S34 - LVN am Wochen-VAH/VAL plus >= 2 Sigma vom Tages-VWAP, Rueckkehr zum VWAP (Praeregistrierung 1.0).

Rules are frozen in docs/research_lab/studien/S34_LVN_VWAP_FADE_PRAEREGISTRIERUNG.md; this file only implements them.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median

from src.research_lab.orderflow_ml.profile import value_area
from src.research_lab.studies.minute_sim import (DAY_MS, MINUTE_MS, Funding, Minutes, Trade, bootstrap_lower, days, leave_one_year_out,
                                                 mean, ms_of, random_control, simulate, summary)

GRID = 0.001            # log price grid of the weekly profile (about the 0.1 % bins of S8)
SIGMA_MIN = 2.0
LVN_SHARE = 0.5
LVN_NEIGHBOURS = 5      # bins on each side
LVN_MAX_DIST = 0.0015   # LVN to VAH/VAL
STOP_PAD = 0.001
TIME_STOP_MIN = 240
CANDLE = 5
MIN_DAY_MIN = 60        # VWAP sigma needs an hour of the UTC day
MIN_WEEK_MIN = 1440     # weekly profile needs at least a day (not Monday morning)
TRAIN = (date(2020, 1, 1), date(2023, 12, 31))
VALID = (date(2024, 1, 1), date(2024, 12, 31))


def gidx(price: float) -> int:
    return math.floor(math.log(price) / GRID)


def lvn_near(hist: dict[int, int], price: float, side: int) -> bool:
    """Is the bin of price an LVN (volume < 50 % of the median of the 10 neighbour bins, all inside the profile range) with
    its centre within 0.15 % of the weekly VAH (side +1, short) or VAL (side -1, long)?"""
    va = value_area(hist)
    if va is None:
        return False
    _poc, val, vah = va
    k = gidx(price)
    lo, hi = min(hist), max(hist)
    if k - LVN_NEIGHBOURS < lo or k + LVN_NEIGHBOURS > hi:
        return False
    nb = [hist.get(k + d, 0) for d in range(-LVN_NEIGHBOURS, LVN_NEIGHBOURS + 1) if d]
    if not hist.get(k, 0) < LVN_SHARE * median(nb):
        return False
    edge = vah if side > 0 else val
    centre = math.exp((k + 0.5) * GRID)
    ref = math.exp((edge + 0.5) * GRID)
    return abs(centre - ref) / ref <= LVN_MAX_DIST


def signals(m: Minutes, first: date, last: date) -> tuple[list[dict], dict]:
    """All signals (1 per UTC day and direction) in [first, last] plus the funnel counts. No Zukunft: weekly profile, VWAP and sigma use
    minutes up to the signal candle close."""
    funnel = {"candles": 0, "dev_2sigma": 0, "lvn_vah": 0, "signals": 0}
    out: list[dict] = []
    week_hist: dict[int, int] = {}
    week_minutes = 0
    # warm start: the week containing first begins on Monday; the profile is rebuilt from that Monday
    d0 = first
    while d0.weekday() != 0:
        d0 = d0.fromordinal(d0.toordinal() - 1)
    d0 = max(d0, m.first)
    for d in days(d0, last):
        if d.weekday() == 0:
            week_hist, week_minutes = {}, 0
        prof = m.day_profile(d)
        by_min: dict[int, list] = {}
        for minute, price, vol in prof:
            by_min.setdefault(minute, []).append((price, vol))
        base_i = (d - m.first).days * 1440
        sv = sp = spp = 0.0
        p_ref = m.close[base_i]
        done = {1: False, -1: False}
        for c in range(1440 // CANDLE):
            for mi in range(c * CANDLE, c * CANDLE + CANDLE):
                for price, vol in by_min.get(mi, ()):
                    k = gidx(price)
                    week_hist[k] = week_hist.get(k, 0) + int(round(vol * 1e4))
                week_minutes += 1
                i = base_i + mi
                v = m.base[i]
                if v > 0:
                    pm = (m.buy_q[i] + m.sell_q[i]) / v - p_ref
                    sv += v
                    sp += v * pm
                    spp += v * pm * pm
            if d < first:
                continue
            minutes_in_day = (c + 1) * CANDLE
            if minutes_in_day < MIN_DAY_MIN or week_minutes < MIN_WEEK_MIN or sv <= 0:
                continue
            funnel["candles"] += 1
            vwap = p_ref + sp / sv
            var = spp / sv - (sp / sv) ** 2
            if var <= 0:
                continue
            sigma = math.sqrt(var)
            i_last = base_i + c * CANDLE + CANDLE - 1
            close = m.close[i_last]
            dev = (close - vwap) / sigma
            side = 1 if dev >= SIGMA_MIN else -1 if dev <= -SIGMA_MIN else 0
            if not side:
                continue
            funnel["dev_2sigma"] += 1
            if done[side]:
                continue
            if not lvn_near(week_hist, close, side):
                continue
            funnel["lvn_vah"] += 1
            i_next = i_last + 1
            if i_next >= m.n:
                continue
            hi = max(m.high[base_i + c * CANDLE: i_next])
            lo = min(m.low[base_i + c * CANDLE: i_next])
            stop = hi * (1 + STOP_PAD) if side > 0 else lo * (1 - STOP_PAD)
            out.append({"side": side, "i_entry": i_next, "stop": stop, "target": vwap, "signal_ms": m.t0 + (i_last + 1) * MINUTE_MS})
            done[side] = True
            funnel["signals"] += 1
    return out, funnel


def run(root: str, funding_root: str, first: date, last: date, symbol: str = "BTCUSDT") -> dict:
    # the minute grid starts on the Monday of the first week so that the weekly profile has no look-ahead and no cold start
    g0 = first
    while g0.weekday() != 0:
        g0 = g0.fromordinal(g0.toordinal() - 1)
    g0 = max(g0, date(2020, 1, 1))
    m = Minutes(root, symbol, g0, last)
    funding = Funding(funding_root, symbol, first, date(last.year, last.month, last.day))
    sigs, funnel = signals(m, first, last)
    trades: list[Trade] = []
    skipped = 0
    for s in sigs:
        t = simulate(m, funding, symbol, -s["side"], s["i_entry"], s["stop"], s["target"], TIME_STOP_MIN, s["signal_ms"], "S34")
        if t is None:
            skipped += 1
        else:
            trades.append(t)
    eligible = [i for i in range((first - g0).days * 1440, m.n - TIME_STOP_MIN) if (i % 1440) % CANDLE == 0]
    res = {
        "studie": "S34", "von": first.isoformat(), "bis": last.isoformat(), "symbol": symbol,
        "funnel": funnel, "ohne_trade_wegen_einstieg_ueber_stop_oder_ziel": skipped, "trades": summary(trades),
        "bootstrap_untergrenze_90": bootstrap_lower([t.net_r for t in trades]),
        "leave_one_year_out": leave_one_year_out(trades),
    }
    if len(trades) >= 10:
        res["zufallskontrolle"] = random_control(m, funding, symbol, trades, eligible, TIME_STOP_MIN)
    return res | {"_trades": [t.__dict__ for t in trades]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("train", "valid"), required=True)
    ap.add_argument("--bars-root", required=True)
    ap.add_argument("--funding-root", required=True)
    ap.add_argument("--train-result", help="required for --phase valid: the training result json (gate n>=60 and net > +0.15 R)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    first, last = TRAIN if a.phase == "train" else VALID
    if a.phase == "valid":
        tr = json.loads(Path(a.train_result).read_text())
        if not (tr["trades"]["n"] >= 60 and tr["trades"]["net_mean_r"] > 0.15):
            print("Validierung gesperrt: Training erfuellt n>=60 und netto > +0,15 R nicht.", file=sys.stderr)
            return 2
    res = run(a.bars_root, a.funding_root, first, last)
    Path(a.out).write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "_trades"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
