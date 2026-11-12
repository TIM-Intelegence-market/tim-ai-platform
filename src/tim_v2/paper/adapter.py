"""Isolated fake execution adapter for V2.8 paper trading.

The adapter simulates orders against bars that the caller hands in. It has no network code, no keys, no
endpoint and no import of any exchange or live-trading module (``isolation.py`` proves that statically, the tests
prove it at runtime). Fills are conservative:

* an order only sees bars that open at or after its submission time (no look-ahead);
* market orders fill at the next bar's open plus slippage;
* stops fill at the trigger or a worse gap open, plus slippage and the extra stop slippage;
* limits fill at the limit (maker, no slippage) only if the bar trades through it; a gap through the limit fills
  at the open as taker;
* if a bar touches both the stop loss and the take profit of a position, the stop loss counts.

One net position per symbol (one-way mode). Money is in quote currency (USDT).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .kill_switch import KillSwitch
from .models import (
    BPS,
    ZERO,
    Bar,
    CostModel,
    Fill,
    LedgerEntry,
    Liquidity,
    Metrics,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
)

# Repository-wide leverage cap (Uzi, 2026-10-20, see src/orderflow_scenario/config.py). Paper uses the same cap.
MAX_LEVERAGE = Decimal("10")


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    initial_equity: Decimal = Decimal("1000")
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    max_leverage: Decimal = MAX_LEVERAGE
    costs: CostModel = field(default_factory=CostModel)

    def __post_init__(self) -> None:
        if self.initial_equity <= ZERO:
            raise ValueError("initial_equity must be positive")
        if not (ZERO < self.max_leverage <= MAX_LEVERAGE):
            raise ValueError(f"max_leverage must be in (0, {MAX_LEVERAGE}]")
        if not self.symbols:
            raise ValueError("at least one symbol is required")


class FakeExecutionAdapter:
    """Paper-only order simulator. ``live_execution`` is always False and cannot be changed."""

    live_execution = False

    def __init__(self, config: AdapterConfig | None = None, kill_switch: KillSwitch | None = None) -> None:
        self.config = config or AdapterConfig()
        self.kill = kill_switch or KillSwitch()
        self.orders: dict[str, Order] = {}  # by client_id, insertion order = submission order
        self.fills: list[Fill] = []
        self.ledger: list[LedgerEntry] = []
        self.positions: dict[str, Position] = {s: Position(s) for s in self.config.symbols}
        self.marks: dict[str, Decimal] = {}
        self.last_bar_at: dict[str, datetime] = {}
        self.metrics = Metrics(peak_equity=self.config.initial_equity)
        self._order_seq = 0
        self._fill_seq = 0
        self._consecutive_rejects = 0
        self._day: str | None = None
        self._day_start_equity = self.config.initial_equity

    def __setattr__(self, name: str, value: object) -> None:
        if name == "live_execution" and value is not False:
            raise AttributeError("paper adapter cannot be switched to live execution")
        object.__setattr__(self, name, value)

    # ------------------------------------------------------------------ account
    @property
    def cash(self) -> Decimal:
        return self.config.initial_equity + sum((e.amount for e in self.ledger), ZERO)

    def equity(self) -> Decimal:
        unrealized = sum(
            (p.unrealized(self.marks[s]) for s, p in self.positions.items() if p.quantity and s in self.marks), ZERO
        )
        return self.cash + unrealized

    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.status is OrderStatus.NEW]

    # ------------------------------------------------------------------ orders
    def submit(self, request: OrderRequest, at: datetime) -> Order:
        existing = self.orders.get(request.client_id)
        if existing is not None:
            if existing.request == request:
                return existing  # idempotent resubmit
            return self._reject(request, at, "duplicate_client_id", store=False)
        self.metrics.orders_submitted += 1
        problems = list(request.problems())
        if request.symbol not in self.positions:
            problems.append("symbol_not_allowed")
        if problems:
            return self._reject(request, at, problems[0])
        position = self.positions[request.symbol]
        if request.reduce_only:
            if not position.quantity or (position.quantity > 0) == (request.side is Side.BUY):
                return self._reject(request, at, "reduce_only_without_position")
        else:
            if self.kill.poll_file(at):
                self._after_kill(at)
                return self._reject(request, at, "kill_switch_engaged")
            ref = request.price if request.price is not None else self.marks.get(request.symbol)
            if ref is None:
                return self._reject(request, at, "no_mark_price")
            projected = abs(position.quantity + request.side.sign * request.quantity) * ref
            if projected > self.config.max_leverage * self.equity():
                return self._reject(request, at, "leverage_limit")
            bracket_problem = self._bracket_problem(request, ref)
            if bracket_problem:
                return self._reject(request, at, bracket_problem)
        self._order_seq += 1
        order = Order(f"po_{self._order_seq:06d}", request, at)
        self.orders[request.client_id] = order
        self._consecutive_rejects = 0
        return order

    def cancel(self, client_id: str, at: datetime, reason: str = "cancelled") -> bool:
        order = self.orders.get(client_id)
        if order is None or order.status is not OrderStatus.NEW:
            return False
        order.status = OrderStatus.CANCELLED
        order.reason = reason
        self.metrics.orders_cancelled += 1
        return True

    def flatten(self, symbol: str, at: datetime) -> Order | None:
        """Close the whole position at the next bar's open (market, reduce-only). Allowed while killed."""
        position = self.positions[symbol]
        if not position.quantity:
            return None
        side = Side.SELL if position.quantity > 0 else Side.BUY
        request = OrderRequest(f"flatten_{symbol}_{at.isoformat()}", symbol, side, abs(position.quantity),
                               reduce_only=True, note="FLATTEN")
        return self.submit(request, at)

    def engage_kill(self, at: datetime, reason: str, source: str = "MANUAL") -> None:
        self.kill.engage(at, reason, source)
        self._after_kill(at)

    # ------------------------------------------------------------------ market data
    def on_bar(self, bar: Bar) -> list[Fill]:
        if bar.symbol not in self.positions:
            raise ValueError(f"symbol not allowed: {bar.symbol}")
        last = self.last_bar_at.get(bar.symbol)
        if last is not None and bar.opened_at <= last:
            raise ValueError(f"bars must be strictly increasing in time for {bar.symbol}")
        self._roll_day(bar.opened_at)
        if self.kill.poll_file(bar.opened_at):
            self._after_kill(bar.opened_at)
        new_fills: list[Fill] = []
        for order in list(self.open_orders()):
            if order.request.symbol != bar.symbol or order.submitted_at > bar.opened_at:
                continue
            fill = self._try_fill(order, bar)
            if fill is not None:
                new_fills.append(fill)
        exit_fill = self._check_brackets(bar)
        if exit_fill is not None:
            new_fills.append(exit_fill)
        self._apply_funding(bar)
        self.marks[bar.symbol] = bar.close
        self.last_bar_at[bar.symbol] = bar.opened_at
        self.metrics.bars_processed += 1
        self._update_risk(bar.opened_at)
        return new_fills

    # ------------------------------------------------------------------ internals
    def _reject(self, request: OrderRequest, at: datetime, reason: str, store: bool = True) -> Order:
        order = Order(f"rej_{len(self.orders) + 1:06d}", request, at, OrderStatus.REJECTED, reason)
        if store:
            self.orders[request.client_id] = order
        self.metrics.orders_rejected += 1
        self.metrics.reject_reasons[reason] = self.metrics.reject_reasons.get(reason, 0) + 1
        self._consecutive_rejects += 1
        if self.kill.check(at, day_start_equity=self._day_start_equity, equity=self.equity(),
                           peak_equity=self.metrics.peak_equity, consecutive_rejects=self._consecutive_rejects):
            self._after_kill(at)
        return order

    @staticmethod
    def _bracket_problem(request: OrderRequest, ref: Decimal) -> str:
        long = request.side is Side.BUY
        if request.stop_loss is not None and (request.stop_loss >= ref if long else request.stop_loss <= ref):
            return "stop_loss_on_wrong_side"
        if request.take_profit is not None and (request.take_profit <= ref if long else request.take_profit >= ref):
            return "take_profit_on_wrong_side"
        return ""

    def _slipped(self, ref: Decimal, side: Side, extra_bps: Decimal = ZERO) -> Decimal:
        bps = self.config.costs.slippage_bps + extra_bps
        return ref * (1 + side.sign * bps / BPS)

    def _try_fill(self, order: Order, bar: Bar) -> Fill | None:
        req = order.request
        position = self.positions[req.symbol]
        quantity = req.quantity
        if req.reduce_only:
            if not position.quantity or (position.quantity > 0) == (req.side is Side.BUY):
                self.cancel(req.client_id, bar.opened_at, "position_already_closed")
                return None
            quantity = min(quantity, abs(position.quantity))
        elif self.kill.engaged:
            self.cancel(req.client_id, bar.opened_at, "kill_switch_engaged")
            return None
        costs = self.config.costs
        buy = req.side is Side.BUY
        if req.order_type is OrderType.MARKET:
            ref, liq = bar.open, Liquidity.TAKER
            price = self._slipped(ref, req.side)
        elif req.order_type is OrderType.LIMIT:
            limit = req.price
            assert limit is not None
            if (bar.open <= limit) if buy else (bar.open >= limit):
                ref, liq = bar.open, Liquidity.TAKER  # gap through the limit: marketable at the open
                price = self._slipped(ref, req.side)
            elif (bar.low <= limit) if buy else (bar.high >= limit):
                ref, liq, price = limit, Liquidity.MAKER, limit
            else:
                return None
        else:  # STOP
            trigger = req.price
            assert trigger is not None
            if not ((bar.high >= trigger) if buy else (bar.low <= trigger)):
                return None
            ref = max(trigger, bar.open) if buy else min(trigger, bar.open)
            liq = Liquidity.TAKER
            price = self._slipped(ref, req.side, costs.stop_extra_slippage_bps)
        fill = self._book_fill(order.order_id, req.client_id, req.symbol, req.side, quantity, ref, price, liq,
                               bar.opened_at, "FLATTEN" if req.note == "FLATTEN" else "ORDER")
        order.status = OrderStatus.FILLED
        order.filled_at = bar.opened_at
        order.fill_id = fill.fill_id
        self.metrics.orders_filled += 1
        if not req.reduce_only and (req.stop_loss is not None or req.take_profit is not None):
            pos = self.positions[req.symbol]
            if pos.quantity:
                pos.stop_loss, pos.take_profit = req.stop_loss, req.take_profit
        return fill

    def _check_brackets(self, bar: Bar) -> Fill | None:
        pos = self.positions[bar.symbol]
        if not pos.quantity or (pos.stop_loss is None and pos.take_profit is None):
            return None
        long = pos.quantity > 0
        exit_side = Side.SELL if long else Side.BUY
        sl, tp = pos.stop_loss, pos.take_profit
        stop_hit = sl is not None and ((bar.low <= sl) if long else (bar.high >= sl))
        target_hit = tp is not None and ((bar.high >= tp) if long else (bar.low <= tp))
        if stop_hit:  # stop wins when both are touched in the same bar
            assert sl is not None
            ref = min(sl, bar.open) if long else max(sl, bar.open)
            price = self._slipped(ref, exit_side, self.config.costs.stop_extra_slippage_bps)
            kind, liq = "STOP_LOSS", Liquidity.TAKER
        elif target_hit:
            assert tp is not None
            if (bar.open >= tp) if long else (bar.open <= tp):
                ref, price, liq = bar.open, self._slipped(bar.open, exit_side), Liquidity.TAKER
            else:
                ref, price, liq = tp, tp, Liquidity.MAKER
            kind = "TAKE_PROFIT"
        else:
            return None
        self.metrics.bracket_exits += 1
        return self._book_fill(f"bracket_{bar.symbol}", f"{kind.lower()}_{bar.opened_at.isoformat()}", bar.symbol,
                               exit_side, abs(pos.quantity), ref, price, liq, bar.opened_at, kind)

    def _book_fill(self, order_id: str, client_id: str, symbol: str, side: Side, quantity: Decimal,
                   ref: Decimal, price: Decimal, liq: Liquidity, at: datetime, kind: str) -> Fill:
        costs = self.config.costs
        fee_bps = costs.maker_fee_bps if liq is Liquidity.MAKER else costs.taker_fee_bps
        fee = quantity * price * fee_bps / BPS
        self._fill_seq += 1
        fill = Fill(f"pf_{self._fill_seq:06d}", order_id, client_id, symbol, side, quantity, ref, price, fee, liq,
                    at, kind)
        self.fills.append(fill)
        self.metrics.fees_paid += fee
        self.metrics.slippage_paid += abs(price - ref) * quantity
        realized = apply_fill_to_position(self.positions[symbol], side, quantity, price)
        if realized:
            self.ledger.append(LedgerEntry(at, "REALIZED", symbol, realized, fill.fill_id))
        self.ledger.append(LedgerEntry(at, "FEE", symbol, -fee, fill.fill_id))
        return fill

    def _apply_funding(self, bar: Bar) -> None:
        pos = self.positions[bar.symbol]
        if bar.funding_rate is None or not pos.quantity:
            return
        amount = -pos.quantity * bar.close * bar.funding_rate
        self.ledger.append(LedgerEntry(bar.opened_at, "FUNDING", bar.symbol, amount, f"funding_{bar.opened_at.isoformat()}"))
        self.metrics.funding_paid -= amount

    def _roll_day(self, at: datetime) -> None:
        day = at.date().isoformat()
        if day != self._day:
            self._day = day
            self._day_start_equity = self.equity()

    def _update_risk(self, at: datetime) -> None:
        equity = self.equity()
        if equity > self.metrics.peak_equity:
            self.metrics.peak_equity = equity
        if self.metrics.peak_equity > 0:
            dd = (self.metrics.peak_equity - equity) / self.metrics.peak_equity
            if dd > self.metrics.max_drawdown_fraction:
                self.metrics.max_drawdown_fraction = dd
        if self.kill.check(at, day_start_equity=self._day_start_equity, equity=equity,
                           peak_equity=self.metrics.peak_equity, consecutive_rejects=self._consecutive_rejects):
            self._after_kill(at)

    def _after_kill(self, at: datetime) -> None:
        self.metrics.kill_events = sum(1 for e in self.kill.events if e.source != "RELEASE")
        for order in self.open_orders():
            if not order.request.reduce_only:
                self.cancel(order.request.client_id, at, "kill_switch_engaged")


def apply_fill_to_position(pos: Position, side: Side, quantity: Decimal, price: Decimal) -> Decimal:
    """Net one-way position update. Returns realized PnL of the closed part."""
    signed = side.sign * quantity
    q0 = pos.quantity
    if q0 == ZERO or (q0 > 0) == (signed > 0):
        new_qty = q0 + signed
        pos.entry_price = (abs(q0) * pos.entry_price + quantity * price) / abs(new_qty)
        pos.quantity = new_qty
        return ZERO
    closing = min(quantity, abs(q0))
    realized = (price - pos.entry_price) * closing * (1 if q0 > 0 else -1)
    new_qty = q0 + signed
    pos.quantity = new_qty
    if new_qty == ZERO:
        pos.entry_price = ZERO
        pos.stop_loss = pos.take_profit = None
    elif (new_qty > 0) != (q0 > 0):  # flipped: remainder opens at this price, old brackets do not apply
        pos.entry_price = price
        pos.stop_loss = pos.take_profit = None
    return realized
