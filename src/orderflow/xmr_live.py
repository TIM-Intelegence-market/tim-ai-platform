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
from collections import deque
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.models.market_data import Trade
from src.orderflow import live_state

SYMBOL = "XMRUSDT"
DEFAULT_PATH = Path("data/orderflow/orderflow_lage_xmr.json")
# Point in time (Codex review PR #369): a plan or fill gets only a Lage taken at or before its moment and at most
# LOOKBACK earlier (the runtime takes one every 10 s). HISTORY covers how late the journal step sees a plan.
LOOKBACK = timedelta(seconds=60)
HISTORY = timedelta(hours=2)


def trades_from_rows(symbol: str, rows: Sequence[Mapping[str, Any]], rejected: dict[str, int] | None = None) -> list[Trade]:
    """Binance aggTrade rows (``a`` id, ``p`` price, ``q`` quantity, ``T`` ms, ``m`` buyer is maker) as Trades.

    The aggressor flag ``m`` must be a real bool: "false", None, 0 or a missing flag never become a side (Codex
    review PR #369); such rows are dropped and counted in ``rejected["flag"]``, other bad rows in ``rejected["row"]``.
    """
    out = []
    for row in rows:
        if not isinstance(row.get("m") if isinstance(row, Mapping) else None, bool):
            if rejected is not None:
                rejected["flag"] = rejected.get("flag", 0) + 1
            continue
        try:
            price, quantity = float(row["p"]), float(row["q"])
            if price <= 0 or quantity <= 0:
                raise ValueError("price and quantity must be positive")
            out.append(Trade(symbol=symbol, price=price, quantity=quantity,
                             event_time=datetime.fromtimestamp(int(row["T"]) / 1000, tz=timezone.utc),
                             trade_id=int(row["a"]), buyer_is_maker=row["m"]))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            if rejected is not None:
                rejected["row"] = rejected.get("row", 0) + 1
    return out


class XmrOrderflowLive:
    """Tracker fed from the perp collector's thread, read from the runtime loop; one lock between them."""

    def __init__(self, tick: float | None = None) -> None:
        if tick is None:
            from src.dashboard.perp_flow import SPECS

            tick = SPECS[SYMBOL].tick
        self.tracker = live_state.LiveOrderflowTracker(SYMBOL, tick)
        self._lock = threading.Lock()
        self.rejected: dict[str, int] = {}
        self._history: deque[tuple[datetime, dict[str, Any]]] = deque()

    def on_rows(self, symbol: str, rows: Sequence[Mapping[str, Any]]) -> None:
        """PerpFlow listener: only XMR rows count; ids at or below the last one are skipped (replay-safe)."""
        if symbol != SYMBOL or not rows:
            return
        with self._lock:
            self.tracker.ingest(trades_from_rows(symbol, rows, self.rejected))

    def snapshot(self, now: datetime, store: Mapping[str, Any] | None) -> dict[str, Any]:
        """The Lage at ``now`` with levels and the running day from the XMR perp store (footprint shape)."""
        from src.dashboard.footprint_data import volume_profiles

        profiles = volume_profiles(store, now) if store and store.get("days") else []
        levels = live_state.levels_from_profiles(profiles)
        running = next((p for p in profiles if p.get("running")), None)
        with self._lock:
            state = self.tracker.snapshot(now, levels, store, running)
            state["source"] = "Binance USD-M Perp aggTrades (XMRUSDT), TIM-Sammler"
            state["rejected_rows"] = dict(self.rejected)
            self._remember(now, state)
        return state

    def _remember(self, now: datetime, state: Mapping[str, Any]) -> None:
        """Keep the snapshot for ``lage_at``; only fresh ones, in time order, at most ``HISTORY`` back (lock held)."""
        if state.get("stale") or state.get("price") is None:
            return
        if self._history and now <= self._history[-1][0]:
            return  # a clock step back never reorders the history
        self._history.append((now, dict(state)))
        while self._history and now - self._history[0][0] > HISTORY:
            self._history.popleft()

    def lage_at(self, moment: datetime) -> dict[str, Any] | None:
        """The latest Lage taken at or before ``moment`` and at most ``LOOKBACK`` earlier; None if there is none.

        Never a Lage from after ``moment`` (no look-ahead), and none after a restart for plans from before it.
        """
        with self._lock:
            known = [state for taken, state in self._history if taken <= moment and moment - taken <= LOOKBACK]
        return dict(known[-1]) if known else None


def for_symbol(lage: Mapping[str, Any] | None, symbol: str = SYMBOL) -> dict[str, Any] | None:
    """The Lage only when it describes ``symbol``: an XMR shadow must never read the BTC Lage and vice versa."""
    if not lage or lage.get("symbol") != symbol:
        return None
    return dict(lage)
