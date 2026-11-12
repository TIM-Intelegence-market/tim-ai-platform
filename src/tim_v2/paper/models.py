"""Data types for the V2.8 paper trading adapter.

Everything here is plain data. There is no account, key, endpoint or URL field on purpose:
the paper adapter has nothing it could send to an exchange.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

ZERO = Decimal("0")
BPS = Decimal("10000")


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    NEW = "NEW"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Liquidity(str, Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"


def d(value: str | int | float | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True, slots=True)
class CostModel:
    """Paper costs. Defaults follow the Bitunix assumptions used in S24/OF2 (taker 6 bp, slippage 3 bp,
    5 bp extra when a stop fills). Fees are an assumption until confirmed against an account statement."""

    taker_fee_bps: Decimal = Decimal("6")
    maker_fee_bps: Decimal = Decimal("2")
    slippage_bps: Decimal = Decimal("3")
    stop_extra_slippage_bps: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        for name in ("taker_fee_bps", "maker_fee_bps", "slippage_bps", "stop_extra_slippage_bps"):
            if getattr(self, name) < ZERO:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    opened_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    funding_rate: Decimal | None = None  # applied once at this bar if set (longs pay a positive rate)

    def __post_init__(self) -> None:
        if self.opened_at.tzinfo is None:
            raise ValueError("bar time must be timezone-aware")
        if min(self.open, self.high, self.low, self.close) <= ZERO:
            raise ValueError("bar prices must be positive")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close):
            raise ValueError("inconsistent OHLC")


@dataclass(frozen=True, slots=True)
class OrderRequest:
    client_id: str
    symbol: str
    side: Side
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    price: Decimal | None = None  # limit price or stop trigger
    reduce_only: bool = False
    stop_loss: Decimal | None = None  # bracket for the resulting position
    take_profit: Decimal | None = None
    note: str = ""

    def problems(self) -> tuple[str, ...]:
        out: list[str] = []
        if not self.client_id.strip():
            out.append("client_id_required")
        if self.quantity <= ZERO:
            out.append("quantity_must_be_positive")
        if self.order_type is OrderType.MARKET and self.price is not None:
            out.append("market_order_has_no_price")
        if self.order_type is not OrderType.MARKET and (self.price is None or self.price <= ZERO):
            out.append("price_required")
        for name in ("stop_loss", "take_profit"):
            value = getattr(self, name)
            if value is not None and value <= ZERO:
                out.append(f"{name}_must_be_positive")
        return tuple(out)


@dataclass(slots=True)
class Order:
    order_id: str
    request: OrderRequest
    submitted_at: datetime
    status: OrderStatus = OrderStatus.NEW
    reason: str = ""
    filled_at: datetime | None = None
    fill_id: str | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    order_id: str
    client_id: str
    symbol: str
    side: Side
    quantity: Decimal
    reference_price: Decimal  # price before slippage (open, limit or trigger)
    price: Decimal  # price after slippage
    fee: Decimal
    liquidity: Liquidity
    filled_at: datetime
    kind: str = "ORDER"  # ORDER, STOP_LOSS, TAKE_PROFIT, FLATTEN

    def to_dict(self) -> dict[str, str]:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "client_id": self.client_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "reference_price": str(self.reference_price),
            "price": str(self.price),
            "fee": str(self.fee),
            "liquidity": self.liquidity.value,
            "filled_at": self.filled_at.isoformat(),
            "kind": self.kind,
            "live_execution": "false",
        }


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: Decimal = ZERO  # signed: > 0 long, < 0 short
    entry_price: Decimal = ZERO
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None

    def unrealized(self, mark: Decimal) -> Decimal:
        return (mark - self.entry_price) * self.quantity if self.quantity else ZERO


@dataclass(slots=True)
class LedgerEntry:
    """Append-only cash movement. Reconciliation rebuilds the account from these and the fills."""

    at: datetime
    kind: str  # REALIZED, FEE, FUNDING
    symbol: str
    amount: Decimal
    ref: str


@dataclass(slots=True)
class Metrics:
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    orders_cancelled: int = 0
    bracket_exits: int = 0
    bars_processed: int = 0
    fees_paid: Decimal = ZERO
    slippage_paid: Decimal = ZERO
    funding_paid: Decimal = ZERO
    peak_equity: Decimal = ZERO
    max_drawdown_fraction: Decimal = ZERO
    kill_events: int = 0
    reconciliations: int = 0
    reconciliation_mismatches: int = 0
    reject_reasons: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for name in self.__slots__:  # type: ignore[attr-defined]
            value = getattr(self, name)
            out[name] = str(value) if isinstance(value, Decimal) else value
        return out
