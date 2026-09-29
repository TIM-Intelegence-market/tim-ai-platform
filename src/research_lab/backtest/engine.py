"""Causal bar-by-bar backtest engine (protocol section 4).

Strategies only ever see a History view that ends at the current closed bar;
reading a later bar raises IndexError. Entries fill at the next bar's open.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Callable, overload

from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.protocol import BASE_COSTS, CostModel


class History(Sequence[Kline]):
    """Read-only view of bars[0..t]; the future does not exist for a strategy."""

    __slots__ = ("_bars", "_end")

    def __init__(self, bars: Sequence[Kline], t: int) -> None:
        self._bars = bars
        self._end = t + 1

    def __len__(self) -> int:
        return self._end

    @overload
    def __getitem__(self, index: int) -> Kline: ...
    @overload
    def __getitem__(self, index: slice) -> list[Kline]: ...
    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(self._end)
            return [self._bars[i] for i in range(start, stop, step)]
        if index < 0:
            index += self._end
        if not 0 <= index < self._end:
            raise IndexError("bar index outside the visible history")
        return self._bars[index]


@dataclass(frozen=True, slots=True)
class Position:
    side: int
    entry_index: int
    entry_price: float
    stop: float
    target: float | None


ExitRule = Callable[[History, Position], bool]


@dataclass(frozen=True, slots=True)
class Signal:
    side: int  # +1 long, -1 short
    stop: float
    target_r: float | None = None
    time_stop_bars: int | None = None
    exit_rule: ExitRule | None = None

    def __post_init__(self) -> None:
        if self.side not in (1, -1):
            raise ValueError("side must be +1 or -1")
        if self.target_r is not None and self.target_r <= 0:
            raise ValueError("target_r must be positive")
        if self.time_stop_bars is not None and self.time_stop_bars < 1:
            raise ValueError("time_stop_bars must be at least 1")


Strategy = Callable[[History], Signal | None]


@dataclass(frozen=True, slots=True)
class Trade:
    signal_time: int
    entry_time: int
    exit_time: int
    side: int
    entry_price: float
    exit_price: float
    stop: float
    reason: str
    bars_held: int
    r: float  # net result in R after all costs
    cost_r: float
    funding_r: float
    stop_atr: float | None = None
    target_r: float | None = None


@dataclass(slots=True)
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    signals: list[tuple[int, int, float]] = field(default_factory=list)  # (time, side, stop)
    ignored_signals: int = 0
    invalid_signals: int = 0
    gap_closes: int = 0


def exit_on_bar(bar: Kline, side: int, stop: float, target: float | None) -> tuple[float, str, int] | None:
    """Stop or target fill on one bar as (raw price, reason, moment), or None.

    A bar opening beyond a level fills at the open. When stop and target are both
    touched inside the bar, the stop wins (protocol section 4.2)."""
    if (bar.open - stop) * side <= 0:
        return bar.open, "stop_gap", bar.open_time
    if target is not None and (bar.open - target) * side >= 0:
        return bar.open, "target_gap", bar.open_time
    if (bar.low <= stop) if side == 1 else (bar.high >= stop):
        return stop, "stop", bar.close_time + 1
    if target is not None and ((bar.high >= target) if side == 1 else (bar.low <= target)):
        return target, "target", bar.close_time + 1
    return None


def _funding_cost(funding: Sequence[FundingRate], times: list[int], side: int, notional: float, start: int, end: int, costs: CostModel) -> float:
    total = 0.0
    for i in range(bisect.bisect_left(times, start), bisect.bisect_left(times, end)):
        payment = side * funding[i].rate * notional
        if payment < 0 and not costs.funding_credits_allowed:
            payment = 0.0
        total += payment
    return total


def run_backtest(
    bars: Sequence[Kline],
    strategy: Strategy,
    interval_ms: int,
    *,
    costs: CostModel = BASE_COSTS,
    funding: Sequence[FundingRate] = (),
    start_ms: int | None = None,
    end_ms: int | None = None,
    atr_at_signal: Callable[[History], float | None] | None = None,
) -> BacktestResult:
    """Run one variant. Signals are only taken for bars in [start_ms, end_ms);
    earlier bars serve as indicator warm-up."""
    result = BacktestResult()
    funding_times = [f.time for f in funding]
    position: Position | None = None
    pending: tuple[int, Signal, float | None] | None = None  # (signal index, signal, atr)
    exit_next_open = False
    signal_time = 0
    signal_atr: float | None = None
    time_stop: int | None = None
    exit_rule: ExitRule | None = None
    target_r: float | None = None

    def close(t: int, raw_price: float, reason: str, moment: int, slip: float) -> None:
        nonlocal position, exit_next_open
        assert position is not None
        exit_next_open = False
        side, entry = position.side, position.entry_price
        exit_price = raw_price * (1 - side * slip)
        risk = abs(entry - position.stop)
        fees = costs.fee * (entry + exit_price)
        fund = _funding_cost(funding, funding_times, side, entry, bars[position.entry_index].open_time, moment, costs)
        pnl = side * (exit_price - entry) - fees - fund
        result.trades.append(
            Trade(signal_time, bars[position.entry_index].open_time, moment, side, entry, exit_price, position.stop, reason,
                  t - position.entry_index + 1, pnl / risk, fees / risk, fund / risk,
                  None if signal_atr is None else risk / signal_atr, target_r)
        )
        position = None

    for t, bar in enumerate(bars):
        contiguous = t > 0 and bar.open_time - bars[t - 1].open_time == interval_ms

        if position is not None and not contiguous:
            close(t - 1, bars[t - 1].close, "gap", bars[t - 1].close_time + 1, costs.slippage)
            result.gap_closes += 1
        if pending is not None:
            index, signal, atr = pending
            pending = None
            if not contiguous:
                result.invalid_signals += 1
            else:
                entry = bar.open * (1 + signal.side * costs.slippage)
                if (entry - signal.stop) * signal.side <= 0:
                    result.invalid_signals += 1
                else:
                    risk = abs(entry - signal.stop)
                    target = None if signal.target_r is None else entry + signal.side * signal.target_r * risk
                    position = Position(signal.side, t, entry, signal.stop, target)
                    signal_time, signal_atr = bars[index].open_time, atr
                    time_stop, exit_rule, target_r = signal.time_stop_bars, signal.exit_rule, signal.target_r
        if position is not None and exit_next_open:
            close(t, bar.open, "rule", bar.open_time, costs.slippage)
        if position is not None:
            hit = exit_on_bar(bar, position.side, position.stop, position.target)
            if hit is not None:
                price, reason, moment = hit
                close(t, price, reason, moment, costs.stop_slippage if reason.startswith("stop") else costs.slippage)
            elif time_stop is not None and t - position.entry_index + 1 >= time_stop:
                close(t, bar.close, "time", bar.close_time + 1, costs.slippage)

        in_range = (start_ms is None or bar.open_time >= start_ms) and (end_ms is None or bar.open_time < end_ms)
        history = History(bars, t)
        if position is not None and exit_rule is not None and exit_rule(history, position):
            exit_next_open = True
        signal = strategy(history) if in_range else None
        if signal is not None:
            result.signals.append((bar.open_time, signal.side, signal.stop))
            if position is not None or pending is not None:
                result.ignored_signals += 1
            elif t + 1 < len(bars):
                pending = (t, signal, atr_at_signal(history) if atr_at_signal else None)

    if position is not None:
        last = len(bars) - 1
        close(last, bars[last].close, "end", bars[last].close_time + 1, costs.slippage)
    return result
