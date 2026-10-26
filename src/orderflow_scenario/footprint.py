"""Footprint: aggressive bid/ask volume per price level and candle.

A footprint bar lists, for one candle, how much was traded into the bid
(aggressive sells, left column) and into the ask (aggressive buys, right
column) at every price level. From it the engine reads what plain candles and a
single window delta cannot show (docs/knowledge/ORDERFLOW_REGELN.md, F1-F6):

* F1 imbalances: one side exceeds the other diagonally by a multiple (Bootcamp: 4x),
* F2 stacked imbalances: three or more consecutive same-side imbalances,
* F3 finished auction: a candle edge with zero on one side; unfinished: both sides > 0,
* F4 absorption cluster: one level carries several times the mean level volume at the
  edge the aggressor is pushing into,
* F5 thin extreme: the edge in the direction of the move carries only a fraction of
  the mean level volume (the "N x 0" print),
* F6 delta per bar and POC location.

Two builders exist: from trades (Binance aggTrades, ``buyer_is_maker``) and from
OpenMarket ``VOLUME_PROFILE_AGG`` rows per interval. Both are deterministic and
never fill missing sides with zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from src.models.market_data import Candle, Trade

from .domain import OrderflowStatement, OrderflowStatementKind, ZERO

__all__ = [
    "FootprintLevel",
    "FootprintBar",
    "FootprintSeries",
    "FootprintReading",
    "footprint_from_trades",
    "footprint_from_levels",
    "analyze_footprint",
]

IMBALANCE_RATIO = Decimal("4")  # Bootcamp: 400 %-618 %, the lower bound
STACK_MIN = 3  # ATAS / Bootcamp: three or more consecutive imbalances
CLUSTER_RATIO = Decimal("3")  # absorption: one level >= 3x the mean level volume
THIN_EXTREME_RATIO = Decimal("0.25")  # exhaustion: edge level <= 25 % of the mean level volume
EDGE_FRACTION = Decimal("0.2")  # a level counts as "at the edge" within the outer 20 % of the bar range
MAX_LEVELS_PER_BAR = 5000


@dataclass(frozen=True, slots=True)
class FootprintLevel:
    price: Decimal
    bid_volume: Decimal  # aggressive sells (hit the bid)
    ask_volume: Decimal  # aggressive buys (lift the ask)

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("footprint price must be > 0")
        if self.bid_volume < 0 or self.ask_volume < 0:
            raise ValueError("footprint volumes cannot be negative")

    @property
    def total(self) -> Decimal:
        return self.bid_volume + self.ask_volume

    @property
    def delta(self) -> Decimal:
        return self.ask_volume - self.bid_volume


@dataclass(frozen=True, slots=True)
class FootprintBar:
    levels: tuple[FootprintLevel, ...]  # ascending by price
    open_time: datetime | None = None
    close: Decimal | None = None
    open: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.levels:
            raise ValueError("footprint bar needs at least one level")
        if len(self.levels) > MAX_LEVELS_PER_BAR:
            raise ValueError("footprint bar has too many levels")
        prices = [level.price for level in self.levels]
        if prices != sorted(prices) or len(set(prices)) != len(prices):
            raise ValueError("footprint levels must be ascending and unique")

    @property
    def high(self) -> FootprintLevel:
        return self.levels[-1]

    @property
    def low(self) -> FootprintLevel:
        return self.levels[0]

    @property
    def total(self) -> Decimal:
        return sum((level.total for level in self.levels), ZERO)

    @property
    def delta(self) -> Decimal:
        return sum((level.delta for level in self.levels), ZERO)

    @property
    def poc(self) -> FootprintLevel:
        # Largest total; ties go to the lower price (same rule as summarize_profile).
        return min(self.levels, key=lambda level: (-level.total, level.price))

    @property
    def direction(self) -> str:
        """UP | DOWN | FLAT from open/close when known, else from the delta sign."""
        if self.open is not None and self.close is not None and self.open != self.close:
            return "UP" if self.close > self.open else "DOWN"
        if self.delta > ZERO:
            return "UP"
        if self.delta < ZERO:
            return "DOWN"
        return "FLAT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_time": self.open_time.isoformat() if self.open_time else None,
            "levels": [[str(level.price), str(level.bid_volume), str(level.ask_volume)] for level in self.levels],
            "delta": str(self.delta),
            "total": str(self.total),
        }


@dataclass(frozen=True, slots=True)
class FootprintSeries:
    bars: tuple[FootprintBar, ...]  # oldest first
    source: str = "unknown"
    tick_size: Decimal | None = None
    skipped_trades: int = 0  # trades without an aggressor side or outside every candle

    def __post_init__(self) -> None:
        if not self.bars:
            raise ValueError("footprint series needs at least one bar")

    @property
    def delta_series(self) -> tuple[Decimal, ...]:
        return tuple(bar.delta for bar in self.bars)

    @property
    def last(self) -> FootprintBar:
        return self.bars[-1]


@dataclass(frozen=True, slots=True)
class FootprintReading:
    """Deterministic reading of the last bar; statements are typed like the engine's."""

    statements: tuple[OrderflowStatement, ...]
    summary: dict[str, Any] = field(default_factory=dict)
    buy_imbalances: int = 0
    sell_imbalances: int = 0
    stacked_buy: int = 0  # longest run of consecutive buy imbalances
    stacked_sell: int = 0
    finished_high: bool = False
    finished_low: bool = False
    unfinished_high: bool = False
    unfinished_low: bool = False
    absorption_cluster: str | None = None  # PASSIVE_SELLERS | PASSIVE_BUYERS
    thin_extreme: str | None = None  # BUYERS_THIN_AT_HIGH | SELLERS_THIN_AT_LOW
    poc_location: str | None = None  # UPPER | MIDDLE | LOWER


