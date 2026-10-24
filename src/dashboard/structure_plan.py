"""Rule version "struct/1": stop and targets from market structure (Broncx).

TIM's first rule version (the plan journal) puts the stop a flat 0.5 or 1 %
behind the entry zone and the targets at fixed 1.5R, 2R and 3R. Broncx works
the other way round: the stop sits behind the swing that would prove the idea
wrong, and the targets are the next places where liquidity rests (poor
highs/lows, naked POCs, yesterday's value, session highs/lows, swing highs and
lows). If the first such place is less than 1.5R away, there is no trade.

This module only rewrites TIM's plans; entry, invalidation and the way the
journal follows a plan stay the same, so both rule versions can run side by
side and be compared on the same market. Paper only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import clean_candles, swing_points

RULE = "struct/1"
MIN_FIRST_R = 1.5
STOP_BUFFER = 0.0005  # 0.05 % behind the swing (wicks that only tag the swing)
MERGE_GAP = 0.0005  # levels closer than 0.05 % count as one place
SWING_WIDTH = 2
VISIBLE = 80  # same 15m window as the Setup-Pfad


def candles_until(series: Mapping[str, Sequence[Mapping[str, Any]]], at: datetime) -> dict[str, list[dict[str, Any]]]:
    """Closed candles only: the struct rule never looks past the plan's 15m close."""
    result = {}
    for timeframe in ("15m", "1h"):
        result[timeframe] = [c for c in clean_candles(series.get(timeframe) or [], timeframe) if c["close_time"] <= at]
    return result


def _swings(candles: Sequence[Mapping[str, Any]]) -> tuple[list[float], list[float]]:
    swings = swing_points(list(candles)[-VISIBLE:], SWING_WIDTH)
    return [s["price"] for s in swings if s["kind"] == "HIGH"], [s["price"] for s in swings if s["kind"] == "LOW"]


def liquidity(prep: Mapping[str, Any] | None, highs: Sequence[float], lows: Sequence[float]) -> list[dict[str, Any]]:
    """Candidate targets: the preparation map's levels plus visible 15m swings."""
    places = [{"price": float(level["price"]), "label": level["label"]} for level in (prep or {}).get("levels") or []]
    places += [{"price": float(p), "label": "15m Swing-Hoch"} for p in highs]
    places += [{"price": float(p), "label": "15m Swing-Tief"} for p in lows]
    return places


def _ordered(places: Sequence[Mapping[str, Any]], entry: float, long: bool) -> list[dict[str, Any]]:
    beyond = [p for p in places if (p["price"] > entry if long else p["price"] < entry)]
    beyond.sort(key=lambda p: abs(p["price"] - entry))
    merged: list[dict[str, Any]] = []
    for place in beyond:
        if merged and abs(place["price"] - merged[-1]["price"]) <= entry * MERGE_GAP:
            continue
        merged.append(dict(place))
    return merged


def structural_plan(plan: Mapping[str, Any], highs: Sequence[float], lows: Sequence[float],
                    places: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    """Rewrite one TIM plan; returns (plan, None) or (None, reason it was dropped)."""
    long = plan["direction"] == "LONG"
    entry = float(plan["entry"])
    zone = [float(v) for v in (plan.get("entry_low"), plan.get("entry_high"), entry) if v is not None]
    edge = min(zone) if long else max(zone)
    if long:
        below = [p for p in lows if p < edge]
        if not below:
            return None, "kein Swing-Tief unter der Einstiegszone"
        swing = max(below)
        stop = swing * (1 - STOP_BUFFER)
    else:
        above = [p for p in highs if p > edge]
        if not above:
            return None, "kein Swing-Hoch über der Einstiegszone"
        swing = min(above)
        stop = swing * (1 + STOP_BUFFER)
    risk = abs(entry - stop)
    targets = _ordered(places, entry, long)
    if not targets:
        return None, "kein Liquiditätsziel jenseits des Einstiegs"
    first_r = abs(targets[0]["price"] - entry) / risk
    if first_r < MIN_FIRST_R:
        return None, f"nächstes Ziel nur {first_r:.2f} R entfernt"
    chosen = targets[:3]
    while len(chosen) < 3:
        chosen.append(chosen[-1])
    rewritten = dict(plan)
    rewritten.update(
        rule=RULE,
        stop=round(stop, 2),
        stop_swing=swing,
        targets=[round(t["price"], 2) for t in chosen],
        target_labels=[t["label"] for t in chosen],
        tim_stop=plan["stop"],
        tim_targets=list(plan["targets"]),
    )
    return rewritten, None


def structural_plans(plans: Sequence[Mapping[str, Any]], candles_15m: Sequence[Mapping[str, Any]],
                     prep: Mapping[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    highs, lows = _swings(candles_15m)
    places = liquidity(prep, highs, lows)
    kept, dropped = [], []
    for plan in plans:
        rewritten, reason = structural_plan(plan, highs, lows, places)
        if rewritten:
            kept.append(rewritten)
        else:
            dropped.append(f"{plan['direction']}: {reason}")
    return kept, dropped
