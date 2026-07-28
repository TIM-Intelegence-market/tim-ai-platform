from datetime import datetime, timedelta, timezone

import pytest

from src.data_ingestion.aggregator import CandleAggregator
from src.models.market_data import Trade


def test_aggregates_and_closes_candle() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    aggregator = CandleAggregator(("1m",))
    assert aggregator.add_trade(Trade("BTCUSDT", 100, 2, start)) == []
    assert aggregator.add_trade(Trade("BTCUSDT", 105, 1, start + timedelta(seconds=30))) == []
    completed = aggregator.add_trade(Trade("BTCUSDT", 103, 3, start + timedelta(minutes=1)))
    assert len(completed) == 1
    assert (completed[0].open, completed[0].high, completed[0].low, completed[0].close) == (100, 105, 100, 105)
    assert completed[0].volume == 3
    assert completed[0].trade_count == 2


def test_rejects_out_of_order_trade() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    aggregator = CandleAggregator(("1m",))
    aggregator.add_trade(Trade("BTCUSDT", 100, 1, start + timedelta(seconds=2)))
    with pytest.raises(ValueError, match="Out-of-order"):
        aggregator.add_trade(Trade("BTCUSDT", 100, 1, start))