def _bucket(price: Decimal, tick: Decimal) -> Decimal:
    return (price // tick) * tick


def footprint_from_trades(
    trades: Sequence[Trade],
    candles: Sequence[Candle],
    tick_size: Decimal,
    *,
    source: str = "trades",
) -> FootprintSeries | None:
    """Aggregate aggTrades into per-candle footprint bars.

    ``buyer_is_maker`` True means the seller was the aggressor (volume into the bid).
    Trades without that flag, or outside every candle window, are skipped and counted,
    never guessed. Candles without a single trade produce no bar. Returns ``None``
    when no bar can be built.
    """
    if tick_size <= 0:
        raise ValueError("tick_size must be > 0")
    if not candles:
        return None
    windows = sorted(candles, key=lambda c: c.open_time)
    buckets: list[dict[Decimal, list[Decimal]]] = [dict() for _ in windows]
    skipped = 0
    for trade in trades:
        if trade.buyer_is_maker is None:
            skipped += 1
            continue
        index = _window_index(windows, trade.event_time)
        if index is None:
            skipped += 1
            continue
        level = buckets[index].setdefault(_bucket(Decimal(str(trade.price)), tick_size), [ZERO, ZERO])
        quantity = Decimal(str(trade.quantity))
        if trade.buyer_is_maker:
            level[0] += quantity  # seller aggressive: volume into the bid
        else:
            level[1] += quantity
    bars: list[FootprintBar] = []
    for candle, levels in zip(windows, buckets):
        if not levels:
            continue
        bars.append(
            FootprintBar(
                levels=tuple(FootprintLevel(price, volumes[0], volumes[1]) for price, volumes in sorted(levels.items())),
                open_time=candle.open_time,
                open=Decimal(str(candle.open)),
                close=Decimal(str(candle.close)),
            )
        )
    if not bars:
        return None
    return FootprintSeries(bars=tuple(bars), source=source, tick_size=tick_size, skipped_trades=skipped)


def _window_index(windows: Sequence[Candle], moment: datetime) -> int | None:
    for index, candle in enumerate(windows):
        if candle.open_time <= moment < candle.close_time:
            return index
    return None


def footprint_from_levels(
    bars: Iterable[tuple[datetime | None, Iterable[tuple[Decimal, Decimal, Decimal]]]],
    *,
    source: str,
    candles: Sequence[Candle] | None = None,
    opens_closes: Mapping[datetime, tuple[Decimal, Decimal]] | None = None,
    tick_size: Decimal | None = None,
) -> FootprintSeries | None:
    """Build a series from (open_time, rows) where each row is (price, bid_volume, ask_volume).

    A bar whose ``open_time`` matches a candle (``candles``) or an entry of
    ``opens_closes`` takes that open/close for its direction.
    """
    by_open: dict[datetime, tuple[Decimal, Decimal]] = dict(opens_closes or {})
    for candle in candles or ():
        by_open[candle.open_time] = (Decimal(str(candle.open)), Decimal(str(candle.close)))
    built: list[FootprintBar] = []
    for open_time, rows in bars:
        levels = sorted((FootprintLevel(price, bid, ask) for price, bid, ask in rows), key=lambda level: level.price)
        if not levels:
            continue
        open_close = by_open.get(open_time) if open_time is not None else None
        built.append(
            FootprintBar(
                levels=tuple(levels),
                open_time=open_time,
                open=open_close[0] if open_close else None,
                close=open_close[1] if open_close else None,
            )
        )
    if not built:
        return None
    if all(bar.open_time is not None for bar in built):
        built.sort(key=lambda bar: bar.open_time)
    if tick_size is None:
        tick_size = _infer_tick(built)
    return FootprintSeries(bars=tuple(built), source=source, tick_size=tick_size)


def _infer_tick(bars: Sequence[FootprintBar]) -> Decimal | None:
    gaps = [
        bar.levels[index + 1].price - bar.levels[index].price
        for bar in bars
        for index in range(len(bar.levels) - 1)
    ]
    positive = [gap for gap in gaps if gap > 0]
    return min(positive) if positive else None


def analyze_footprint(
    series: FootprintSeries,
    *,
    imbalance_ratio: Decimal = IMBALANCE_RATIO,
    stack_min: int = STACK_MIN,
) -> FootprintReading:
    """Read the last bar: imbalances, stacks, auction edges, cluster, thin extreme, POC."""
    bar = series.last
    levels = bar.levels
    statements: list[OrderflowStatement] = []
    refs = ("footprint",)

    # --- F1/F2 diagonal imbalances ---
    buy_flags: list[bool] = []
    sell_flags: list[bool] = []
    for index, level in enumerate(levels):
        below = levels[index - 1] if index > 0 else None
        above = levels[index + 1] if index + 1 < len(levels) else None
        # Buyers lift the ask at this price against sellers hitting the bid one tick lower.
        # A zero on the opposite side counts as an imbalance, as footprint tools show it.
        buy_flags.append(below is not None and level.ask_volume > ZERO and level.ask_volume >= imbalance_ratio * below.bid_volume)
        # Sellers hit the bid at this price against buyers lifting the ask one tick higher.
        sell_flags.append(above is not None and level.bid_volume > ZERO and level.bid_volume >= imbalance_ratio * above.ask_volume)
    buy_imbalances = sum(buy_flags)
    sell_imbalances = sum(sell_flags)
    stacked_buy = _longest_run(buy_flags)
    stacked_sell = _longest_run(sell_flags)
    if buy_imbalances or sell_imbalances:
        statements.append(
            OrderflowStatement(
                kind=OrderflowStatementKind.OBSERVATION,
                text=f"footprint_imbalances buy={buy_imbalances} sell={sell_imbalances}",
                evidence_refs=refs,
            )
        )
    if stacked_buy >= stack_min:
        statements.append(
            OrderflowStatement(
                kind=OrderflowStatementKind.INTERPRETATION,
                text=f"stacked_buy_imbalances={stacked_buy}",
                evidence_refs=refs,
                weight=Decimal("0.7"),
            )
        )
    if stacked_sell >= stack_min:
        statements.append(
            OrderflowStatement(
                kind=OrderflowStatementKind.INTERPRETATION,
                text=f"stacked_sell_imbalances={stacked_sell}",
                evidence_refs=refs,
                weight=Decimal("0.7"),
            )
        )

    # --- F3 auction edges ---
    finished_high = min(bar.high.bid_volume, bar.high.ask_volume) == ZERO
    finished_low = min(bar.low.bid_volume, bar.low.ask_volume) == ZERO
    unfinished_high = not finished_high
    unfinished_low = not finished_low
    for label, finished in (("high", finished_high), ("low", finished_low)):
        statements.append(
            OrderflowStatement(
                kind=OrderflowStatementKind.OBSERVATION,
                text=f"{'finished' if finished else 'unfinished'}_auction_{label}",
                evidence_refs=refs,
            )
        )

    # --- F4/F5 cluster and thin extreme (need a mean level volume) ---
    mean_level = bar.total / Decimal(len(levels)) if levels else ZERO
    absorption_cluster: str | None = None
    thin_extreme: str | None = None
    if mean_level > ZERO and len(levels) >= 3:
        span = bar.high.price - bar.low.price
        edge = span * EDGE_FRACTION
        direction = bar.direction
        cluster = max(levels, key=lambda level: (level.total, -level.price))
        if cluster.total >= CLUSTER_RATIO * mean_level and span > ZERO:
            near_high = bar.high.price - cluster.price <= edge
            near_low = cluster.price - bar.low.price <= edge
            # Buyers pushing into a heavy level at the top: passive sellers absorb; and vice versa.
            if near_high and cluster.ask_volume >= cluster.bid_volume and direction != "DOWN":
                absorption_cluster = "PASSIVE_SELLERS"
            elif near_low and cluster.bid_volume >= cluster.ask_volume and direction != "UP":
                absorption_cluster = "PASSIVE_BUYERS"
            if absorption_cluster:
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.INTERPRETATION,
                        text=f"footprint_absorption_cluster={absorption_cluster.lower()} price={cluster.price} ratio={(cluster.total / mean_level):.1f}",
                        evidence_refs=refs,
                        weight=Decimal("0.8"),
                    )
                )
        if direction == "UP" and bar.high.total <= THIN_EXTREME_RATIO * mean_level:
            thin_extreme = "BUYERS_THIN_AT_HIGH"
        elif direction == "DOWN" and bar.low.total <= THIN_EXTREME_RATIO * mean_level:
            thin_extreme = "SELLERS_THIN_AT_LOW"
        if thin_extreme:
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.INTERPRETATION,
                    text=f"footprint_thin_extreme={thin_extreme.lower()}",
                    evidence_refs=refs,
                    weight=Decimal("0.8"),
                )
            )

    # --- F6 POC location ---
    poc_location: str | None = None
    if len(levels) >= 3:
        span = bar.high.price - bar.low.price
        if span > ZERO:
            position = (bar.poc.price - bar.low.price) / span
            poc_location = "UPPER" if position >= Decimal("2") / Decimal("3") else "LOWER" if position <= Decimal("1") / Decimal("3") else "MIDDLE"
            statements.append(
                OrderflowStatement(kind=OrderflowStatementKind.OBSERVATION, text=f"footprint_poc_location={poc_location}", evidence_refs=refs)
            )

    summary: dict[str, Any] = {
        "source": series.source,
        "bars": len(series.bars),
        "levels": len(levels),
        "last_delta": str(bar.delta),
        "last_total": str(bar.total),
        "poc": str(bar.poc.price),
        "poc_location": poc_location,
        "buy_imbalances": buy_imbalances,
        "sell_imbalances": sell_imbalances,
        "stacked_buy": stacked_buy,
        "stacked_sell": stacked_sell,
        "finished_high": finished_high,
        "finished_low": finished_low,
        "absorption_cluster": absorption_cluster,
        "thin_extreme": thin_extreme,
    }
    if series.tick_size is not None:
        summary["tick_size"] = str(series.tick_size)
    if series.skipped_trades:
        summary["skipped_trades"] = series.skipped_trades
    return FootprintReading(
        statements=tuple(statements),
        summary=summary,
        buy_imbalances=buy_imbalances,
        sell_imbalances=sell_imbalances,
        stacked_buy=stacked_buy,
        stacked_sell=stacked_sell,
        finished_high=finished_high,
        finished_low=finished_low,
        unfinished_high=unfinished_high,
        unfinished_low=unfinished_low,
        absorption_cluster=absorption_cluster,
        thin_extreme=thin_extreme,
        poc_location=poc_location,
    )


def _longest_run(flags: Sequence[bool]) -> int:
    best = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        best = max(best, current)
    return best
