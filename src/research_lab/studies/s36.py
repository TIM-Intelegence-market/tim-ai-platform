"""S36 - QM, OB und SFP mit Orderflow-Konfluenz, HTF->Exec, BTC (Praeregistrierung Entwurf 0.1).

Phase ``count``: results-blind count of how many trades each of the 15 configurations (profile x pattern) would have
taken in Training (2020-2023) and Validation (2024). Only counts and the funnel are written, no R is printed or saved.
The detectors and the plan mechanics are the shadow's (``src/analysis/patterns.py``, ``pattern_shadow.advance``).
Rules: docs/research_lab/studien/S36_SFP_PRAEREGISTRIERUNG.md.
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
               blocks: Sequence[dict[str, Any]] | None = None, mode: str = "M", collect: list | None = None) -> dict[str, Any]:
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
    if collect is not None:
        collect.extend(p for p in plans.values() if p["status"] == "CLOSED")
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


# --- Auswertung (Phasen train / valid), Regeln 1.0 ----------------------------------------------------------------------

import random  # noqa: E402

from src.research_lab.studies.minute_sim import Funding  # noqa: E402

ENTRY_PCT = {"M": 0.0006 + 0.0003, "L": P.MAKER_PCT}  # taker + 0.03 % slippage / maker
EXIT_PCT = {"M": {"ZIEL": 0.0006 + 0.0003, "STOP": 0.0006 + 0.0005, "ZEIT": 0.0006 + 0.0003},
            "L": {"ZIEL": P.MAKER_PCT, "STOP": 0.0006 + 0.0005, "ZEIT": 0.0006 + 0.0003}}
MIN_N = {"train": 60, "valid": 30}
MIN_NET_R = 0.15
HOLM_P = 0.01
BOOT_SEED, CTRL_SEED, DRAWS, CTRL_DRAWS = 36, 36, 10_000, 1000


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def study_trade(plan: dict[str, Any], symbol: str, funding: Funding) -> dict[str, Any]:
    """One closed plan with the study's strict costs (S34/S35a rates) and the actual funding of its market, in R."""
    mode, direction = plan["mode"], 1 if plan["direction"] == P.LONG else -1
    cost_r = (ENTRY_PCT[mode] + EXIT_PCT[mode][plan["how"]]) * plan["entry"] / plan["risk"]
    entry_ms, exit_ms = _ms(plan["entry_time"]), _ms(plan["closed_at"])
    fund_r = funding.cost(direction, entry_ms, exit_ms) * plan["entry"] / plan["risk"]
    net = plan["gross_r"] - cost_r - fund_r
    return {"symbol": symbol, "profile": plan["profile"], "exec": plan["exec"], "mode": mode, "direction": direction, "entry_ms": entry_ms,
            "exit_ms": exit_ms, "how": plan["how"], "gross_r": plan["gross_r"], "cost_r": cost_r, "fund_r": fund_r, "net_r": net,
            "stop_frac": plan["risk"] / plan["entry"],
            "target_frac": abs(plan["target"] - plan["entry"]) / plan["entry"]}


