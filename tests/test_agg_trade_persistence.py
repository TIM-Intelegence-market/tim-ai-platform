from datetime import datetime, timedelta, timezone
import os

import pytest
import pytest_asyncio

from src.data_ingestion.aggregator import CandleAggregator
from src.database.connection import Database
from src.database.repository import MarketRepository, _validate_agg_trade_for_persistence, agg_trade_hash
from src.models.market_data import Trade


BASE = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=20)
SYMBOL = "AGGTEST"


def trade(trade_id: int, seconds: int = 0, price: float = 100.0) -> Trade:
    return Trade(SYMBOL, price, 0.25, BASE + timedelta(seconds=seconds), trade_id, False)


@pytest_asyncio.fixture
async def repository():
    database_url = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("isolated durable-ingestion PostgreSQL URL not provided")
    database = Database(database_url)
    await database.connect(); await database.initialize_schema()
    repo = MarketRepository(database)
    async with database.acquire() as connection:
        await connection.execute("DELETE FROM agg_trades WHERE symbol=$1", SYMBOL)
    yield repo
    async with database.acquire() as connection:
        await connection.execute("DELETE FROM agg_trades WHERE symbol=$1", SYMBOL)
    await database.close()


@pytest.mark.asyncio
async def test_duplicate_insert_is_idempotent_and_count_matches_unique_received(repository):
    received = [trade(1), trade(2, 1), trade(2, 1)]
    inserted = [await repository.insert_agg_trade(item) for item in received]
    assert inserted == [True, True, False]
    assert await repository.agg_trade_count(SYMBOL) == sum(inserted) == 2


@pytest.mark.asyncio
async def test_identity_collision_with_changed_payload_is_rejected(repository):
    await repository.insert_agg_trade(trade(10, price=100))
    with pytest.raises(ValueError, match="Conflicting payload"):
        await repository.insert_agg_trade(trade(10, price=101))
    assert await repository.agg_trade_count(SYMBOL) == 1


@pytest.mark.asyncio
async def test_restart_recovery_and_replay_produce_identical_candle_state(repository):
    original = [trade(20, 0, 100), trade(21, 10, 102), trade(22, 70, 101)]
    for item in original: assert await repository.insert_agg_trade(item)
    recovered = await repository.agg_trades_since(SYMBOL, BASE)
    assert [item.trade_id for item in recovered] == [20, 21, 22]
    live, replay = CandleAggregator(("1m",)), CandleAggregator(("1m",))
    live_output = [candle for item in original for candle in live.add_trade(item)]
    replay_output = [candle for item in recovered for candle in replay.add_trade(item)]
    assert live_output == replay_output
    assert live.snapshots() == replay.snapshots()


def test_hash_is_stable_and_governance_rejects_invalid_records():
    item = trade(30)
    assert agg_trade_hash(item) == agg_trade_hash(item)
    assert len(agg_trade_hash(item)) == 64
    with pytest.raises(ValueError, match="aggregate_trade_id"):
        _validate_agg_trade_for_persistence(Trade(SYMBOL, 100, 1, BASE, None, False))
    with pytest.raises(ValueError, match="buyer_is_maker"):
        _validate_agg_trade_for_persistence(Trade(SYMBOL, 100, 1, BASE, 1, None))
    with pytest.raises(ValueError, match="Future"):
        _validate_agg_trade_for_persistence(Trade(SYMBOL, 100, 1, datetime.now(timezone.utc)+timedelta(minutes=1), 1, False))
