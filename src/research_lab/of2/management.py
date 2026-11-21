"""Trade management variants for OF2 trades (Fabervaale video 16.11.2026, plan package P5).

The video (W10/W11): take the trade off at the next balance, or trail it; when the move runs and the next balance is
far away, lock the floating profit at the last invalidation and risk a third of it in a second position.

This replays *finished* OF2 trades (same fill, entry, stop, target) minute by minute with other exits; signals and
fills stay exactly as the engine made them, so the variants differ only in management (paired comparison).

- ``FEST``: the engine's own exit (stop, target, time stop, max hold), recomputed; checks the replay.
- ``TEIL``: half off at +1 R, stop of the rest to break-even, rest to target or stop.
- ``NACHZIEHEN``: no target; from +1 R on the stop trails ``trail_r`` R behind the best price.
- ``AUFBAU``: like ``NACHZIEHEN``; at +``add_at_r`` R the first stop moves to +``lock_r`` R and a second position
  opens at that minute's close with risk = ``add_share`` x the floating profit (in R of the first trade), its stop
  at the first position's locked stop; both then trail together.

Every variant keeps the engine's time stop (8 bars without 0,5 R) and the hard holding limit. Within a minute the
stop is checked before anything favourable (conservative, as the tracker). Costs per leg with the tracker's cost
model (fee both sides, slippage, stop slippage). Results in R of the first position's risk.

    python -m src.research_lab.of2.management --bars <orderflow_ml root> --trades run.json --out DIR

reads the trades of an ``of2 run`` result (training or validation, as that run) and the minute bars after each fill.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.research_lab.of2.config import DEFAULT_CONFIG, MINUTE_MS, Config
from src.research_lab.orderflow_ml.bars import E8, MinuteBar
from src.research_lab.protocol import CostModel

VARIANTS = ("FEST", "TEIL", "NACHZIEHEN", "AUFBAU")


@dataclass(frozen=True, slots=True)
class Params:
    trail_r: float = 1.0      # NACHZIEHEN/AUFBAU: distance of the trailing stop behind the best price, in R
    add_at_r: float = 2.0     # AUFBAU: floating profit that allows the second position
    lock_r: float = 1.0       # AUFBAU: the first stop moves here when the second position opens
    add_share: float = 1 / 3  # AUFBAU: risk of the second position as a share of the floating profit (video: a third)


@dataclass
class _Leg:
    size: float      # in units of the first position
    entry: float
    stop: float
    open: bool = True
    exit: float = 0.0
    stopped: bool = False


def _leg_r(leg: _Leg, direction: int, risk: float, costs: CostModel) -> float:
    gross = (leg.exit - leg.entry) * direction / risk
    fee = costs.fee * (leg.entry + leg.exit)
    slip = costs.slippage * leg.entry + (costs.stop_slippage if leg.stopped else costs.slippage) * leg.exit
    return leg.size * (gross - (fee + slip) / risk)


def replay(trade: dict, bars: Sequence[MinuteBar], variant: str, cfg: Config = DEFAULT_CONFIG,
           params: Params = Params()) -> dict:
    """Net R and exit reason of one trade under ``variant``. ``bars`` start at the fill minute (ascending)."""
    if variant not in VARIANTS:
        raise ValueError(variant)
    d, entry, stop0, target = trade["direction"], trade["entry"], trade["stop"], trade["target"]
    risk = abs(entry - stop0)
    if risk <= 0:
        raise ValueError("trade without risk")
    costs = cfg.costs()
    legs = [_Leg(1.0, entry, stop0)]
    tf = trade.get("tf", 30)
    fill = trade["fill_ms"]
    hold = cfg.hold_limit_minutes(tf) * MINUTE_MS
    best, mfe, reason, trailing, added, half_done = entry, 0.0, "", False, False, False

    def close_all(price: float, why: str, stopped: bool = False) -> None:
        nonlocal reason
        for leg in legs:
            if leg.open:
                leg.open, leg.exit, leg.stopped = False, price, stopped
        reason = why

    for bar in bars:
        t = bar.window_start_ms
        if t < fill or not bar.has_trades:
            continue
        h, l, c = bar.high_price_e8 / E8, bar.low_price_e8 / E8, bar.last_price_e8 / E8
        # 1. stops (each open leg)
        for leg in legs:
            if leg.open and (l <= leg.stop if d > 0 else h >= leg.stop):
                leg.open, leg.exit, leg.stopped = False, leg.stop, True
        if not any(leg.open for leg in legs):
            reason = "STOP"
            break
        # 2. favourable side
        fav = h if d > 0 else l
        best = max(best, fav) if d > 0 else min(best, fav)
        mfe = max(mfe, (best - entry) * d / risk)
        if variant == "FEST" and (h >= target if d > 0 else l <= target):
            close_all(target, "TARGET")
            break
        if variant == "TEIL":
            if not half_done and mfe >= 1.0:
                half = _Leg(0.5, entry, stop0, False, entry + risk * d)   # half off at +1 R
                legs[0].size = 0.5
                legs[0].stop = entry                                       # rest to break-even
                legs.append(half)
                half_done = True
            if h >= target if d > 0 else l <= target:
                close_all(target, "TARGET")
                break
        if variant in ("NACHZIEHEN", "AUFBAU"):
            if mfe >= 1.0:
                trailing = True
            if variant == "AUFBAU" and not added and mfe >= params.add_at_r:
                lock = entry + params.lock_r * risk * d
                legs[0].stop = lock if d > 0 and lock > legs[0].stop or d < 0 and lock < legs[0].stop else legs[0].stop
                floating = (c - entry) * d / risk
                dist = abs(c - legs[0].stop)
                if floating > 0 and dist > 0 and (c - legs[0].stop) * d > 0:
                    size = params.add_share * floating * risk / dist      # its risk = share x floating profit
                    legs.append(_Leg(size, c, legs[0].stop))
                added = True
            if trailing:
                trail = best - params.trail_r * risk * d
                for leg in legs:
                    if leg.open and (trail > leg.stop if d > 0 else trail < leg.stop):
                        leg.stop = trail
        # 3. time limits (same rule as the tracker)
        held = t - fill
        if held >= hold:
            close_all(c, "MAX_HOLD")
            break
        if held >= cfg.time_stop_bars * tf * MINUTE_MS and mfe < cfg.time_stop_mfe_r:
            close_all(c, "TIME_STOP")
            break
    else:
        close_all(bars[-1].last_price_e8 / E8 if bars else entry, "DATENENDE")
    return {"variante": variant, "netto_r": round(sum(_leg_r(leg, d, risk, costs) for leg in legs), 6),
            "grund": reason, "beine": len(legs), "mfe_r": round(mfe, 4)}


def summarize(rows: Sequence[dict]) -> dict:
    out: dict = {}
    for v in VARIANTS:
        xs = sorted(r[v]["netto_r"] for r in rows)
        if not xs:
            out[v] = {"n": 0}
            continue
        n = len(xs)
        equity = peak = dd = 0.0
        for r in rows:
            equity += r[v]["netto_r"]
            peak = max(peak, equity)
            dd = max(dd, peak - equity)
        out[v] = {"n": n, "summe": round(sum(xs), 3), "mittel": round(sum(xs) / n, 4), "median": round(xs[n // 2], 4),
                  "treffer": round(sum(x > 0 for x in xs) / n, 4), "schlechtester": round(xs[0], 3),
                  "bester": round(xs[-1], 3), "max_drawdown_r": round(dd, 3)}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from src.research_lab.orderflow_ml.store import MinuteBarStore
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.of2.management")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--trades", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    run = json.loads(args.trades.read_text())
    cfg = DEFAULT_CONFIG
    store = MinuteBarStore(args.bars)
    present = set(store.present_days())
    cache: dict = {}
    rows = []
    for trade in sorted(run["trades"], key=lambda r: r["fill_ms"]):
        first = datetime.fromtimestamp(trade["fill_ms"] / 1000, tz=timezone.utc).date()
        days = [first + timedelta(days=i) for i in range(cfg.longest_hold_minutes // 1440 + 2)]
        bars: list[MinuteBar] = []
        for day in days:
            if day not in present:
                break
            if day not in cache:
                if len(cache) > 8:
                    cache.clear()
                cache[day] = list(store.load(day))
            bars += cache[day]
        row = {"model": trade["model"], "confirmed": trade["confirmed"], "fest_engine": trade["net_r"]}
        for v in VARIANTS:
            row[v] = replay(trade, bars, v, cfg)
        rows.append(row)
    result = {"quelle": str(args.trades), "abschnitt": run.get("abschnitt"), "config_digest": run.get("config_digest"),
              "alle": summarize(rows), "nur_of": summarize([r for r in rows if r["confirmed"]]),
              "abweichung_fest": round(max((abs(r["FEST"]["netto_r"] - r["fest_engine"]) for r in rows), default=0.0), 6),
              "modell": {m: summarize([r for r in rows if r["model"] == m]) for m in sorted({r["model"] for r in rows})},
              "trades": rows}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "of2_management.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: result[k] for k in ("alle", "nur_of", "abweichung_fest")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
