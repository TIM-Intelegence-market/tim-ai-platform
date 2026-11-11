"""Bitunix USDT-M contract rules as read from the public API (no key).

Snapshot taken 11.11.2026 from ``GET /api/v1/futures/market/trading_pairs`` and
``GET /api/v1/futures/position/get_position_tiers`` (https://www.bitunix.com/api-docs/futures/). Fees are NOT in the
public API; the VIP0 values below are Uzi's figures from 10.11.2026 and stay marked as unverified until a fee
page or a filled trade confirms them.
"""
from __future__ import annotations

from dataclasses import dataclass

SNAPSHOT_DATE = "2026-11-11"


@dataclass(frozen=True)
class Tier:
    level: int
    start_value: float  # notional USDT, inclusive
    end_value: float  # notional USDT, exclusive
    max_leverage: int
    mmr: float  # maintenance margin rate


@dataclass(frozen=True)
class Contract:
    symbol: str
    min_qty: float
    qty_precision: int
    price_precision: int
    max_leverage: int
    max_market_qty: float
    max_limit_qty: float
    tiers: tuple[Tier, ...]

    def tier_for(self, notional: float) -> Tier:
        if notional < 0:
            raise ValueError("notional must be >= 0")
        for tier in self.tiers:
            if tier.start_value <= notional < tier.end_value:
                return tier
        raise ValueError(f"notional {notional} above the last tier of {self.symbol}")

    def leverage_allowed(self, leverage: float, notional: float) -> bool:
        return 1 <= leverage <= min(self.max_leverage, self.tier_for(notional).max_leverage)


# Uzi 10.11.2026, VIP0; unverified against an official fee page.
FEE_TAKER = 0.0006
FEE_MAKER = 0.0002
FEES_VERIFIED = False

BTCUSDT = Contract(
    symbol="BTCUSDT",
    min_qty=0.0001,
    qty_precision=4,
    price_precision=1,
    max_leverage=200,
    max_market_qty=120.0,
    max_limit_qty=1200.0,
    tiers=(
        Tier(1, 0, 100_000, 200, 0.003),
        Tier(2, 100_000, 400_000, 150, 0.004),
        Tier(3, 400_000, 1_000_000, 100, 0.005),
        Tier(4, 1_000_000, 4_000_000, 75, 0.0065),
        Tier(5, 4_000_000, 10_000_000, 50, 0.01),
        Tier(6, 10_000_000, 20_000_000, 25, 0.02),
        Tier(7, 20_000_000, 30_000_000, 20, 0.025),
        Tier(8, 30_000_000, 50_000_000, 10, 0.05),
        Tier(9, 50_000_000, 80_000_000, 5, 0.1),
        Tier(10, 80_000_000, 120_000_000, 2, 0.25),
        Tier(11, 120_000_000, 200_000_000, 1, 0.5),
    ),
)
