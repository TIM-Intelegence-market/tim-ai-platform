"""Zone strength: overlapping chart marks weighted into zones (rule ``ZONE_RULES``, fixed, not fitted).

Input is the chart model the interactive chart draws (``chart_live.build_live_chart``, served at
``/api/chart/live``). Every current mark within ``RANGE_PCT`` of the price gets a weight by its kind
(``weight``); marks closer than ``WIDTH_PCT`` to each other form one zone; a zone's strength is the sum of its
weights plus a bonus for earlier rejections (wick into the zone, close back out). Weights are a starting
judgement written down before any result, not an optimum.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

RANGE_PCT = 4.0       # marks this far from the price are looked at
WIDTH_PCT = 0.40      # one zone spans at most this much (% of price)
PAD_PCT = 0.05        # a single mark becomes a zone of +- this much
STRONG = 6.0          # a zone with at least this strength is "strong": the AI is asked there
BUSY_BARS = 48        # busiest price (most traded) over this many footprint bars
REACT_BARS = 96       # earlier rejections counted over this many candles before the current one
REACT_EACH, REACT_MAX = 0.5, 1.5
ZONE_RULES = (f"marks within {RANGE_PCT} %", f"zone width <= {WIDTH_PCT} %", f"strong >= {STRONG}",
              f"busiest price over {BUSY_BARS} bars = 2", f"rejection +{REACT_EACH} each, max {REACT_MAX}")

GROUP_WEIGHT = {"gamma_ob": 4.0, "year": 3.0, "quarter": 3.0, "month": 3.0, "week": 2.0, "naked": 2.0, "day": 1.5,
                "liq": 1.5, "running": 1.0, "session": 1.0, "ib": 1.0, "vwap": 1.0}


def weight(group: str, label: str) -> float:
    """Weight of one chart mark; 0 = not a zone mark (trend lines, history, targets, bands)."""
    if group == "gamma":
        if "Call Wall" in label or "Put Wall" in label:
            return 3.0
        if "OI-Wand" in label or "Flip" in label:
            return 2.0
        return 1.0 if ("Max Pain" in label or "EM " in label) else 0.0
    if group == "structure":
        return 1.5 if ("Strong" in label or "Weak" in label) else 0.0
    return GROUP_WEIGHT.get(group, 0.0)


def marks(model: Mapping[str, Any], price: float) -> list[dict[str, Any]]:
    """Current chart marks near the price, each with its weight (finished history and sloped lines left out)."""
    out, seen = [], set()
    for d in model.get("drawings") or []:
        group, label = str(d.get("group") or ""), str(d.get("label") or d.get("name") or "")
        if d.get("finished") or d.get("curve") or d.get("price") is None:
            continue
        w = weight(group, label)
        if w <= 0:
            continue
        band = d.get("band")
        low, high = (float(band[0]), float(band[1])) if isinstance(band, (list, tuple)) and len(band) == 2 else (float(d["price"]),) * 2
        mid = (low + high) / 2
        if abs(mid - price) / price * 100 > RANGE_PCT or (label, round(mid, 1)) in seen:
            continue
        seen.add((label, round(mid, 1)))
        out.append({"low": min(low, high), "high": max(low, high), "price": mid, "label": label, "group": group, "weight": w})
    busy = busiest_price(model)
    if busy is not None and abs(busy - price) / price * 100 <= RANGE_PCT:
        out.append({"low": busy, "high": busy, "price": busy, "label": "meistgehandelter Preis", "group": "fp", "weight": 2.0})
    return out


def busiest_price(model: Mapping[str, Any]) -> float | None:
    """Price row with the most traded volume over the last ``BUSY_BARS`` footprint bars (where buyers and sellers
    met most often)."""
    rows: dict[float, float] = {}
    for bar in list((model.get("footprint") or {}).get("bars") or [])[-BUSY_BARS:]:
        for level in bar.get("levels") or []:
            price, bid, ask = level[0], level[1], level[2]
            rows[float(price)] = rows.get(float(price), 0.0) + float(bid) + float(ask)
    return max(rows, key=rows.__getitem__) if rows else None


def rejections(zone: Mapping[str, Any], candles: Sequence[Mapping[str, Any]]) -> int:
    """Candles whose wick entered the zone but closed back on the side they came from."""
    count = 0
    for c in candles:
        high, low, close = float(c["high"]), float(c["low"]), float(c["close"])
        if low <= zone["high"] and close > zone["high"] and low >= zone["low"] - (zone["high"] - zone["low"]) * 2:
            count += 1          # from above: dipped in, closed above
        elif high >= zone["low"] and close < zone["low"] and high <= zone["high"] + (zone["high"] - zone["low"]) * 2:
            count += 1          # from below: poked in, closed below
    return count


def build(model: Mapping[str, Any], price: float, history: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Zones near ``price``, strongest first. ``history``: closed candles before the current one (rejections)."""
    points = sorted(marks(model, price), key=lambda m: m["price"])
    clusters: list[list[dict[str, Any]]] = []
    for m in points:
        if clusters and m["price"] - clusters[-1][0]["price"] <= price * WIDTH_PCT / 100:
            clusters[-1].append(m)
        else:
            clusters.append([m])
    pad = price * PAD_PCT / 100
    recent = list(history)[-REACT_BARS:]
    zones = []
    for members in clusters:
        low = min(m["low"] for m in members) - pad
        high = max(m["high"] for m in members) + pad
        zone = {"low": round(low, 1), "high": round(high, 1), "center": round((low + high) / 2, 1),
                "sources": [m["label"] for m in members], "groups": sorted({m["group"] for m in members})}
        bounce = rejections(zone, recent)
        bonus = min(REACT_MAX, bounce * REACT_EACH)
        zone["rejections"] = bounce
        zone["strength"] = round(sum(m["weight"] for m in members) + bonus, 2)
        zones.append(zone)
    return sorted(zones, key=lambda z: -z["strength"])
