"""Orderflow-Lage for the Control Center (tile) and the chart page (section), read-only.

Both read ``DashboardState.orderflow_live`` (src/orderflow/live_state.py). Nothing here computes or trades.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from src.dashboard.cockpit.tiles import Tile, make_tile
from src.dashboard.helpers import _safe

MAX_AGE_SECONDS = 60
HREF = "/chart?symbol=BTCUSDT&tf=15m"


def headline(state: Mapping[str, Any] | None) -> str:
    if not state or state.get("stale") or state.get("price") is None:
        return "keine frischen Trades"
    wave = state.get("wave") or {}
    if wave.get("direction") == "keine":
        return "keine klare Welle"
    word = "Käuferwelle" if wave.get("direction") == "auf" else "Verkäuferwelle"
    tail = ", Exhaustion" if wave.get("exhaustion") else ""
    return f"{word} {wave.get('strength', 0)}/3, {wave.get('phase', '')}{tail}"


def tile(state: Mapping[str, Any] | None, now: datetime | None = None) -> Tile:
    now = now or datetime.now(timezone.utc)
    if not state:
        return make_tile("orderflow", "Orderflow", "—", state="unknown", reason="Orderflow-Lage noch nicht geschrieben",
                         source="src/orderflow/live_state.py", href=HREF, now=now)
    status = "WARN" if state.get("stale") else "PASS"
    return make_tile("orderflow", "Orderflow", headline(state), status, source="Spot-aggTrades live, Perp-Store",
                     as_of=state.get("as_of"), max_age_seconds=MAX_AGE_SECONDS, detail=str(state.get("text") or ""),
                     href=HREF, now=now, extra={"kind": "info", "wave": state.get("wave"), "tempo": state.get("tempo")})


def section(state: Mapping[str, Any] | None) -> str:
    """Chart page: one short section with the German text and the near levels."""
    if not state:
        return "<section class='cc-section tc-orderflow'><p class='cc-note'>Orderflow-Lage: noch keine Daten.</p></section>"
    rows = "".join(
        f"<tr><td>{_safe(level['name'])}</td><td>{level['price']:.0f}</td><td>{level['distance_pct']:+.2f} %</td>"
        f"<td>{level['bid']:.2f} × {level['ask']:.2f}</td><td>{_safe(level.get('imbalance') or '')}"
        f"{' Absorption' if level.get('absorption') else ''}</td></tr>"
        for level in (state.get("levels") or [])[:5])
    table = (f"<table class='cc-table'><thead><tr><th>Level</th><th>Preis</th><th>Abstand</th><th>Bid × Ask 15m</th><th>Hinweis</th></tr></thead>"
             f"<tbody>{rows}</tbody></table>") if rows else ""
    return (f"<section class='cc-section tc-orderflow'><h2>Orderflow-Lage</h2><p>{_safe(state.get('text') or '')}</p>{table}"
            f"<p class='cc-note'>Live aus den Spot-Trades, alle 10 s; Schwellen sind Startwerte (OF2-Kalibrierung offen). Nur Beschreibung, kein Plan.</p></section>")
