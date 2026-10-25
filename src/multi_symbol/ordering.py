"""Ordering, de-duplication and recovery cursors per symbol.

Binance aggregate-trade ids are independent sequences per symbol (measured on
2026-10-25: BTC ~4.1e9, ETH ~2.1e9, SOL ~6.8e8). They are therefore only
comparable within one symbol. The current strict-order outbox claim orders by
``aggregate_trade_id`` per worker without a symbol filter; with several symbols
that order would serve one symbol's whole backlog before the next symbol, and a
quarantined head of one symbol would block all others. ``per_symbol_heads``
models the intended claim: one strict prefix per symbol.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

ACCEPT = "ACCEPT"
DUPLICATE = "DUPLICATE"
GAP = "GAP"
STALE = "STALE"


@dataclass(frozen=True, slots=True)
class OrderDecision:
    symbol: str
    status: str
    trade_id: int
    missing_from: int | None = None
    missing_to: int | None = None


class SymbolCursorBook:
    """Last processed aggregate id per symbol; never shared between symbols."""

    def __init__(self, cursors: Mapping[str, int | None] | None = None) -> None:
        self._cursors: dict[str, int | None] = dict(cursors or {})

    def cursor(self, symbol: str) -> int | None:
        return self._cursors.get(symbol)

    def classify(self, symbol: str, trade_id: int) -> OrderDecision:
        """Decide without mutating: duplicate, gap (needs recovery first) or accept."""
        if isinstance(trade_id, bool) or not isinstance(trade_id, int) or trade_id < 0:
            raise ValueError("trade_id must be a non-negative integer")
        last = self._cursors.get(symbol)
        if last is None or trade_id == last + 1:
            return OrderDecision(symbol, ACCEPT, trade_id)
        if trade_id <= last:
            return OrderDecision(symbol, DUPLICATE, trade_id)
        return OrderDecision(symbol, GAP, trade_id, last + 1, trade_id - 1)

    def advance(self, symbol: str, trade_id: int) -> None:
        decision = self.classify(symbol, trade_id)
        if decision.status != ACCEPT:
            raise ValueError(f"cursor for {symbol} cannot advance: {decision.status}")
        self._cursors[symbol] = trade_id

    def recovered_through(self, symbol: str, trade_id: int) -> None:
        """Catch-up for ``symbol`` persisted everything up to ``trade_id``."""
        last = self._cursors.get(symbol)
        if last is not None and trade_id < last:
            raise ValueError("recovery cannot move a cursor backwards")
        self._cursors[symbol] = trade_id

    def snapshot(self) -> dict[str, int | None]:
        return dict(self._cursors)


class _OutboxLike(Protocol):
    symbol: str
    aggregate_trade_id: int
    status: str


ACTIVE = frozenset({"PENDING", "RETRY", "PROCESSING", "QUARANTINED"})
CLAIMABLE = frozenset({"PENDING", "RETRY"})


def per_symbol_heads(items: Iterable[_OutboxLike], limit: int) -> dict[str, list[_OutboxLike]]:
    """Strict claimable prefix per symbol (pure model of the proposed claim).

    Within a symbol items run in aggregate-id order and the prefix stops at the
    first active item that is not claimable (processing, quarantined). Other
    symbols are unaffected by that blocker.
    """
    if not 1 <= limit <= 1_000:
        raise ValueError("limit must be between 1 and 1000")
    by_symbol: dict[str, list[_OutboxLike]] = {}
    for item in items:
        if item.status in ACTIVE:
            by_symbol.setdefault(item.symbol, []).append(item)
    heads: dict[str, list[_OutboxLike]] = {}
    for symbol, active in by_symbol.items():
        active.sort(key=lambda item: item.aggregate_trade_id)
        prefix: list[_OutboxLike] = []
        for item in active:
            if item.status not in CLAIMABLE or len(prefix) >= limit:
                break
            prefix.append(item)
        heads[symbol] = prefix
    return heads


def global_order_heads(items: Iterable[_OutboxLike], limit: int) -> list[_OutboxLike]:
    """Model of today's claim (one strict order per worker, no symbol filter)."""
    prefix: list[_OutboxLike] = []
    for item in sorted((i for i in items if i.status in ACTIVE), key=lambda i: i.aggregate_trade_id):
        if item.status not in CLAIMABLE or len(prefix) >= limit:
            break
        prefix.append(item)
    return prefix
