"""Summed bubbles: big taker orders at one price within a few minutes, added up (Uzi 24.11.2026 "go Summe").

TIM's bubbles show single taker orders. Other charts (the signal group's MMT view, Uzi's screenshot of 24.11.2026) add up
the orders that hit the same price within minutes, so absorption shows as one big bubble (1K, 835, 776 BTC at
the high of 23.11.) where TIM showed several of 200 to 350 BTC. ``clusters`` does that sum; ``drawings`` turns
the biggest sums into chart lines (group "absorb") that the AI deciders read as zone marks.

Display and context only, no signal. ``MIN_BTC``, ``WINDOW_S`` and ``PRICE_PCT`` were set by eye on that one
screenshot (23./24.11.2026) and are not tested.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

WINDOW_S = 300        # orders within five minutes of the cluster's first order
PRICE_PCT = 0.10      # and within this distance (%) of the cluster's average price
MIN_BTC = 400.0       # a sum below this is no summed bubble
MIN_ORDERS = 3        # a single big order is already a normal bubble
LINES = 8             # biggest sums drawn as lines
LINE_HOURS = 48       # a line older than this is dropped


def orders_from_store(store: Mapping[str, Any] | None, first: float, last: float) -> list[tuple[float, float, float, int]]:
    """(time s, price, quantity, side) of the store's bubbles (``perp_flow`` / ``footprint_data`` day lists) in the window."""
    out = []
    for key in sorted((store or {}).get("bubbles") or {}):
        for time_ms, price, quantity, side in store["bubbles"][key]:
            moment = time_ms / 1000.0
            if first <= moment < last:
                out.append((moment, float(price), float(quantity), 1 if side > 0 else -1))
    return sorted(out)


def clusters(orders: Iterable[Sequence[float]], window_s: float = WINDOW_S, price_pct: float = PRICE_PCT,
             min_btc: float = MIN_BTC, min_orders: int = MIN_ORDERS) -> list[dict[str, Any]]:
    """Orders of one side joined while they stay within ``window_s`` of the first and ``price_pct`` of the running average price."""
    open_by_side: dict[int, list[dict[str, Any]]] = {1: [], -1: []}
    done: list[dict[str, Any]] = []
    for moment, price, quantity, side in sorted(orders):
        side = 1 if side > 0 else -1
        live = [c for c in open_by_side[side] if moment - c["start"] <= window_s]
        done += [c for c in open_by_side[side] if moment - c["start"] > window_s]
        home = next((c for c in live if abs(price - c["usd"] / c["btc"]) / price * 100 <= price_pct), None)
        if home is None:
            home = {"start": moment, "end": moment, "btc": 0.0, "usd": 0.0, "orders": 0, "side": side, "biggest": 0.0}
            live.append(home)
        home["end"], home["btc"], home["usd"] = moment, home["btc"] + quantity, home["usd"] + price * quantity
        home["orders"] += 1
        home["biggest"] = max(home["biggest"], quantity)
        open_by_side[side] = live
    done += open_by_side[1] + open_by_side[-1]
    out = [{"time": round(c["start"], 3), "end": round(c["end"], 3), "price": round(c["usd"] / c["btc"], 1), "quantity": round(c["btc"], 1),
            "usd": round(c["usd"], 2), "orders": c["orders"], "biggest": round(c["biggest"], 1), "side": c["side"]}
           for c in done if c["btc"] >= min_btc and c["orders"] >= min_orders]
    return sorted(out, key=lambda c: c["time"])


def drawings(found: Sequence[Mapping[str, Any]], now: float, lines: int = LINES, hours: float = LINE_HOURS) -> list[dict[str, Any]]:
    """The biggest recent sums as level drawings for ``chart_live.place_drawings`` (group "absorb")."""
    recent = [c for c in found if now - float(c["time"]) <= hours * 3600]
    out = []
    for c in sorted(sorted(recent, key=lambda c: -float(c["quantity"]))[:lines], key=lambda c: c["time"]):
        who = "Käufe" if c["side"] > 0 else "Verkäufe"
        size = f"{c['quantity'] / 1000:.1f}K" if c["quantity"] >= 1000 else f"{c['quantity']:.0f}"
        out.append({"group": "absorb", "tf": "", "name": f"Summe {size} {who}", "label": f"Summe {size} {who}", "price": float(c["price"]),
                    "start": datetime.fromtimestamp(float(c["time"]), timezone.utc).isoformat(),
                    "color": "#35d39a" if c["side"] > 0 else "#ff5c6c",
                    "note": f"{c['orders']} große Market Orders in {max(1, round((c['end'] - c['time']) / 60))} min am selben Preis, zusammen "
                            f"{c['quantity']:.0f} BTC (größte {c['biggest']:.0f}); Anzeige, kein Signal"})
    return out