def _week(ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isocalendar()
    return d[0], d[1]


def cluster_bootstrap_lower(trades: Sequence[dict[str, Any]], level: float = 0.90) -> float:
    """Lower bound of the one-sided interval of the mean net R, clusters = ISO weeks (Praeregistrierung: Block nach Woche)."""
    if not trades:
        return float("nan")
    clusters: dict[tuple[int, int], list[float]] = {}
    for t in trades:
        clusters.setdefault(_week(t["entry_ms"]), []).append(t["net_r"])
    groups = list(clusters.values())
    rng = random.Random(BOOT_SEED)
    k = len(groups)
    means = []
    for _ in range(DRAWS):
        total = n = 0
        for _i in range(k):
            g = groups[rng.randrange(k)]
            total += sum(g)
            n += len(g)
        means.append(total / n)
    means.sort()
    return means[int((1 - level) * DRAWS)]


def leave_one_year_out_ok(trades: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Pass when the mean net R stays > 0 after leaving out any single year (at least two years needed)."""
    years: dict[int, list[float]] = {}
    for t in trades:
        years.setdefault(datetime.fromtimestamp(t["entry_ms"] / 1000, tz=timezone.utc).year, []).append(t["net_r"])
    rows, ok = {}, len(years) > 1
    for y in years:
        rest = [x for yy, v in years.items() if yy != y for x in v]
        m = sum(rest) / len(rest) if rest else float("nan")
        rows[y] = {"n": len(years[y]), "leave_out_mean": m}
        ok = ok and m > 0
    return {"ok": ok, "years": rows}


def random_control(trades: Sequence[dict[str, Any]], series: dict[tuple[str, str], list[dict[str, Any]]], fundings: dict[str, Funding],
                   window: tuple[datetime, datetime]) -> dict[str, Any]:
    """Same trade count, direction, stop and target distance (fractions of the entry), entry at the close of a random exec candle of
    the same market and profile inside the period, same exits (stop first, 96 bars hold) and costs. p = share of draws with mean >= real."""
    rng = random.Random(CTRL_SEED)
    prepared: dict[tuple[str, str], tuple[list, list, list, list]] = {}
    for key, ex in series.items():
        idx = [i for i, c in enumerate(ex) if window[0] <= c["close_time"] < window[1] and i + 1 < len(ex)]
        prepared[key] = (idx, [c["close"] for c in ex], [c["high"] for c in ex], [c["low"] for c in ex])
    ends = {key: [int(c["close_time"].timestamp() * 1000) for c in ex] for key, ex in series.items()}
    real = sum(t["net_r"] for t in trades) / len(trades)
    means = []
    for _ in range(CTRL_DRAWS):
        total = 0.0
        for t in trades:
            key = (t["symbol"], t["profile"])
            idx, close, high, low = prepared[key]
            i = idx[rng.randrange(len(idx))]
            e, d = close[i], t["direction"]
            stop, target = e * (1 - d * t["stop_frac"]), e * (1 + d * t["target_frac"])
            how, x, j = "ZEIT", close[min(i + P.HOLD_BARS, len(close) - 1)], min(i + P.HOLD_BARS, len(close) - 1)
            for k in range(i + 1, min(i + P.HOLD_BARS, len(close) - 1) + 1):
                if (low[k] <= stop) if d > 0 else (high[k] >= stop):
                    how, x, j = "STOP", stop, k
                    break
                if (high[k] >= target) if d > 0 else (low[k] <= target):
                    how, x, j = "ZIEL", target, k
                    break
            risk = t["stop_frac"] * e
            gross = d * (x - e) / risk
            cost = (ENTRY_PCT[t["mode"]] + EXIT_PCT[t["mode"]][how]) * e / risk
            fund = fundings[t["symbol"]].cost(d, ends[key][i], ends[key][j]) * e / risk
            total += gross - cost - fund
        means.append(total / len(trades))
    means.sort()
    return {"real_mean_net_r": real, "random_mean": sum(means) / len(means), "random_p95": means[int(0.95 * CTRL_DRAWS)],
            "p": (1 + sum(1 for x in means if x >= real)) / (CTRL_DRAWS + 1), "draws": CTRL_DRAWS}


def holm_adjusted(p: dict[str, float], m: int) -> dict[str, float]:
    """Holm over m hypotheses; those not tested count as p = 1."""
    out, running = {}, 0.0
    for rank, (key, value) in enumerate(sorted(p.items(), key=lambda kv: kv[1])):
        running = max(running, min(1.0, (m - rank) * value))
        out[key] = running
    return out


def evaluate(phase: str, roots: dict[str, str], funding_root: str, out: Path, train_result: Path | None = None) -> int:
    first, last = TRAIN if phase == "train" else VALID
    allowed = list(CONFIG_IDS)
    if phase == "valid":
        tr = json.loads(Path(train_result).read_text())
        allowed = [c for c, v in tr["configs"].items() if v.get("training_passed")]
        if not allowed:
            print("Validierung gesperrt: keine Konfiguration hat das Training bestanden.")
            return 2
    trades: dict[str, list[dict[str, Any]]] = {c: [] for c in CONFIG_IDS}
    series: dict[tuple[str, str], list[dict[str, Any]]] = {}
    fundings: dict[str, Funding] = {}
    for sym in SYMBOLS:
        g0 = date(2020, 8, 11) if sym == "SOLUSDT" else date(2020, 1, 1)
        m = Minutes(roots[sym], sym, g0, VALID[1])
        fundings[sym] = Funding(funding_root, sym, SOL_START if sym == "SOLUSDT" else g0, VALID[1])
        candles = {tf: build_candles(m, tf) for tf in TF_MIN}
        a = max(first, SOL_START) if sym == "SOLUSDT" else first
        window = (datetime(a.year, a.month, a.day, tzinfo=timezone.utc), datetime(last.year, last.month, last.day, tzinfo=timezone.utc) + timedelta(days=1))
        for name, htf_tf, exec_tf in P.PROFILES:
            htf, ex = candles[htf_tf], candles[exec_tf]
            series[(sym, name)] = ex
            htf_ends = [c["close_time"] for c in htf]
            seconds = TF_MIN[htf_tf] * 60

            def atr_at(moment: datetime, htf=htf, htf_ends=htf_ends) -> float | None:
                i = bisect.bisect_right(htf_ends, moment) - 1
                return P.atr_at(htf, i) if i >= 0 else None

            setups = [{**x, "tf_seconds": seconds} for x in P.htf_setups(htf, htf_tf) if x["kind"] == "SFP"]
            exec_obs = P.order_blocks(ex, exec_tf)
            for mode in MODES:
                closed: list[dict[str, Any]] = []
                run_config(setups, ex, exec_tf, atr_at, window, exec_obs, mode, closed)
                trades[f"{POOLED}-{mode}"].extend(study_trade(p, sym, fundings[sym]) for p in closed)
    res: dict[str, Any] = {"studie": "S36", "version": "1.0", "phase": phase, "von": first.isoformat(), "bis": last.isoformat(), "configs": {}}
    window_all = (datetime(first.year, first.month, first.day, tzinfo=timezone.utc), datetime(last.year, last.month, last.day, tzinfo=timezone.utc) + timedelta(days=1))
    for c in CONFIG_IDS:
        ts = trades[c]
        v: dict[str, Any] = {"n": len(ts), "n_pro_markt": {s: sum(t["symbol"] == s for t in ts) for s in SYMBOLS}}
        if ts:
            v.update(net_mean_r=sum(t["net_r"] for t in ts) / len(ts), gross_mean_r=sum(t["gross_r"] for t in ts) / len(ts),
                     cost_mean_r=sum(t["cost_r"] for t in ts) / len(ts), funding_mean_r=sum(t["fund_r"] for t in ts) / len(ts),
                     stop_share=sum(t["how"] == "STOP" for t in ts) / len(ts), target_share=sum(t["how"] == "ZIEL" for t in ts) / len(ts),
                     bootstrap_untergrenze_90=cluster_bootstrap_lower(ts), leave_one_year_out=leave_one_year_out_ok(ts),
                     je_profil={p: {"n": sum(t["profile"] == p for t in ts), "net_mean_r": (sum(t["net_r"] for t in ts if t["profile"] == p) / max(1, sum(t["profile"] == p for t in ts)))}
                                for p, _h, _e in P.PROFILES})
        res["configs"][c] = v
    if phase == "train":
        pv: dict[str, float] = {}
        for c in CONFIG_IDS:
            v = res["configs"][c]
            if v["n"] >= MIN_N["train"] and v["net_mean_r"] > MIN_NET_R and v["bootstrap_untergrenze_90"] > 0:
                v["zufallskontrolle"] = random_control(trades[c], series, fundings, window_all)
                pv[c] = v["zufallskontrolle"]["p"]
        adj = holm_adjusted(pv, len(CONFIG_IDS)) if pv else {}
        for c in CONFIG_IDS:
            v = res["configs"][c]
            v["holm_adjustiert"] = adj.get(c)
            v["training_passed"] = bool(c in adj and adj[c] <= HOLM_P and v["leave_one_year_out"]["ok"])
    else:
        for c in CONFIG_IDS:
            v = res["configs"][c]
            v["validation_passed"] = bool(c in allowed and v["n"] >= MIN_N["valid"] and v.get("net_mean_r", -1) > MIN_NET_R
                                          and v.get("bootstrap_untergrenze_90", -1) > 0)
    out.write_text(json.dumps(res, indent=1, default=str))
    out.with_suffix(".trades.json").write_text(json.dumps(trades, default=str))
    for c, v in res["configs"].items():
        print(c, {k: v.get(k) for k in ("n", "net_mean_r", "gross_mean_r", "cost_mean_r", "funding_mean_r", "bootstrap_untergrenze_90", "holm_adjustiert",
                                         "training_passed", "validation_passed")})
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("count", "train", "valid"))
    ap.add_argument("--btc-root", required=True, help="S8 store root (bars/, bars_manifest.json) of BTCUSDT")
    ap.add_argument("--multi-root", required=True, help="dir with ETHUSDT/ and SOLUSDT/ bar roots, as for S35a")
    ap.add_argument("--out", required=True)
    ap.add_argument("--train-result")
    a = ap.parse_args(argv)
    roots = {"BTCUSDT": a.btc_root, "ETHUSDT": f"{a.multi_root}/ETHUSDT", "SOLUSDT": f"{a.multi_root}/SOLUSDT"}
    if a.phase != "count":
        return evaluate(a.phase, roots, f"{a.multi_root}/funding", Path(a.out), Path(a.train_result) if a.train_result else None)
    res = count(roots, Path(a.out))
    for key, v in res["je_profil_und_markt"].items():
        print(key, {k: (v[k]["setups"], v[k]["valid"], v[k]["plans"], v[k]["trades"]) for k in v})
    for cid in CONFIG_IDS:
        print(cid, "Training:", res["configs"][cid]["training"], "Validierung:", res["configs"][cid]["validierung"])
    print("nicht testbar (Training n<60):", res["nicht_testbar_training_n_unter_60"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
