"""Rule version "vp/1": paper plans from the volume-profile context (Uzi 03.11.2026).

Source: reel DfQG9buhylb (tradingelder, "My entire system using volume profile + orderflow"),
which the chart summary shows since PR #95 (``session_map.value_context``), plus reel
DfQwG8pumy5 (skydweller.trades, five footprint mistakes): one loud candle is no signal, a print
needs a map, absorption at a low is strength, and imbalances in thin hours mean little.

Fixed before the first plan (no tuning on the journal's own results):

- context: today's developing value against the previous day's value (``value_context``).
  HIGHER / LOWER / INSIDE are traded. OVERLAP_HIGHER / OVERLAP_LOWER only with absorption
  (the reel: "be picky"). WIDER, EARLY and UNKNOWN: no plan.
- trigger: the 30m candle that just closed touched a playbook entry level (previous VAH / POC
  for a long in HIGHER, VAL / POC for a short in LOWER, both edges in INSIDE) and closed back on
  the trade side of it. With two levels touched, the deeper one counts.
- entry: limit at that candle's close.
- stop (``STOP_BUFFER`` behind): in the trend and overlap contexts the reel's invalid level, the
  opposite previous value edge; in INSIDE the touch candle's extreme beyond the faded edge, the
  place the absorption must hold ("0 ticks lower"). A 30m close beyond the same level invalidates.
- target: the playbook target (nearest naked POC in trade direction, the previous POC in
  INSIDE), all three journal targets at that one price; reward below ``MIN_R`` x risk: no plan.
  The reel names no reward/risk minimum; 1 R only keeps the target at least as far as the stop.
- recorded, not filtered (for the later "lessons -> filter" step): the candle's taker delta from
  TIM's aggTrades (``absorption`` = delta against the trade at the touch) and its volume against
  the average 30m volume of the same UTC half hour over the last ``HOUR_DAYS`` days.
- also recorded (Uzi 04.11.2026, reel DfTgoOTx6Qs on call walls): the newest options-gamma
  snapshot taken by the close (``gex``: call wall, put wall, flip, regime, distances in %),
  so a later check can ask whether a value edge holds better near a wall. Never a filter.

The journal's own gates still apply (invalid on arrival, lost levels, cost limit 0.25 R).
Paper only: no order, no real money.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from src.dashboard.structure_plan import STOP_BUFFER

RULE = "vp/1"
SCENARIO_TYPE = "VP_CONTEXT"
ENTRY_MODEL = "VP_REACTION"
TRADED = ("HIGHER", "LOWER", "INSIDE")
PICKY = ("OVERLAP_HIGHER", "OVERLAP_LOWER")
STALE_SECONDS = 3600
MIN_R = 1.0  # target at least as far from the entry as the stop
HOUR_DAYS = 14
GEX_MAX_AGE_SECONDS = 1200  # same freshness as the dashboard (gamma_data.STALE_AFTER)
WALL_NEAR_PCT = 0.3  # a wall within 0.3 % of the touched level counts as "at the level"  # days behind the same-half-hour volume average
SOURCE = "Reels tradingelder (DfQG9buhylb) + skydweller.trades (DfQwG8pumy5), Uzi 03.11.2026"


def bar_delta(footprint: Mapping[str, Any] | None, candle: Mapping[str, Any]) -> float | None:
    """Taker delta (ask - bid) of one 30m candle from the aggTrades store, None without data."""
    if not footprint or not footprint.get("days"):
        return None
    from src.dashboard.footprint_data import bar_deltas

    start = int(candle["open_time"].timestamp())
    deltas = bar_deltas(footprint, [start, start + 1800], 1800)
    return None if start not in deltas else round(deltas[start], 4)


def volume_vs_hour(candles: Sequence[Mapping[str, Any]], candle: Mapping[str, Any]) -> float | None:
    """The candle's volume against the mean of the same UTC half hour over the previous HOUR_DAYS days."""
    slot = (candle["open_time"].hour, candle["open_time"].minute)
    earlier = [c["volume"] for c in candles if c["open_time"] < candle["open_time"]
               and (c["open_time"].hour, c["open_time"].minute) == slot and c.get("volume")][-HOUR_DAYS:]
    if not earlier or not candle.get("volume"):
        return None
    return round(candle["volume"] / (sum(earlier) / len(earlier)), 3)


def gex_context(snapshot: Mapping[str, Any] | None, level: float, at: datetime) -> dict[str, Any] | None:
    """Walls and flip of the newest gamma snapshot taken by ``at`` (no look-ahead), against the touched level."""
    if not snapshot:
        return None
    try:
        taken = datetime.fromisoformat(str(snapshot["as_of"]))
        overall = snapshot["all_expiries"]
    except (KeyError, TypeError, ValueError):
        return None
    age = (at - taken).total_seconds()
    if age < 0 or age > GEX_MAX_AGE_SECONDS:
        return {"as_of": snapshot.get("as_of"), "usable": False, "reason": "after the close" if age < 0 else "stale"}

    def distance(price: Any) -> float | None:
        return None if price is None else round((float(price) - level) / level * 100, 3)

    walls = {"call_wall": overall.get("call_wall"), "put_wall": overall.get("put_wall"), "gamma_flip": overall.get("gamma_flip")}
    dist = {f"{key}_dist_pct": distance(price) for key, price in walls.items()}
    return {"as_of": snapshot["as_of"], "usable": True, "age_seconds": int(age), "regime": overall.get("regime"), **walls, **dist,
            "wall_at_level": any(v is not None and abs(v) <= WALL_NEAR_PCT for k, v in dist.items() if k != "gamma_flip_dist_pct")}


