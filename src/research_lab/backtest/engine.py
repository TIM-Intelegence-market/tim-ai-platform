"""Causal bar-by-bar backtest engine (protocol section 4).

Strategies only ever see a History view that ends at the current closed bar;
reading a later bar raises IndexError. Entries fill at the next bar's open.
"""
from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
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
    cost_r: float  # fees only; slippage is inside the fill prices
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
    locked_signals: int = 0  # refused by the portfolio position cap (run_portfolio); also counted in ignored_signals
    ignored_times: list[int] = field(default_factory=list)  # open times of every ignored signal (own position or cap)
    locked_times: list[int] = field(default_factory=list)  # open times of the signals refused by the cap only


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
        rate = funding[i]
        payment = abs(rate.rate) * notional if rate.proxy else side * rate.rate * notional
        if payment < 0 and not costs.funding_credits_allowed:
            payment = 0.0
        total += payment
    return total


class _Runner:
    """State machine for one instrument. ``run_backtest`` steps a single runner over its
    bars; ``run_portfolio`` steps several in lockstep so that a position cap can be shared.

    Each bar is processed in two phases: ``pre_signal`` closes a position that ended with a
    gap or by rule, fills a pending entry at the open and applies stop/target/time stop;
    ``signal`` evaluates the exit rule and the strategy on the closed bar and books the
    pending entry for the next open."""

    def __init__(self, bars: Sequence[Kline], strategy: Strategy, interval_ms: int, *, costs: CostModel, funding: Sequence[FundingRate],
                 start_ms: int | None, end_ms: int | None, atr_at_signal: Callable[[History], float | None] | None,
                 gap_entry_as_loss: bool) -> None:
        self.bars = bars
        self.strategy = strategy
        self.interval_ms = interval_ms
        self.costs = costs
        self.funding = funding
        self.funding_times = [f.time for f in funding]
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.atr_at_signal = atr_at_signal
        self.gap_entry_as_loss = gap_entry_as_loss
        self.result = BacktestResult()
        self.position: Position | None = None
        self.pending: tuple[int, Signal, float | None] | None = None  # (signal index, signal, atr)
        self.exit_next_open = False
        self.signal_time = 0
        self.signal_atr: float | None = None
        self.time_stop: int | None = None
        self.exit_rule: ExitRule | None = None
        self.target_r: float | None = None

    @property
    def busy(self) -> bool:
        """An open position or a pending entry occupies one portfolio slot. A position that
        exits by rule at the next open does not (it makes room, as in ``run_backtest``)."""
        return (self.position is not None and not self.exit_next_open) or self.pending is not None

    def _close(self, t: int, raw_price: float, reason: str, moment: int, slip: float) -> None:
        position = self.position
        assert position is not None
        self.exit_next_open = False
        side, entry = position.side, position.entry_price
        exit_price = raw_price * (1 - side * slip)
        risk = abs(entry - position.stop)
        fees = self.costs.fee * (entry + exit_price)
        fund = _funding_cost(self.funding, self.funding_times, side, entry, self.bars[position.entry_index].open_time, moment, self.costs)
        pnl = side * (exit_price - entry) - fees - fund
        self.result.trades.append(
            Trade(self.signal_time, self.bars[position.entry_index].open_time, moment, side, entry, exit_price, position.stop, reason,
                  t - position.entry_index + 1, pnl / risk, fees / risk, fund / risk,
                  None if self.signal_atr is None else risk / self.signal_atr, self.target_r)
        )
        self.position = None

    def pre_signal(self, t: int) -> None:
        bars, costs = self.bars, self.costs
        bar = bars[t]
        contiguous = t > 0 and bar.open_time - bars[t - 1].open_time == self.interval_ms

        if self.position is not None and not contiguous:
            self._close(t - 1, bars[t - 1].close, "gap", bars[t - 1].close_time + 1, costs.slippage)
            self.result.gap_closes += 1
        if self.position is not None and self.exit_next_open:
            self._close(t, bar.open, "rule", bar.open_time, costs.slippage)
        if self.pending is not None:
            index, signal, atr = self.pending
            self.pending = None
            if not contiguous:
                self.result.invalid_signals += 1
            else:
                entry = bar.open * (1 + signal.side * costs.slippage)
                # The stop must lie beyond the raw open too, or the trade would be
                # stopped at the open with a tiny risk and an extreme R.
                if (entry - signal.stop) * signal.side <= 0 or (bar.open - signal.stop) * signal.side <= 0:
                    planned = bars[index].close
                    planned_risk = (planned - signal.stop) * signal.side
                    if self.gap_entry_as_loss and planned_risk > 0:
                        cost = (2 * costs.fee + costs.slippage + costs.stop_slippage) * planned / planned_risk
                        self.result.trades.append(
                            Trade(bars[index].open_time, bar.open_time, bar.open_time, signal.side, bar.open, bar.open,
                                  signal.stop, "stop_before_entry", 1, -1.0 - cost, 2 * costs.fee * planned / planned_risk,
                                  0.0, None if atr is None else planned_risk / atr, signal.target_r))
                    else:
                        self.result.invalid_signals += 1
                else:
                    risk = abs(entry - signal.stop)
                    target = None if signal.target_r is None else entry + signal.side * signal.target_r * risk
                    self.position = Position(signal.side, t, entry, signal.stop, target)
                    self.signal_time, self.signal_atr = bars[index].open_time, atr
                    self.time_stop, self.exit_rule, self.target_r = signal.time_stop_bars, signal.exit_rule, signal.target_r
        if self.position is not None:
            hit = exit_on_bar(bar, self.position.side, self.position.stop, self.position.target)
            if hit is not None:
                price, reason, moment = hit
                self._close(t, price, reason, moment, costs.stop_slippage if reason.startswith("stop") else costs.slippage)
            elif self.time_stop is not None and t - self.position.entry_index + 1 >= self.time_stop:
                self._close(t, bar.close, "time", bar.close_time + 1, costs.slippage)

    def signal(self, t: int, may_enter: Callable[[], bool] | None = None) -> None:
        """Evaluate the strategy on bar t. ``may_enter`` is the portfolio's capacity check; a
        signal it refuses is counted as ignored and as locked."""
        bar = self.bars[t]
        in_range = (self.start_ms is None or bar.open_time >= self.start_ms) and (self.end_ms is None or bar.open_time < self.end_ms)
        history = History(self.bars, t)
        if self.position is not None and self.exit_rule is not None and self.exit_rule(history, self.position):
            self.exit_next_open = True
        signal = self.strategy(history) if in_range else None
        if signal is None:
            return
        self.result.signals.append((bar.open_time, signal.side, signal.stop))
        # A position that exits by rule at the next open makes room for a
        # signal on the same bar (reversal, e.g. L1 long/short).
        if (self.position is not None and not self.exit_next_open) or self.pending is not None:
            self.result.ignored_signals += 1
            self.result.ignored_times.append(bar.open_time)
        elif may_enter is not None and not may_enter():
            self.result.ignored_signals += 1
            self.result.locked_signals += 1
            self.result.ignored_times.append(bar.open_time)
            self.result.locked_times.append(bar.open_time)
        elif t + 1 < len(self.bars):
            self.pending = (t, signal, self.atr_at_signal(history) if self.atr_at_signal else None)
        else:
            self.result.invalid_signals += 1  # no next bar to enter on

    def finish(self) -> None:
        if self.position is not None:
            last = len(self.bars) - 1
            self._close(last, self.bars[last].close, "end", self.bars[last].close_time + 1, self.costs.slippage)


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
    gap_entry_as_loss: bool = False,
) -> BacktestResult:
    """Run one variant. Signals are only taken for bars in [start_ms, end_ms);
    earlier bars serve as indicator warm-up.

    gap_entry_as_loss (study S4, section 4.1): a signal whose entry bar opens at
    or beyond its stop is not dropped as invalid (that would select on the
    future) but booked as a full loss: -1 R minus the stop-case costs, R taken
    from the signal bar's close to the stop."""
    runner = _Runner(bars, strategy, interval_ms, costs=costs, funding=funding, start_ms=start_ms, end_ms=end_ms,
                     atr_at_signal=atr_at_signal, gap_entry_as_loss=gap_entry_as_loss)
    for t in range(len(bars)):
        runner.pre_signal(t)
        runner.signal(t)
    runner.finish()
    return runner.result


