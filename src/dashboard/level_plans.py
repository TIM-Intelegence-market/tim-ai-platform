"""Rule version "level/1": plans at the day's and week's main levels.

TIM's orderflow pipeline only writes plans when price tests the range edge or
breaks out. In a balance it returns two neutral scenarios without a zone, so
the chart shows no plan at all. A trader still has a plan then: buy the next
main level below, sell the next main level above, and only when the risk to
the swing behind the level is small against the next target.

Main levels (anchors) come from the preparation map
(``src.dashboard.session_map``): yesterday's VAH/VAL/POC and high/low, last
week's high/low and VAH/VAL/POC, naked POCs. Levels closer than
``CLUSTER_GAP`` are one place (confluence). Per direction the nearest place
within ``MAX_DISTANCE`` that passes the checks becomes the plan:

- zone: the place's price span plus ``ZONE_PAD``, limit entry at the first
  touch (top of the zone for a long, bottom for a short),
- stop: behind the nearest 30m swing beyond the zone (same rule as struct/1),
  at most ``MAX_RISK`` away,
- targets: the next liquidity places beyond the zone (levels and 30m swings),
  the first one at least ``MIN_FIRST_R`` away,
- invalidation: a 30m close beyond that swing.

Session and initial-balance highs/lows are targets only, never anchors. The
plan carries whether it trades with or against the 1D/4h bias and where price
stands against yesterday's value. Paper only: these are plans for the chart,
not orders, and no plan is marked confirmed here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import _fmt
from src.dashboard.structure_plan import MERGE_GAP, MIN_FIRST_R, STOP_BUFFER, _ordered, _swings, liquidity

RULE = "level/1"
ANCHOR_SOURCES = ("Profil Vortag", "Vortag", "Vorwoche", "Profil Vorwoche", "unberührter Tages-POC")
CLUSTER_GAP = 0.0015  # anchors within 0.15 % are one place
ZONE_PAD = 0.0005  # zone reaches 0.05 % beyond the place
MAX_DISTANCE = 0.03  # only places within 3 % of price
MAX_RISK = 0.02  # entry to stop at most 2 %
MAX_PLACES = 3  # places tried per direction
STALE_SECONDS = 3600  # no plans when the last 30m close is older than this
ENTRY_MODEL = "LEVEL_LIMIT"
SCENARIO_TYPE = "LEVEL_REACTION"


def _is_anchor(level: Mapping[str, Any]) -> bool:
    # Same-price levels are merged by the preparation map, e.g. "Vortag · Session".
    return bool(level.get("price")) and any(part in ANCHOR_SOURCES for part in str(level.get("source") or "").split(" · "))


def anchors(prep: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Main levels from the preparation map, merged into places by price."""
    levels = sorted(
        (dict(level) for level in (prep or {}).get("levels") or [] if _is_anchor(level)),
        key=lambda level: float(level["price"]),
    )
    places: list[dict[str, Any]] = []
    for level in levels:
        price = float(level["price"])
        # Measured from the place's lowest level, so a chain of close levels never grows wider than CLUSTER_GAP.
        if places and price - places[-1]["low"] <= places[-1]["low"] * CLUSTER_GAP:
            place = places[-1]
            place["high"] = price
            place["labels"].append(level["label"])
        else:
            places.append({"low": price, "high": price, "labels": [level["label"]]})
    return places


def _trend(direction: str, bias: str | None) -> str:
    if bias in ("LONG", "SHORT"):
        return "mit Trend" if bias == direction else "gegen den Trend"
    return "ohne klaren Bias"


