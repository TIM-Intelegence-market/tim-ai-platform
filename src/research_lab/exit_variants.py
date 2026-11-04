"""Exit variants for the plan journal's last third: fixed TP3, runner, or runner only when orderflow agrees.

Uzi, 04.11.2026: the MID long of that day closed at TP3 (78,517), the price ran on to about 81,000.
TIM should let a trade run when the orderflow still pushes, and take the target when it does not.

How it is measured, without look-ahead and without touching the paper journal:

- The plan journal books a third at TP1, a third at TP2 and the rest at TP3 (or at the stop).
  Up to TP2 every variant here follows exactly the path the journal booked (same fills, same stops,
  same moves of the stop). Only the last third after the TP2 hit is followed again, on 1m candles.
- ``FEST``: the journal's own rule, recomputed (TP3, stop, invalidation, timeout). Checks the replay.
  The journal trails the stop behind the latest confirmed swing of the plan timeframe at every plan
  close (``plan_journal.judge_trades`` / ``swing_stop``); the replay does the same.
- ``LAEUFER``: no TP3. The last third keeps that trail and ends at the trailed stop, at invalidation
  or at the timeout.
- ``LAEUFER_WEIT``: the same, trailing behind swings one timeframe higher (15m -> 1h, 1h -> 4h): more room.
- ``OF_LAEUFER``: TP3 as booked, unless at the TP3 touch the taker delta of the last ``OF_BARS``
  closed plan bars and the delta since the fill both point in the trade direction (perp first, spot
  if no perp data). Then the last third runs on like ``LAEUFER``. No orderflow data: TP3.

Every decision uses only candles and delta buckets that closed before the minute it is taken in.
Costs: Kraken futures as measured 04.11.2026 (5 bps taker per side, no slippage measured) and the
research protocol 1.1 (5 bps fee, 3 bps slippage, 5 bps on stops) for comparison.

Paper only. Nothing here trades, writes a journal or changes a rule.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import PIVOT_WINDOW, swing_points

VARIANTS = ("FEST", "LAEUFER", "LAEUFER_WEIT", "OF_LAEUFER")
HIGHER = {"15m": "1h", "30m": "1h", "1h": "4h", "4h": "1d"}
THIRD = 1.0 / 3.0
MIN_GAP_R = 0.1  # same as plan_journal.COST_STOP_MIN_GAP_R: the close must be this far beyond a new stop
OF_BARS = 3
TIMEFRAME_MINUTES = {"1m": 1, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
STOP_EXITS = {"STOP", "BREAK_EVEN", "BREAK_EVEN_COSTS", "COST_STOP", "TRAIL_STOP", "RUNNER_STOP"}


@dataclass(frozen=True)
class Costs:
    name: str
    fee: float
    slippage: float
    stop_slippage: float


KRAKEN = Costs("kraken_2026-11-04", 0.0005, 0.0, 0.0)
PROTOCOL = Costs("protocol/1.1", 0.0005, 0.0003, 0.0005)


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def r_of(entry: Mapping[str, Any], price: float) -> float:
    risk = abs(float(entry["entry"]) - float(entry["stop"]))
    move = price - float(entry["entry"]) if entry["direction"] == "LONG" else float(entry["entry"]) - price
    return move / risk if risk else 0.0


def net_r(entry: Mapping[str, Any], legs: Sequence[tuple[float, float, str]], costs: Costs) -> tuple[float, float]:
    """(gross_r, net_r) of a filled plan closed in ``legs`` = [(share, price, reason)].

    Fee and slippage on the whole size at the fill, on each leg at its price; stop slippage on legs
    that close as a stop order. Same structure as plan_journal.costs_r."""
    risk = abs(float(entry["entry"]) - float(entry["stop"]))
    if risk <= 0:
        return 0.0, 0.0
    fill = float(entry.get("fill_price") or entry["entry"])
    gross = sum(share * r_of(entry, price) for share, price, _ in legs)
    cost = (costs.fee + costs.slippage) * fill
    for share, price, reason in legs:
        cost += share * (costs.fee + (costs.stop_slippage if reason in STOP_EXITS else costs.slippage)) * price
    return round(gross, 4), round(gross - cost / risk, 4)


def stop_at(entry: Mapping[str, Any], moment: datetime) -> float:
    """The journal's stop for a filled plan in force at ``moment``: the best of the original stop, every
    move in ``stop_path`` up to then and break-even (plus costs) after TP1. Never back."""
    from src.dashboard.plan_journal import stop_steps

    best = float(entry["stop"])
    for at, price, _ in stop_steps(entry):
        if _time(at) <= moment and r_of(entry, price) > r_of(entry, best):
            best = price
    return best


def _trail(entry: Mapping[str, Any], candles: Sequence[Mapping[str, Any]], close: float, floor: float) -> float:
    """Latest confirmed swing behind the trade since the fill, beyond ``floor`` and at least MIN_GAP_R
    behind the close. ``candles`` must end at the close the decision is taken on."""
    long = entry["direction"] == "LONG"
    filled = _time(entry["filled_at"])
    best = floor
    for swing in swing_points(candles, PIVOT_WINDOW):
        if swing["kind"] != ("LOW" if long else "HIGH") or candles[swing["index"]]["open_time"] < filled:
            continue
        price = float(swing["price"])
        if (price > best if long else price < best) and r_of(entry, close) - r_of(entry, price) >= MIN_GAP_R:
            best = price
    return best


def orderflow_agrees(entry: Mapping[str, Any], deltas: Mapping[int, float], bar_seconds: int, moment: datetime,
                     bars: int = OF_BARS) -> bool | None:
    """True when the delta of the last ``bars`` plan bars closed before ``moment`` and the delta since the
    fill both point in the trade direction; False when not; None without data for those bars."""
    if not deltas:
        return None
    sign = 1.0 if entry["direction"] == "LONG" else -1.0
    end = int(moment.timestamp()) // bar_seconds * bar_seconds  # open of the running bar: excluded
    filled = int(_time(entry["filled_at"]).timestamp()) // bar_seconds * bar_seconds
    recent = [end - bar_seconds * (i + 1) for i in range(bars)]
    if any(bar not in deltas for bar in recent):
        return None
    since = sum(value for bar, value in deltas.items() if filled <= bar < end)
    return sign * sum(deltas[bar] for bar in recent) > 0 and sign * since > 0


def _closes_between(candles: Sequence[Mapping[str, Any]], close_times: Sequence[datetime], start: datetime,
                    end: datetime) -> list[int]:
    """Indices of candles whose close lies in (start, end]."""
    lo, hi = bisect_right(close_times, start), bisect_right(close_times, end)
    return list(range(lo, hi))


def aggregate(minutes: Sequence[Mapping[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    """Complete candles of ``timeframe`` (UTC-aligned) from sorted 1m candles; a bucket with a missing
    minute is left out, so no trail or close is taken on a candle that did not fully exist."""
    size = TIMEFRAME_MINUTES[timeframe] * 60
    groups: dict[int, list[Mapping[str, Any]]] = {}
    for candle in minutes:
        start = int(candle["open_time"].timestamp()) // size * size
        groups.setdefault(start, []).append(candle)
    result = []
    for start in sorted(groups):
        group = groups[start]
        if len(group) != size // 60:
            continue
        opened = datetime.fromtimestamp(start, tz=timezone.utc)
        result.append({"open_time": opened, "close_time": opened + timedelta(seconds=size), "timeframe": timeframe,
                       "open": group[0]["open"], "high": max(c["high"] for c in group),
                       "low": min(c["low"] for c in group), "close": group[-1]["close"]})
    return result


def follow_rest(entry: Mapping[str, Any], minutes: Sequence[Mapping[str, Any]], plan: Sequence[Mapping[str, Any]],
                higher: Sequence[Mapping[str, Any]], variant: str, deltas: Mapping[int, float] | None = None) -> dict[str, Any]:
    """Follow the last third from the TP2 hit under ``variant``. Returns exit time, price, reason
    (or ``OFFEN`` with the last close when the data ends first) and the orderflow verdict if asked."""
    long = entry["direction"] == "LONG"
    start = _time(entry["tp_hits"][1])
    deadline = _time(entry["filled_at"]) + timedelta(hours=float(entry.get("max_hold_hours") or 48))
    stop = stop_at(entry, start)
    tp3 = float(entry["targets"][2])
    level, side = entry.get("invalidation_level"), entry.get("invalidation_side")
    timeframe = str(entry.get("timeframe") or "30m")
    bar_seconds = TIMEFRAME_MINUTES.get(timeframe, 30) * 60
    trail_on = higher if variant == "LAEUFER_WEIT" else plan
    trail_closes = [c["close_time"] for c in trail_on]
    plan_closes = [c["close_time"] for c in plan]
    runner = variant in {"LAEUFER", "LAEUFER_WEIT"}
    verdict: bool | None = None
    seen = start
    result: dict[str, Any] = {"variant": variant}
    best_price = None
    for candle in minutes:
        if candle["open_time"] < start:
            continue
        opened = candle["open_time"]
        # Closes completed since the previous minute: invalidation, then the trail.
        if level is not None:
            for index in _closes_between(plan, plan_closes, seen, opened):
                close = plan[index]["close"]
                if (side == "<" and close < level) or (side == ">" and close > level):
                    return {**result, "exit_at": _iso(plan[index]["close_time"]), "exit_price": close,
                            "exit_reason": "INVALIDATION", "of_verdict": verdict, "best_price": best_price}
        # Every variant trails like the journal (LAEUFER_WEIT on the higher timeframe), from the next minute on.
        new = _closes_between(trail_on, trail_closes, seen, opened)
        if new:
            last = new[-1]
            stop = _trail(entry, trail_on[: last + 1], float(trail_on[last]["close"]), stop)
        seen = opened
        if opened >= deadline:
            return {**result, "exit_at": _iso(opened), "exit_price": candle["open"], "exit_reason": "TIMEOUT",
                    "of_verdict": verdict, "best_price": best_price}
        extreme = candle["high"] if long else candle["low"]
        best_price = extreme if best_price is None or (extreme > best_price if long else extreme < best_price) else best_price
        if (long and candle["low"] <= stop) or (not long and candle["high"] >= stop):
            reason = "RUNNER_STOP" if r_of(entry, stop) > r_of(entry, stop_at(entry, start)) else "STOP"
            return {**result, "exit_at": _iso(candle["close_time"]), "exit_price": stop, "exit_reason": reason,
                    "of_verdict": verdict, "best_price": best_price}
        touched = (long and candle["high"] >= tp3) or (not long and candle["low"] <= tp3)
        if touched and not runner and verdict is None:
            if variant == "OF_LAEUFER":
                verdict = orderflow_agrees(entry, deltas or {}, bar_seconds, opened)
            if not verdict:
                return {**result, "exit_at": _iso(candle["close_time"]), "exit_price": tp3, "exit_reason": "TP3",
                        "of_verdict": verdict, "best_price": best_price}
    last = minutes[-1] if minutes else None
    return {**result, "exit_at": None, "exit_price": last["close"] if last else None, "exit_reason": "OFFEN",
            "of_verdict": verdict, "best_price": best_price, "marked_at": _iso(last["close_time"]) if last else None}


def evaluate_entry(entry: Mapping[str, Any], minutes: Sequence[Mapping[str, Any]], plan: Sequence[Mapping[str, Any]],
                   higher: Sequence[Mapping[str, Any]], deltas: Mapping[int, float] | None = None,
                   costs: Costs = KRAKEN) -> dict[str, Any] | None:
    """All variants for one filled journal entry. None for plans that never filled."""
    if not entry.get("filled_at"):
        return None
    hits = list(entry.get("tp_hits") or [])
    base = {"id": entry.get("id"), "direction": entry["direction"], "timeframe": entry.get("timeframe"),
            "filled_at": entry["filled_at"], "fill_price": entry.get("fill_price") or entry["entry"],
            "stop": entry["stop"], "targets": entry["targets"], "journal_exit": entry.get("exit_reason"),
            "journal_exit_price": entry.get("exit_price"), "journal_net_r": entry.get("net_r"),
            "status": entry.get("status"), "tp_hits": len(hits)}
    variants: dict[str, Any] = {}
    if len(hits) < 2:
        # Up to TP2 every variant is the journal's own path.
        if entry.get("status") != "CLOSED":
            base["variants"] = {name: {"exit_reason": "OFFEN"} for name in VARIANTS}
            return base
        legs = [(THIRD, float(entry["targets"][i]), "TP") for i in range(len(hits))]
        legs.append((1.0 - THIRD * len(hits), float(entry["exit_price"]), str(entry["exit_reason"])))
        gross, net = net_r(entry, legs, costs)
        same = {"exit_at": entry.get("closed_at"), "exit_price": entry["exit_price"], "exit_reason": entry["exit_reason"],
                "gross_r": gross, "net_r": net, "same_as_journal": True}
        base["variants"] = {name: dict(same) for name in VARIANTS}
        return base
    fixed = [(THIRD, float(entry["targets"][0]), "TP"), (THIRD, float(entry["targets"][1]), "TP")]
    for name in VARIANTS:
        rest = follow_rest(entry, minutes, plan, higher, name, deltas)
        if rest["exit_price"] is None:
            variants[name] = rest
            continue
        gross, net = net_r(entry, [*fixed, (THIRD, float(rest["exit_price"]), rest["exit_reason"])], costs)
        variants[name] = {**rest, "gross_r": gross, "net_r": net}
    base["variants"] = variants
    return base


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Sum and mean net R per variant over closed rows (rows where any variant is still open are counted
    apart: their runner is not finished)."""
    done = [r for r in rows if r and all(v.get("exit_reason") != "OFFEN" for v in r["variants"].values())]
    open_rows = [r for r in rows if r and r not in done]
    out: dict[str, Any] = {"trades": len(done), "open": len(open_rows),
                           "reached_tp2": sum(1 for r in done if r["tp_hits"] >= 2)}
    for name in VARIANTS:
        values = [float(r["variants"][name]["net_r"]) for r in done]
        out[name] = {"sum_r": round(sum(values), 3), "mean_r": round(sum(values) / len(values), 3) if values else None,
                     "wins": sum(1 for v in values if v > 0)}
    return out