def _touched(item: Mapping[str, Any], candle: Mapping[str, Any]) -> dict[str, Any] | None:
    """The deepest entry level the candle touched and closed back beyond, or None."""
    long = item["direction"] == "LONG"
    hit = None
    for level in item["entry"]:
        price = float(level["price"])
        if long and candle["low"] <= price < candle["close"]:
            hit = level if hit is None or price < float(hit["price"]) else hit
        if not long and candle["high"] >= price > candle["close"]:
            hit = level if hit is None or price > float(hit["price"]) else hit
    return hit


def vp_plan(item: Mapping[str, Any], context: str, candle: Mapping[str, Any], delta: float | None,
            volume_ratio: float | None, gex: Mapping[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """One plan from one playbook entry at the closed candle; returns (plan, None) or (None, reason)."""
    direction = item["direction"]
    long = direction == "LONG"
    level = _touched(item, candle)
    if level is None:
        return None, None  # no touch: nothing to note
    name = f"{direction}: {level['label']}"
    absorption = None if delta is None else (delta < 0 if long else delta > 0)
    if context in PICKY and not absorption:
        return None, f"{name}: Überlappung ohne Absorption (wählerisch)"
    target = item.get("target")
    if not target:
        return None, f"{name}: kein Ziel (kein naked POC in Handelsrichtung)"
    entry = float(candle["close"])
    extreme = float(candle["low"] if long else candle["high"])
    invalid = float(item["invalid"]["price"])
    behind = extreme if context == "INSIDE" else invalid
    stop = behind * (1 - STOP_BUFFER) if long else behind * (1 + STOP_BUFFER)
    risk = abs(entry - stop)
    goal = float(target["price"])
    if (long and goal <= entry) or (not long and goal >= entry) or risk <= 0:
        return None, f"{name}: Ziel liegt nicht in Handelsrichtung"
    first_r = abs(goal - entry) / risk
    if first_r < MIN_R:
        return None, f"{name}: nächstes Ziel nur {first_r:.2f} R entfernt"
    side = "<" if long else ">"
    plan_id = "V1" if long else "V2"
    return {
        "rule": RULE,
        "scenario_id": plan_id,
        "scenario_type": SCENARIO_TYPE,
        "direction": direction,
        "entry_model": ENTRY_MODEL,
        "plan_text": f"PLAN {plan_id} {direction} {entry:.2f}: Reaktion an {level['label']} ({context})",
        "anchor": level["label"],
        "value_context": context,
        "entry_low": round(min(entry, float(level["price"])), 2),
        "entry_high": round(max(entry, float(level["price"])), 2),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "targets": [round(goal, 2)] * 3,
        "target_labels": [target["label"]] * 3,
        "invalidation_level": round(behind, 2),
        "invalidation_side": side,
        "scenario_state": "PROPOSED",
        "score": None,
        "missing_confirmations": [],
        "touch": {"level": level["label"], "price": round(float(level["price"]), 2), "extreme": round(extreme, 2)},
        "delta": delta,
        "absorption": absorption,
        "volume_vs_hour": volume_ratio,
        "gex": dict(gex) if gex else None,
        "vp_source": SOURCE,
        "grade": None,
    }, None


def build_vp_plans(prep: Mapping[str, Any] | None, candles_30m: Sequence[Mapping[str, Any]], now: datetime,
                   footprint: Mapping[str, Any] | None = None, gamma: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Plans for the 30m candle closed at ``now``: at most one per direction."""
    result: dict[str, Any] = {"rule": RULE, "plans": [], "dropped": []}
    done = [c for c in candles_30m if c["close_time"] <= now]
    if not done or (now - done[-1]["close_time"]).total_seconds() > STALE_SECONDS:
        result["dropped"].append("30m-Kerzen fehlen oder veraltet")
        return result
    context = ((prep or {}).get("value_context") or {})
    state = context.get("state")
    if state not in TRADED + PICKY:
        return result
    candle = done[-1]
    delta = bar_delta(footprint, candle)
    ratio = volume_vs_hour(done, candle)
    for item in context.get("playbook") or []:
        level = _touched(item, candle)
        gex = gex_context(gamma, float(level["price"]), candle["close_time"]) if level else None
        plan, reason = vp_plan(item, state, candle, delta, ratio, gex)
        if plan:
            result["plans"].append(plan)
        elif reason:
            result["dropped"].append(reason)
    return result
