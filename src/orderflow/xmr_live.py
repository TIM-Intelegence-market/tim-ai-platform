"""Live-Orderflow-Lage for Monero from the XMR perp trades (Bauplan XMR, Paket 3; Barti 11.11./24.11.2026).

BTC's Lage (``live_state``) reads spot aggTrades from PostgreSQL. Binance has no XMR spot market and TIM keeps no
XMR trades in the database (Barti: "Weg 2", files only), so the XMR Lage reads the raw batches the perp collector
already fetches (``perp_flow.PerpFlow.listeners``): no extra call to Binance, no database.

The same ``LiveOrderflowTracker`` and the same thresholds describe the wave, the windows, the day and the levels
(prior-day VAH/VAL/POC and the running POC from the XMR perp store). The "perp" block is the same source here,
because XMR has only the perp. Own file ``data/orderflow/orderflow_lage_xmr.json``; the BTC Lage and its file are
not touched. Describes only: nothing here plans, filters or trades.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.models.market_data import Trade
from src.orderflow import live_state

SYMBOL = "XMRUSDT"
DEFAULT_PATH = Path("data/orderflow/orderflow_lage_xmr.json")


def trades_from_rows(symbol: str, rows: Sequence[Mapping[str, Any]]) -> list[Trade]:
    """Binance aggTrade rows (``a`` id, ``p`` price, ``q`` quantity, ``T`` ms, ``m`` buyer is maker) as Trades."""
    out = []
    for row in rows:
        try:
            price, quantity = float(row["p"]), float(row["q"])
            if price <= 0 or quantity <= 0:
                continue
            out.append(Trade(symbol=symbol, price=price, quantity=quantity,
                             event_time=datetime.fromtimestamp(int(row["T"]) / 1000, tz=timezone.utc),
                             trade_id=int(row["a"]), buyer_is_maker=bool(row["m"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


class XmrOrderflowLive:
    """Tracker fed from the perp collector's thread, read from the runtime loop; one lock between them."""

    def __init__(self, tick: float | None = None) -> None:
        if tick is None:
            from src.dashboard.perp_flow import SPECS

            tick = SPECS[SYMBOL].tick
        self.tracker = live_state.LiveOrderflowTracker(SYMBOL, tick)
        self._lock = threading.Lock()

    def on_rows(self, symbol: str, rows: Sequence[Mapping[str, Any]]) -> None:
        """PerpFlow listener: only XMR rows count; ids at or below the last one are skipped (replay-safe)."""
        if symbol != SYMBOL or not rows:
            return
        trades = trades_from_rows(symbol, rows)
        with self._lock:
            self.tracker.ingest(trades)

    def snapshot(self, now: datetime, store: Mapping[str, Any] | None) -> dict[str, Any]:
        """The Lage at ``now`` with levels and the running day from the XMR perp store (footprint shape)."""
        from src.dashboard.footprint_data import volume_profiles

        profiles = volume_profiles(store, now) if store and store.get("days") else []
        levels = live_state.levels_from_profiles(profiles)
        running = next((p for p in profiles if p.get("running")), None)
        with self._lock:
            state = self.tracker.snapshot(now, levels, store, running)
        state["source"] = "Binance USD-M Perp aggTrades (XMRUSDT), TIM-Sammler"
        return state


def for_symbol(lage: Mapping[str, Any] | None, symbol: str = SYMBOL) -> dict[str, Any] | None:
    """The Lage only when it describes ``symbol``: an XMR shadow must never read the BTC Lage and vice versa."""
    if not lage or lage.get("symbol") != symbol:
        return None
    return dict(lage)
