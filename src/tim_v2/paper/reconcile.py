"""Reconciliation for the V2.8 paper adapter.

Rebuilds positions and cash only from the fill list and the funding entries, with its own arithmetic, and
compares the result with the adapter's live state and order book. Any difference engages the kill switch
(source RECONCILIATION), because a paper account that does not add up cannot be used as evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .adapter import FakeExecutionAdapter
from .models import ZERO, OrderStatus

TOLERANCE = Decimal("1e-9")


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    at: datetime
    ok: bool
    differences: tuple[str, ...]
    rebuilt_cash: Decimal
    adapter_cash: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "at": self.at.isoformat(),
            "ok": self.ok,
            "differences": list(self.differences),
            "rebuilt_cash": str(self.rebuilt_cash),
            "adapter_cash": str(self.adapter_cash),
        }


def _rebuild(adapter: FakeExecutionAdapter) -> tuple[dict[str, tuple[Decimal, Decimal]], Decimal]:
    """Independent replay: per symbol (signed quantity, cost basis of the open part)."""
    book: dict[str, tuple[Decimal, Decimal]] = {}
    cash = adapter.config.initial_equity
    for fill in adapter.fills:
        qty, basis = book.get(fill.symbol, (ZERO, ZERO))
        signed = fill.quantity if fill.side.value == "BUY" else -fill.quantity
        cash -= fill.fee
        if qty == ZERO or (qty > 0) == (signed > 0):
            book[fill.symbol] = (qty + signed, basis + signed * fill.price)
            continue
        closing = min(abs(signed), abs(qty))
        avg = basis / qty
        direction = Decimal(1) if qty > 0 else Decimal(-1)
        cash += (fill.price - avg) * closing * direction
        rest = qty + signed
        if rest == ZERO:
            book[fill.symbol] = (ZERO, ZERO)
        elif (rest > 0) == (qty > 0):
            book[fill.symbol] = (rest, avg * rest)
        else:
            book[fill.symbol] = (rest, fill.price * rest)
    cash += sum((e.amount for e in adapter.ledger if e.kind == "FUNDING"), ZERO)
    return book, cash


def reconcile(adapter: FakeExecutionAdapter, at: datetime, *, engage_kill: bool = True) -> ReconciliationReport:
    diffs: list[str] = []
    book, cash = _rebuild(adapter)
    for symbol, pos in adapter.positions.items():
        qty, basis = book.get(symbol, (ZERO, ZERO))
        if abs(qty - pos.quantity) > TOLERANCE:
            diffs.append(f"{symbol}: quantity {pos.quantity} vs rebuilt {qty}")
        elif qty != ZERO and abs(basis / qty - pos.entry_price) > TOLERANCE * max(Decimal(1), pos.entry_price):
            diffs.append(f"{symbol}: entry {pos.entry_price} vs rebuilt {basis / qty}")
    if abs(cash - adapter.cash) > TOLERANCE * max(Decimal(1), abs(cash)):
        diffs.append(f"cash {adapter.cash} vs rebuilt {cash}")
    fee_ledger = -sum((e.amount for e in adapter.ledger if e.kind == "FEE"), ZERO)
    fee_fills = sum((f.fee for f in adapter.fills), ZERO)
    if abs(fee_ledger - fee_fills) > TOLERANCE:
        diffs.append(f"fees ledger {fee_ledger} vs fills {fee_fills}")
    fills_by_order: dict[str, int] = {}
    for f in adapter.fills:
        if not f.order_id.startswith("bracket_"):
            fills_by_order[f.order_id] = fills_by_order.get(f.order_id, 0) + 1
    filled = {o.order_id for o in adapter.orders.values() if o.status is OrderStatus.FILLED}
    for order_id in sorted(filled | set(fills_by_order)):
        n = fills_by_order.get(order_id, 0)
        if order_id not in filled:
            diffs.append(f"fill without filled order: {order_id}")
        elif n != 1:
            diffs.append(f"order {order_id} has {n} fills")
    report = ReconciliationReport(at, not diffs, tuple(diffs), cash, adapter.cash)
    adapter.metrics.reconciliations += 1
    if diffs:
        adapter.metrics.reconciliation_mismatches += 1
        if engage_kill:
            adapter.engage_kill(at, f"reconciliation mismatch: {diffs[0]}", "RECONCILIATION")
    return report
