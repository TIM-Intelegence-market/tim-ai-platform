"""Per-symbol candle state: one aggregator and one history per symbol.

The live runtime deep-copies its whole aggregator for every trade (candidate
state, committed only after enrichment succeeded). With one shared aggregator
that copy grows with the number of symbols. Here each symbol owns its own
aggregator, so a candidate copy only ever contains one symbol and a failure in
one symbol cannot roll back or block another one.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass, field

from src.data_ingestion.aggregator import CandleAggregator
from src.models.market_data import Candle, Trade

HISTORY_LIMIT = 500


class UnknownSymbolError(ValueError):
    """A trade for a symbol that is not configured is rejected, never auto-added."""


@dataclass(slots=True)
class SymbolPipelineState:
    symbol: str
    aggregator: CandleAggregator
    history: dict[str, list[Candle]] = field(default_factory=dict)


class SymbolPartitionedCandles:
    def __init__(self, symbols: Iterable[str], timeframes: Iterable[str]) -> None:
        self.timeframes = tuple(timeframes)
        self._states: dict[str, SymbolPipelineState] = {}
        for symbol in symbols:
            if symbol in self._states:
                raise ValueError(f"duplicate symbol {symbol}")
            self._states[symbol] = SymbolPipelineState(
                symbol,
                CandleAggregator(self.timeframes),
                {timeframe: [] for timeframe in self.timeframes},
            )
        if not self._states:
            raise ValueError("at least one symbol is required")

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self._states)

    def state(self, symbol: str) -> SymbolPipelineState:
        try:
            return self._states[symbol]
        except KeyError as error:
            raise UnknownSymbolError(f"symbol not configured: {symbol}") from error

    def candidate(self, trade: Trade) -> tuple[CandleAggregator, list[Candle]]:
        """Apply ``trade`` to a copy of its own symbol's aggregator only.

        Raises like ``CandleAggregator.add_trade`` (out of order, closed candle);
        the committed state stays untouched until ``commit`` is called.
        """
        candidate = copy.deepcopy(self.state(trade.symbol).aggregator)
        return candidate, candidate.add_trade(trade)

    def commit(self, symbol: str, candidate: CandleAggregator, completed: Iterable[Candle]) -> None:
        state = self.state(symbol)
        for candle in completed:
            if candle.symbol != symbol:
                raise ValueError("completed candle belongs to another symbol")
            history = state.history[candle.timeframe]
            history[:] = [item for item in history if item.open_time != candle.open_time]
            history.append(candle)
            history.sort(key=lambda item: item.open_time)
            del history[:-HISTORY_LIMIT]
        state.aggregator = candidate

    def history(self, symbol: str, timeframe: str) -> list[Candle]:
        return list(self.state(symbol).history[timeframe])
