"""Per-minute bars from raw aggTrades, the single input of every feature and label.

A bar holds exact integers only: quantities in 1e-8 BTC ("sats"), prices in
1e-8 USDT ("e8"), quote volume in 1e-8 USDT. The same ``reduce_trades`` turns
archive rows (offline) and, later, live trades into bars, so the lab and a
future live adapter compute features from identical inputs.

Units are part of the field names; there is no silent unit switch.
"""
from __future__ import annotations

from dataclasses import astuple, dataclass, fields
from typing import Iterable, Iterator, NamedTuple, Sequence

MINUTE_MS = 60_000
MINUTES_PER_DAY = 1_440
DAY_MS = 86_400_000
E8 = 10**8
LARGE_TRADE_SATS = E8  # one BTC per aggTrade counts as "large" (fixed for bar version 1)
BAR_VERSION = "1.2.0"  # 1.2.0: sufficient statistics for within-minute sequence features
PROFILE_STEP_DIVISOR = 1000  # bin width about 0.1 % of the first trade price of the day


class TradeTick(NamedTuple):
    """One aggTrade. ``buyer_is_maker`` True means the aggressor sold."""

    agg_trade_id: int
    price_e8: int
    qty_sats: int
    time_ms: int
    buyer_is_maker: bool


@dataclass(frozen=True, slots=True)
class MinuteBar:
    window_start_ms: int
    trade_count: int
    buy_count: int
    buy_sats: int
    sell_sats: int
    largest_sats: int
    large_count: int
    buy_quote_e8: int
    sell_quote_e8: int
    first_price_e8: int  # 0 when the minute has no trade
    last_price_e8: int
    high_price_e8: int
    low_price_e8: int
    last_trade_ms: int  # 0 when the minute has no trade
    first_sign: int = 0  # +1 buy, -1 sell; zero means absent/legacy statistics
    last_sign: int = 0
    signed_tail_run: int = 0
    sign_product_sum: int = 0  # sum(sign[i-1] * sign[i]) within this minute, aggTrade-id order
    peak_second_sats: int = 0  # largest total volume of the 60 fixed UTC second buckets

    def __post_init__(self) -> None:
        if self.window_start_ms % MINUTE_MS:
            raise ValueError("window_start_ms must be minute aligned")
        if not 0 <= self.buy_count <= self.trade_count:
            raise ValueError("buy_count must lie in 0..trade_count")
        if min(self.buy_sats, self.sell_sats, self.largest_sats, self.large_count, self.buy_quote_e8, self.sell_quote_e8) < 0:
            raise ValueError("bar values cannot be negative")
        if self.trade_count == 0:
            if any((self.buy_sats, self.sell_sats, self.largest_sats, self.first_price_e8, self.last_price_e8, self.last_trade_ms)):
                raise ValueError("an empty minute carries no volume or price")
        else:
            if not 0 < self.low_price_e8 <= min(self.first_price_e8, self.last_price_e8) <= max(self.first_price_e8, self.last_price_e8) <= self.high_price_e8:
                raise ValueError("inconsistent prices")
            if not self.window_start_ms <= self.last_trade_ms < self.window_start_ms + MINUTE_MS:
                raise ValueError("last trade outside the minute")
        if self.first_sign:
            if self.first_sign not in (-1, 1) or self.last_sign not in (-1, 1):
                raise ValueError("invalid sequence sign")
            if not 1 <= abs(self.signed_tail_run) <= self.trade_count or self.signed_tail_run * self.last_sign <= 0:
                raise ValueError("invalid last run")
            if abs(self.sign_product_sum) > self.trade_count - 1:
                raise ValueError("invalid adjacent sign sum")
            if not 0 < self.peak_second_sats <= self.buy_sats + self.sell_sats:
                raise ValueError("invalid peak-second volume")

    @property
    def has_trades(self) -> bool:
        return self.trade_count > 0

    @property
    def sell_count(self) -> int:
        return self.trade_count - self.buy_count

    def as_row(self) -> list[int]:
        return list(astuple(self))

    @classmethod
    def from_row(cls, row: Sequence[str | int]) -> "MinuteBar":
        return cls(*(int(value) for value in row))

    @staticmethod
    def empty(window_start_ms: int) -> "MinuteBar":
        return MinuteBar(window_start_ms, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


BAR_HEADER = [f.name for f in fields(MinuteBar)]


def decimal_to_e8(text: str) -> int:
    """Exact 1e-8 integer from a decimal string with at most eight decimals."""
    value = text.strip()
    if not value or value.startswith("-"):
        raise ValueError(f"not a positive decimal: {text!r}")
    whole, _, frac = value.partition(".")
    frac = frac.rstrip("0")
    if len(frac) > 8 or not (whole or "0").isdigit() or (frac and not frac.isdigit()):
        raise ValueError(f"not an 1e-8 decimal: {text!r}")
    return int(whole or "0") * E8 + int(frac.ljust(8, "0") or "0")


def archive_ms(value: str) -> int:
    stamp = int(value)
    return stamp // 1000 if stamp >= 10**14 else stamp


def parse_buyer_is_maker(text: str) -> bool:
    flag = text.strip().lower()
    if flag in {"true", "1"}:
        return True
    if flag in {"false", "0"}:
        return False
    raise ValueError(f"unknown is_buyer_maker flag {text!r}")


def ticks_from_rows(rows: Iterable[Sequence[str]]) -> Iterator[TradeTick]:
    """Spot aggTrades archive rows: id, price, qty, first_id, last_id, time, is_buyer_maker, is_best_match."""
    for row in rows:
        yield TradeTick(int(row[0]), decimal_to_e8(row[1]), decimal_to_e8(row[2]), archive_ms(row[5]), parse_buyer_is_maker(row[6]))


@dataclass(slots=True)
class ReductionQuality:
    """What the reduction noticed; written to the day manifest and the quality report."""

    rows: int = 0
    duplicate_rows: int = 0  # identical aggTrade id seen again: dropped
    id_gaps: int = 0  # missing aggTrade ids between consecutive rows
    time_regressions: int = 0  # later id with an earlier timestamp (kept, counted)
    empty_minutes: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"rows": self.rows, "duplicate_rows": self.duplicate_rows, "id_gaps": self.id_gaps,
                "time_regressions": self.time_regressions, "empty_minutes": self.empty_minutes}


