from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.orderflow.metrics import OrderflowMetric
from src.orderflow.observations import OrderflowObservationEngine, OrderflowResearchCaseEngine


START=datetime(2026,7,22,12,tzinfo=timezone.utc)


def metric(start=START,**changes):
    values=dict(symbol="BTCUSDT",window_start=start,window_end=start+timedelta(minutes=1),trade_count=10,buy_count=5,sell_count=5,aggressive_buy_volume=Decimal("1"),aggressive_sell_volume=Decimal("1"),total_volume=Decimal("2"),net_delta=Decimal("0"),cumulative_delta=Decimal("0"),average_trade_size=Decimal("0.2"),largest_trade=Decimal("0.3"),trades_per_second=Decimal("0.166666"),volume_per_second=Decimal("0.033333"),buy_sell_ratio=Decimal("1"),source_hash="a"*64)
    values.update(changes);return OrderflowMetric(**values)


def test_observation_requires_two_satisfied_evidence_conditions():
    previous=metric()
    current=metric(START+timedelta(minutes=1),buy_count=10,sell_count=3,aggressive_buy_volume=Decimal("3"),aggressive_sell_volume=Decimal("1"),total_volume=Decimal("4"),net_delta=Decimal("2"),cumulative_delta=Decimal("2"),buy_sell_ratio=Decimal("3"),source_hash="b"*64)
    output=OrderflowObservationEngine().evaluate(previous,current)
    kinds={item.kind for item in output}
    assert "STRONG_BUYER_ACTIVITY" in kinds and "EXTREME_BUY_RATIO_ACTIVITY" in kinds
    assert all(len(item.evidence)>=2 for item in output)
    assert all("confidence" not in item.to_dict() for item in output)


def test_single_metric_change_does_not_create_observation():
    previous=metric();current=metric(START+timedelta(minutes=1),aggressive_buy_volume=Decimal("3"),source_hash="b"*64)
    assert OrderflowObservationEngine().evaluate(previous,current)==[]


def test_replay_ids_hashes_and_cases_are_identical():
    previous=metric();current=metric(START+timedelta(minutes=1),trade_count=30,buy_count=20,sell_count=10,aggressive_buy_volume=Decimal("4"),aggressive_sell_volume=Decimal("1"),total_volume=Decimal("5"),net_delta=Decimal("3"),cumulative_delta=Decimal("3"),trades_per_second=Decimal("0.5"),volume_per_second=Decimal("0.083333"),buy_sell_ratio=Decimal("4"),source_hash="b"*64)
    engine=OrderflowObservationEngine();first=engine.evaluate(previous,current);second=engine.evaluate(previous,current)
    assert first==second
    cases=[OrderflowResearchCaseEngine().create(item) for item in first]
    assert [case.case_id for case in cases]==[OrderflowResearchCaseEngine().create(item).case_id for item in second]
    assert all(case.outcome is None and case.missing_evidence==["subsequent_orderflow_context"] for case in cases)


def test_non_adjacent_windows_are_rejected():
    with pytest.raises(ValueError,match="adjacent"):OrderflowObservationEngine().evaluate(metric(),metric(START+timedelta(minutes=2)))


@pytest.mark.asyncio
async def test_observation_and_case_persistence_is_atomic_and_idempotent(monkeypatch):
    from config.settings import settings
    from src.database.connection import Database
    from src.database.repository import MarketRepository
    previous=metric();current=metric(START+timedelta(minutes=1),buy_count=10,sell_count=3,aggressive_buy_volume=Decimal("3"),aggressive_sell_volume=Decimal("1"),total_volume=Decimal("4"),net_delta=Decimal("2"),cumulative_delta=Decimal("2"),buy_sell_ratio=Decimal("3"),source_hash="b"*64)
    observation=OrderflowObservationEngine().evaluate(previous,current)[0];case=OrderflowResearchCaseEngine().create(observation)
    database=Database(settings.database_url);await database.connect();await database.initialize_schema();repository=MarketRepository(database)
    async with database.acquire() as con:
        await con.execute("DELETE FROM research_cases WHERE case_id=$1",case.case_id);await con.execute("DELETE FROM orderflow_observations WHERE observation_id=$1",observation.observation_id)
    original=repository._upsert_case
    async def fail(*args):raise RuntimeError("TEST_ONLY case failure")
    monkeypatch.setattr(repository,"_upsert_case",fail)
    with pytest.raises(RuntimeError,match="case failure"):await repository.save_orderflow_observation_with_case(observation,case)
    async with database.acquire() as con:assert await con.fetchval("SELECT count(*) FROM orderflow_observations WHERE observation_id=$1",observation.observation_id)==0
    monkeypatch.setattr(repository,"_upsert_case",original)
    assert await repository.save_orderflow_observation_with_case(observation,case) is True
    assert await repository.save_orderflow_observation_with_case(observation,case) is False
    async with database.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM orderflow_observations WHERE observation_id=$1",observation.observation_id)==1
        await con.execute("DELETE FROM research_cases WHERE case_id=$1",case.case_id);await con.execute("DELETE FROM orderflow_observations WHERE observation_id=$1",observation.observation_id)
    await database.close()
