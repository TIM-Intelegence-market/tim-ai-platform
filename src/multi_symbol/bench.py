"""Measure the per-trade deepcopy cost: shared aggregator vs. one per symbol.

Run: ``python -m src.multi_symbol.bench`` (pure CPU, no network, no database).
"""

from __future__ import annotations

import copy
import timeit
from datetime import datetime, timezone

from src.data_ingestion.aggregator import CandleAggregator
from src.models.market_data import Trade
from src.multi_symbol.partition import SymbolPartitionedCandles

TIMEFRAMES = ("1m", "5m", "15m", "1h")
START = datetime(2026, 10, 24, tzinfo=timezone.utc)


def _symbols(count: int) -> list[str]:
    return [f"SYM{index}USDT" for index in range(count)]


def measure(count: int, *, number: int = 5_000, repeat: int = 5) -> dict[str, float]:
    shared = CandleAggregator(TIMEFRAMES)
    partitioned = SymbolPartitionedCandles(_symbols(count), TIMEFRAMES)
    for symbol in _symbols(count):
        trade = Trade(symbol, 100.0, 1.0, START, 1)
        shared.add_trade(trade)
        candidate, completed = partitioned.candidate(trade)
        partitioned.commit(symbol, candidate, completed)
    target = _symbols(count)[0]
    shared_us = min(timeit.repeat(lambda: copy.deepcopy(shared), number=number, repeat=repeat)) / number * 1e6
    own_us = min(
        timeit.repeat(lambda: copy.deepcopy(partitioned.state(target).aggregator), number=number, repeat=repeat)
    ) / number * 1e6
    return {"symbols": count, "shared_deepcopy_us": round(shared_us, 1), "per_symbol_deepcopy_us": round(own_us, 1)}


if __name__ == "__main__":
    for symbol_count in (1, 3, 20):
        print(measure(symbol_count))