def nice_width_e8(price_e8: int) -> int:
    """Largest 1/2/5 x 10^k (in 1e-8 USDT, at least 0.01 USDT) not above price / PROFILE_STEP_DIVISOR."""
    target = max(price_e8 // PROFILE_STEP_DIVISOR, 10**6)
    best = 10**6
    scale = 10**6
    while scale <= target:
        for factor in (1, 2, 5):
            if factor * scale <= target:
                best = factor * scale
        scale *= 10
    return best


@dataclass(frozen=True, slots=True)
class DayProfile:
    """Aggressive volume per (minute of day, price bin) on one bin width fixed for the whole UTC day.

    ``width_e8`` comes from the first trade of the day, so a developing profile
    never needs a price that was not yet known. Bin b covers [b * width, (b + 1) * width).
    """

    day_start_ms: int
    width_e8: int
    entries: tuple[tuple[int, int, int, int], ...]  # (minute, bin, buy_sats, sell_sats), sorted

    def as_rows(self) -> list[list[int]]:
        return [list(e) for e in self.entries]


PROFILE_HEADER = ["minute", "bin", "buy_sats", "sell_sats"]


def reduce_trades(ticks: Iterable[TradeTick], day_start_ms: int) -> tuple[list[MinuteBar], ReductionQuality]:
    bars, quality, _ = reduce_trades_with_profile(ticks, day_start_ms)
    return bars, quality


def reduce_trades_with_profile(ticks: Iterable[TradeTick], day_start_ms: int) -> tuple[list[MinuteBar], ReductionQuality, DayProfile]:
    """One UTC day of ticks -> 1440 bars. Trades outside the day raise (time zone or file errors).

    Ids must ascend; an exact repeat of the previous id is a duplicate row and is
    dropped and counted, a smaller id refuses the day.
    """
    if day_start_ms % DAY_MS:
        raise ValueError("day_start_ms must be a UTC midnight")
    quality = ReductionQuality()
    acc: list[list[int] | None] = [None] * MINUTES_PER_DAY
    second_volume: list[dict[int, int] | None] = [None] * MINUTES_PER_DAY
    previous_id: int | None = None
    previous_time = -1
    seen_at_previous: TradeTick | None = None
    width = 0
    cells: dict[tuple[int, int], list[int]] = {}
    for tick in ticks:
        quality.rows += 1
        if previous_id is not None:
            if tick.agg_trade_id == previous_id:
                if tick != seen_at_previous:
                    raise ValueError(f"aggTrade id {tick.agg_trade_id} repeats with different content")
                quality.duplicate_rows += 1
                continue
            if tick.agg_trade_id < previous_id:
                raise ValueError("aggTrades must be in ascending id order")
            quality.id_gaps += tick.agg_trade_id - previous_id - 1
        if tick.time_ms < previous_time:
            quality.time_regressions += 1
        previous_id, previous_time, seen_at_previous = tick.agg_trade_id, max(previous_time, tick.time_ms), tick
        minute = (tick.time_ms - day_start_ms) // MINUTE_MS
        if not 0 <= minute < MINUTES_PER_DAY:
            raise ValueError(f"trade at {tick.time_ms} lies outside the UTC day starting {day_start_ms}")
        if tick.qty_sats <= 0 or tick.price_e8 <= 0:
            raise ValueError("zero quantity or price")
        if not width:
            width = nice_width_e8(tick.price_e8)
        cell = cells.setdefault((minute, tick.price_e8 // width), [0, 0])
        cell[1 if tick.buyer_is_maker else 0] += tick.qty_sats
        quote = tick.price_e8 * tick.qty_sats  # 1e-16 USDT, summed exactly, divided once per minute
        slot = acc[minute]
        if slot is None:
            # count, buy_count, buy_sats, sell_sats, largest, large, buy_quote, sell_quote, first, last, high, low, last_ms
            slot = acc[minute] = [0, 0, 0, 0, 0, 0, 0, 0, tick.price_e8, 0, tick.price_e8, tick.price_e8, 0,
                                  0, 0, 0, 0, 0]
            second_volume[minute] = {}
        sign = -1 if tick.buyer_is_maker else 1
        if slot[14]:
            slot[16] += slot[14] * sign
        else:
            slot[13] = sign
        slot[15] = slot[15] + sign if slot[14] == sign else sign
        slot[14] = sign
        seconds = second_volume[minute]
        second = (tick.time_ms - day_start_ms) % MINUTE_MS // 1000
        seconds[second] = seconds.get(second, 0) + tick.qty_sats
        slot[17] = max(slot[17], seconds[second])
        slot[0] += 1
        if tick.buyer_is_maker:
            slot[3] += tick.qty_sats
            slot[7] += quote
        else:
            slot[1] += 1
            slot[2] += tick.qty_sats
            slot[6] += quote
        if tick.qty_sats > slot[4]:
            slot[4] = tick.qty_sats
        if tick.qty_sats >= LARGE_TRADE_SATS:
            slot[5] += 1
        slot[9] = tick.price_e8  # ids ascend, so the last row is the last trade
        if tick.price_e8 > slot[10]:
            slot[10] = tick.price_e8
        if tick.price_e8 < slot[11]:
            slot[11] = tick.price_e8
        if tick.time_ms > slot[12]:
            slot[12] = tick.time_ms
    bars: list[MinuteBar] = []
    for minute, slot in enumerate(acc):
        start = day_start_ms + minute * MINUTE_MS
        if slot is None:
            quality.empty_minutes += 1
            bars.append(MinuteBar.empty(start))
            continue
        bars.append(MinuteBar(start, slot[0], slot[1], slot[2], slot[3], slot[4], slot[5], slot[6] // E8, slot[7] // E8,
                              slot[8], slot[9], slot[10], slot[11], slot[12], *slot[13:18]))
    entries = tuple((m, b, v[0], v[1]) for (m, b), v in sorted(cells.items()))
    return bars, quality, DayProfile(day_start_ms, width, entries)