def run_portfolio(
    bars_by_symbol: Mapping[str, Sequence[Kline]],
    strategies: Mapping[str, Strategy],
    interval_ms: int,
    *,
    priority: Sequence[str],
    costs: CostModel = BASE_COSTS,
    funding_by_symbol: Mapping[str, Sequence[FundingRate]] | None = None,
    start_ms_by_symbol: Mapping[str, int | None] | None = None,
    end_ms: int | None = None,
    atr_at_signal: Callable[[History], float | None] | None = None,
    gap_entry_as_loss: bool = False,
    max_positions: int = 1,
) -> dict[str, BacktestResult]:
    """Several instruments in lockstep with at most ``max_positions`` open or pending
    positions over all of them (study S7b).

    Bars are visited in order of their open time. For every time stamp, phase one runs
    ``pre_signal`` for every instrument that has a bar there (exits and pending entries),
    phase two evaluates the strategies in ``priority`` order. A signal arriving while the
    cap is reached lapses (``ignored_signals`` and ``locked_signals``); nothing is queued.
    An exit on bar t frees the slot for signals on the close of the same bar, exactly as
    the single-instrument engine re-enters on its own exit bar. Per instrument the
    results are identical to ``run_backtest`` whenever the cap never binds."""
    order = list(priority)
    if sorted(order) != sorted(bars_by_symbol) or len(order) != len(set(order)):
        raise ValueError("priority must list every instrument exactly once")
    if max_positions < 1:
        raise ValueError("max_positions must be at least 1")
    funding_by_symbol = funding_by_symbol or {}
    start_ms_by_symbol = start_ms_by_symbol or {}
    runners = {
        sym: _Runner(bars_by_symbol[sym], strategies[sym], interval_ms, costs=costs, funding=funding_by_symbol.get(sym, ()),
                     start_ms=start_ms_by_symbol.get(sym), end_ms=end_ms, atr_at_signal=atr_at_signal,
                     gap_entry_as_loss=gap_entry_as_loss)
        for sym in order
    }
    index = {sym: {bar.open_time: i for i, bar in enumerate(bars_by_symbol[sym])} for sym in order}
    for sym in order:
        if len(index[sym]) != len(bars_by_symbol[sym]):
            raise ValueError(f"{sym}: duplicate open times")
    times = sorted(set().union(*(index[sym].keys() for sym in order)))

    def may_enter() -> bool:
        return sum(1 for r in runners.values() if r.busy) < max_positions

    for time in times:
        for sym in order:
            i = index[sym].get(time)
            if i is not None:
                runners[sym].pre_signal(i)
        for sym in order:
            i = index[sym].get(time)
            if i is not None:
                runners[sym].signal(i, may_enter)
    for runner in runners.values():
        runner.finish()
    return {sym: runners[sym].result for sym in order}
