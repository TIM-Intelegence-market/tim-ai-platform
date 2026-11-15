"""S36 - QM, OB und SFP mit Orderflow-Konfluenz, HTF->Exec, BTC (Praeregistrierung Entwurf 0.1).

Phase ``count``: results-blind count of how many trades each of the 15 configurations (profile x pattern) would have
taken in Training (2020-2023) and Validation (2024). Only counts and the funnel are written, no R is printed or saved.
The detectors and the plan mechanics are the shadow's (``src/analysis/patterns.py``, ``pattern_shadow.advance``).
Rules: docs/research_lab/studien/S36_MUSTER_QM_OB_SFP_PRAEREGISTRIERUNG_ENTWURF.md.
"""
from __future__ import annotations

import argparse
import bisect
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from src.analysis import patterns as P
from src.dashboard import pattern_shadow as S
from src.research_lab.studies.minute_sim import MINUTE_MS, Minutes

TRAIN = (date(2020, 1, 1), date(2023, 12, 31))
VALID = (date(2024, 1, 1), date(2024, 12, 31))
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
WEEK_OFFSET_MIN = 4 * 1440  # the epoch is a Thursday, the first Monday is 4 days later
CONFIGS = ["SFP-alle-M", "SFP-alle-L"]  # Entwurf 0.3: pooled SFP in two entry variants (0.1 had 15 configurations, all below n=60)
SLICE_LEAD = 30  # exec candles before the arm time, for ATR(14) and the 20-bar RVOL


def build_candles(m: Minutes, tf: str) -> list[dict[str, Any]]:
    """Complete candles of ``tf`` from the minute grid, with volume (base) and the aggressive delta share of the candle."""
    width = TF_MIN[tf]
    shift = -WEEK_OFFSET_MIN if tf == "1w" else 0
    out: list[dict[str, Any]] = []
    first_min = m.t0 // 60000
    n_min = m.n
    k0 = (first_min + shift) // width
    k1 = (first_min + shift + n_min) // width
    for k in range(k0, k1 + 1):
        start_min = k * width - shift
        i0 = start_min - first_min
        i1 = i0 + width
        if i0 < 0 or i1 > n_min or not any(m.valid[i0:i1]):
            continue
        buy, sell = sum(m.buy_q[i0:i1]), sum(m.sell_q[i0:i1])
        start = datetime.fromtimestamp(start_min * 60, tz=timezone.utc)
        out.append({"open_time": start, "close_time": start + timedelta(minutes=width), "open": m.open[i0], "high": max(m.high[i0:i1]),
                    "low": min(m.low[i0:i1]), "close": m.close[i1 - 1], "volume": sum(m.base[i0:i1]),
                    "delta_share": (buy - sell) / (buy + sell) if buy + sell > 0 else None, "closed": True})
    return out


def run_config(setups: Sequence[dict[str, Any]], ex: list[dict[str, Any]], exec_tf: str, htf_atr_at: Any, window: tuple[datetime, datetime],
               blocks: Sequence[dict[str, Any]] | None = None, mode: str = "M") -> dict[str, Any]:
    """One configuration over one period: plans armed at their exec-OB close, advanced through the shadow's own rules."""
    ends = [c["close_time"] for c in ex]
    blocks = P.order_blocks(ex, exec_tf) if blocks is None else blocks
    plans: dict[str, dict[str, Any]] = {}
    funnel = {"setups": 0, "valid": 0, "plans": 0}
    for setup in setups:
        if not (window[0] <= setup["created"] <= window[1]):
            continue
        funnel["setups"] += 1
        if not setup["valid"]:
            continue
        funnel["valid"] += 1
        atr = htf_atr_at(setup["created"])
        if not atr:
            continue
        life_end = setup["created"] + timedelta(seconds=P.HTF_MAX_AGE * setup["tf_seconds"])
        for block in P.exec_blocks(setup, ex, exec_tf, atr, blocks):
            if block["created"] > life_end or block["created"] > window[1]:
                continue
            plan = S._plan_from(setup, {**block, "id": block["created"].isoformat()}, "study", exec_tf, block["created"])
            plan["mode"] = mode
            plan["setup_extra"] = {"sweep_rvol": setup.get("sweep_rvol"), "sweep_delta": setup.get("sweep_delta")}
            plans.setdefault(plan["id"], plan)
            funnel["plans"] += 1
    for plan in sorted(plans.values(), key=lambda p: p["armed_at"]):
        a = bisect.bisect_right(ends, datetime.fromisoformat(plan["armed_at"]))
        stop = min(len(ex), a + P.WAIT_BARS + P.HOLD_BARS + 4)
        S.advance(plan, ex[max(0, a - SLICE_LEAD):stop], plans, None)
    entered = [p for p in plans.values() if p["status"] in ("OPEN", "CLOSED")]
    skipped: dict[str, int] = {}
    for p in plans.values():
        if p["status"] == "SKIPPED":
            skipped[p["reason"]] = skipped.get(p["reason"], 0) + 1
    return {**funnel, "trades": len(entered), "skipped": skipped, "unresolved": sum(p["status"] in ("ARMED", "OPEN") for p in plans.values())}


SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SOL_START = date(2020, 9, 1)  # perpetual funding exists from Sep 2020, as in S35a
MODES = ("M", "L")  # M: market at the retest close (taker), L: limit at the zone edge (maker)
POOLED = "SFP-alle"
CONFIG_IDS = [f"{POOLED}-{m}" for m in MODES]


def count(roots: dict[str, str], out: Path) -> dict[str, Any]:
    """Entwurf 0.3: only SFP, the five profiles pooled, BTC/ETH/SOL, entry variants M and L. Per-profile and per-market counts are descriptive only."""
    res: dict[str, Any] = {"studie": "S36", "phase": "count", "version": "0.3", "ergebnisblind": True, "pooled": POOLED,
                           "je_profil_und_markt": {}, "configs": {c: {"training": {"trades": 0}, "validierung": {"trades": 0}} for c in CONFIG_IDS}}
    skipped_total: dict[str, dict[str, dict[str, int]]] = {c: {"training": {}, "validierung": {}} for c in CONFIG_IDS}
    for sym in SYMBOLS:
        first = date(2020, 8, 11) if sym == "SOLUSDT" else date(2020, 1, 1)
        m = Minutes(roots[sym], sym, first, VALID[1])
        candles = {tf: build_candles(m, tf) for tf in TF_MIN}
        for name, htf_tf, exec_tf in P.PROFILES:
            htf, ex = candles[htf_tf], candles[exec_tf]
            htf_ends = [c["close_time"] for c in htf]
            seconds = TF_MIN[htf_tf] * 60

            def atr_at(moment: datetime, htf=htf, htf_ends=htf_ends) -> float | None:
                i = bisect.bisect_right(htf_ends, moment) - 1
                return P.atr_at(htf, i) if i >= 0 else None

            setups = [{**x, "tf_seconds": seconds} for x in P.htf_setups(htf, htf_tf) if x["kind"] == "SFP"]
            exec_obs = P.order_blocks(ex, exec_tf)
            for abschnitt, (a, b) in (("training", TRAIN), ("validierung", VALID)):
                a = max(a, SOL_START) if sym == "SOLUSDT" else a
                window = (datetime(a.year, a.month, a.day, tzinfo=timezone.utc), datetime(b.year, b.month, b.day, tzinfo=timezone.utc) + timedelta(days=1))
                for mode in MODES:
                    r = run_config(setups, ex, exec_tf, atr_at, window, exec_obs, mode)
                    cid = f"{POOLED}-{mode}"
                    res["je_profil_und_markt"].setdefault(f"{name}-{sym}-{mode}", {})[abschnitt] = r
                    res["configs"][cid][abschnitt]["trades"] += r["trades"]
                    for reason, n in r["skipped"].items():
                        skipped_total[cid][abschnitt][reason] = skipped_total[cid][abschnitt].get(reason, 0) + n
    for cid in CONFIG_IDS:
        for abschnitt in ("training", "validierung"):
            res["configs"][cid][abschnitt]["skipped"] = skipped_total[cid][abschnitt]
    res["nicht_testbar_training_n_unter_60"] = [c for c in CONFIG_IDS if res["configs"][c]["training"]["trades"] < 60]
    out.write_text(json.dumps(res, indent=1, default=str))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("count",))
    ap.add_argument("--btc-root", required=True, help="S8 store root (bars/, bars_manifest.json) of BTCUSDT")
    ap.add_argument("--multi-root", required=True, help="dir with ETHUSDT/ and SOLUSDT/ bar roots, as for S35a")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    roots = {"BTCUSDT": a.btc_root, "ETHUSDT": f"{a.multi_root}/ETHUSDT", "SOLUSDT": f"{a.multi_root}/SOLUSDT"}
    res = count(roots, Path(a.out))
    for key, v in res["je_profil_und_markt"].items():
        print(key, {k: (v[k]["setups"], v[k]["valid"], v[k]["plans"], v[k]["trades"]) for k in v})
    for cid in CONFIG_IDS:
        print(cid, "Training:", res["configs"][cid]["training"], "Validierung:", res["configs"][cid]["validierung"])
    print("nicht testbar (Training n<60):", res["nicht_testbar_training_n_unter_60"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
