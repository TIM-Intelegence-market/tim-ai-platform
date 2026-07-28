from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.models.market_data import Trade
from src.orderflow.metrics import OrderflowMetricsEngine, OrderflowMetricsService


START = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def item(trade_id: int, second: int, quantity: float, buyer_is_maker: bool, price: float = 100.0) -> Trade:
    return Trade("BTCUSDT", price, quantity, START + timedelta(seconds=second), trade_id, buyer_is_maker)


TRADES = [item(1, 1, 2, False), item(2, 2, 1, True), item(3, 3, 3, False)]


def test_exact_orderflow_statistics_and_aggressor_semantics():
    metric = OrderflowMetricsEngine.calculate(TRADES, START, START + timedelta(seconds=10), symbol="BTCUSDT")
    assert metric.trade_count == 3 and metric.buy_count == 2 and metric.sell_count == 1
    assert metric.aggressive_buy_volume == Decimal("5")
    assert metric.aggressive_sell_volume == Decimal("1")
    assert metric.net_delta == metric.cumulative_delta == Decimal("4")
    assert metric.average_trade_size == Decimal("2")
    assert metric.largest_trade == Decimal("3")
    assert metric.trades_per_second == Decimal("0.3")
    assert metric.volume_per_second == Decimal("0.6")
    assert metric.buy_sell_ratio == Decimal("5")


def test_replay_and_input_order_have_identical_hash_and_output():
    engine = OrderflowMetricsEngine()
    first = engine.calculate(TRADES, START, START + timedelta(seconds=10), symbol="BTCUSDT")
    replay = engine.calculate(list(reversed(TRADES)), START, START + timedelta(seconds=10), symbol="BTCUSDT")
    assert first == replay
    assert first.source_hash == replay.source_hash and len(first.source_hash) == 64


def test_series_uses_fixed_boundaries_and_cumulative_delta():
    trades = [item(1, 1, 2, False), item(2, 11, 1, True), item(3, 20, 9, False)]
    series = OrderflowMetricsEngine().series(trades, START, START + timedelta(seconds=20), 10, symbol="BTCUSDT")
    assert len(series) == 2
    assert [value.net_delta for value in series] == [Decimal("2"), Decimal("-1")]
    assert [value.cumulative_delta for value in series] == [Decimal("2"), Decimal("1")]
    assert all(value.trade_count == 1 for value in series)  # end boundary is exclusive


def test_empty_and_one_sided_windows_are_explicit():
    empty = OrderflowMetricsEngine.calculate([], START, START + timedelta(seconds=1), symbol="BTCUSDT")
    assert empty.trade_count == 0 and empty.buy_sell_ratio is None and empty.net_delta == 0
    buys = OrderflowMetricsEngine.calculate([item(1, 0, 1, False)], START, START + timedelta(seconds=1), symbol="BTCUSDT")
    assert buys.buy_sell_ratio is None


@pytest.mark.parametrize("trades", [[TRADES[0], TRADES[0]], [Trade("ETHUSDT", 1, 1, START, 5, False), TRADES[0]]])
def test_governance_rejects_duplicate_identity_and_mixed_symbols(trades):
    with pytest.raises(ValueError): OrderflowMetricsEngine.calculate(trades, START, START + timedelta(seconds=10))


@pytest.mark.asyncio
async def test_service_reads_persisted_range_and_creates_no_research_objects():
    class Repository:
        async def agg_trades_between(self, symbol, start, end):
            assert symbol == "BTCUSDT" and start == START
            return TRADES
    metrics = await OrderflowMetricsService(Repository()).calculate_series("BTCUSDT", START, START + timedelta(seconds=10), 10)
    payload = metrics[0].to_dict()
    assert payload["mode"] == "OBSERVE" and payload["source"] == "BINANCE_SPOT_AGGTRADE"
    assert "confidence" not in payload and "observation" not in payload and "research_case" not in payload
