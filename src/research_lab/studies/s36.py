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
CONFIGS = [f"{name}-{kind}" for name, _h, _e in P.PROFILES for kind in ("QM", "OB", "SFP")]  # 15
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
               blocks: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
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


def count(bars_root: str, out: Path) -> dict[str, Any]:
    m = Minutes(bars_root, "BTCUSDT", date(2020, 1, 1), VALID[1])
    candles = {tf: build_candles(m, tf) for tf in TF_MIN}
    res: dict[str, Any] = {"studie": "S36", "phase": "count", "ergebnisblind": True, "configs": {}}
    for name, htf_tf, exec_tf in P.PROFILES:
        htf, ex = candles[htf_tf], candles[exec_tf]
        htf_ends = [c["close_time"] for c in htf]
        seconds = TF_MIN[htf_tf] * 60

        def atr_at(moment: datetime, htf=htf, htf_ends=htf_ends) -> float | None:
            i = bisect.bisect_right(htf_ends, moment) - 1
            return P.atr_at(htf, i) if i >= 0 else None

        setups = [{**s, "tf_seconds": seconds} for s in P.htf_setups(htf, htf_tf)]
        exec_obs = P.order_blocks(ex, exec_tf)  # once per profile, not per setup
        for kind in ("QM", "OB", "SFP"):
            mine = [s for s in setups if s["kind"] == kind]
            res["configs"][f"{name}-{kind}"] = {
                abschnitt: run_config(mine, ex, exec_tf, atr_at, (datetime(a.year, a.month, a.day, tzinfo=timezone.utc),
                                                                  datetime(b.year, b.month, b.day, tzinfo=timezone.utc) + timedelta(days=1)), exec_obs)
                for abschnitt, (a, b) in (("training", TRAIN), ("validierung", VALID))}
    res["nicht_testbar_training_n_unter_60"] = [c for c, v in res["configs"].items() if v["training"]["trades"] < 60]
    out.write_text(json.dumps(res, indent=1, default=str))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("count",))
    ap.add_argument("--btc-root", required=True, help="S8 store root (bars/, bars_manifest.json)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = count(a.btc_root, Path(a.out))
    for c, v in res["configs"].items():
        print(c, {k: (v[k]["setups"], v[k]["valid"], v[k]["plans"], v[k]["trades"]) for k in v})
    print("nicht testbar (Training n<60):", res["nicht_testbar_training_n_unter_60"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