def level_plan(place: Mapping[str, Any], direction: str, last: float, highs: Sequence[float], lows: Sequence[float],
               targets_from: Sequence[Mapping[str, Any]], bias: str | None, location: str | None,
               plan_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """One plan at one place; returns (plan, None) or (None, reason)."""
    long = direction == "LONG"
    zone_low, zone_high = place["low"] * (1 - ZONE_PAD), place["high"] * (1 + ZONE_PAD)
    entry = place["high"] if long else place["low"]
    name = " + ".join(place["labels"])
    if long:
        below = [p for p in lows if p < zone_low]
        if not below:
            return None, f"{name}: kein 30m-Swing-Tief unter der Zone"
        swing = max(below)
        stop = swing * (1 - STOP_BUFFER)
    else:
        above = [p for p in highs if p > zone_high]
        if not above:
            return None, f"{name}: kein 30m-Swing-Hoch über der Zone"
        swing = min(above)
        stop = swing * (1 + STOP_BUFFER)
    risk = abs(entry - stop)
    if risk > entry * MAX_RISK:
        return None, f"{name}: Stop {risk / entry * 100:.1f} % entfernt (max. {MAX_RISK * 100:.0f} %)"
    edge = zone_high if long else zone_low
    beyond = [p for p in _ordered(targets_from, edge, long) if abs(p["price"] - edge) > edge * MERGE_GAP]
    if not beyond:
        return None, f"{name}: kein Ziel jenseits der Zone"
    first_r = abs(beyond[0]["price"] - entry) / risk
    if first_r < MIN_FIRST_R:
        return None, f"{name}: nächstes Ziel nur {first_r:.2f} R entfernt"
    chosen = beyond[:3]
    while len(chosen) < 3:
        chosen.append(chosen[-1])
    targets = [round(t["price"], 2) for t in chosen]
    trend = _trend(direction, bias)
    side = "<" if long else ">"
    gap = f"{risk / entry * 100:.1f}".replace(".", ",")
    where = "unter" if long else "über"
    plan_text = f"PLAN {plan_id} {direction}  Limit {_fmt(entry)} am {name} ({trend})"
    reaction = (f"Ablehnung: 30m-Schluss zurück über {_fmt(zone_high)}" if long
                else f"Ablehnung: 30m-Schluss zurück unter {_fmt(zone_low)}")
    return {
        "id": plan_id,
        "rule": RULE,
        "entry_model": ENTRY_MODEL,
        "type": SCENARIO_TYPE,
        "direction": direction,
        "state": "PROPOSED",
        "score": None,
        "score_type": None,
        "plan_text": plan_text,
        "anchor": name,
        "anchor_labels": list(place["labels"]),
        "trend": trend,
        "location": location,
        "distance_pct": round((entry - last) / last * 100, 3),
        "trigger": None,
        "entry_low": round(zone_low, 2),
        "entry_high": round(zone_high, 2),
        "invalidation_level": {"level": round(swing, 2), "side": side,
                               "text": f"Ungültig {plan_id}: 30m-Schluss {side} {_fmt(swing)} (Swing)"},
        "invalidation": ["30m_close_beyond_swing"],
        "missing_confirmations": ["Kurs erreicht die Zone", reaction, f"keine zwei 30m-Schlüsse {'unter' if long else 'über'} der Zone"],
        "preview": {
            "entry": round(entry, 2), "stop": round(stop, 2), "targets": targets,
            "target_labels": [t["label"] for t in chosen], "reward_risk": round(first_r, 2),
            "stop_text": f"Stop {plan_id} {_fmt(stop)} ({gap} % {where} Einstieg, hinter Swing {_fmt(swing)})",
            "note": "Level-Plan level/1, nicht bestätigt",
        },
        "grade": None,
    }, None


def build_level_plans(prep: Mapping[str, Any] | None, candles_30m: Sequence[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    """Up to one long and one short plan at the nearest main levels."""
    result: dict[str, Any] = {"rule": RULE, "plans": [], "dropped": []}
    done = [c for c in candles_30m if c["close_time"] <= now]
    if len(done) < 10:
        result["dropped"].append("zu wenige 30m-Kerzen")
        return result
    if (now - done[-1]["close_time"]).total_seconds() > STALE_SECONDS:
        result["dropped"].append("30m-Kerzen veraltet: keine neuen Level-Pläne")
        return result
    last = float(done[-1]["close"])
    highs, lows = _swings(done)
    targets_from = liquidity(prep, highs, lows)
    bias = ((prep or {}).get("bias") or {}).get("bias")
    location = ((prep or {}).get("location") or {}).get("label")
    places = anchors(prep)
    for direction, plan_id in (("LONG", "L1"), ("SHORT", "S1")):
        long = direction == "LONG"
        side = [p for p in places if (p["high"] < last if long else p["low"] > last)
                and abs((p["high"] if long else p["low"]) - last) <= last * MAX_DISTANCE]
        side.sort(key=lambda p: abs((p["high"] if long else p["low"]) - last))
        for place in side[:MAX_PLACES]:
            plan, reason = level_plan(place, direction, last, highs, lows, targets_from, bias, location, plan_id)
            if plan:
                result["plans"].append(plan)
                break
            result["dropped"].append(f"{direction}: {reason}")
        else:
            if not side:
                result["dropped"].append(f"{direction}: kein Hauptlevel innerhalb {MAX_DISTANCE * 100:.0f} %")
    return result
