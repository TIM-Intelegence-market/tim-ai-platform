from datetime import datetime,timedelta,timezone
from uuid import uuid4

import pytest

from config.settings import settings
from src.database.connection import Database
from src.database.repository import MarketRepository
from src.models.market_data import Candle,Observation,ObservationKind
from src.observation.engine import candle_input_hash
from src.research.case_engine import ResearchCaseEngine


@pytest.mark.asyncio
async def test_observation_rolls_back_when_case_persistence_fails(monkeypatch):
    database=Database(settings.database_url);await database.connect();repository=MarketRepository(database)
    opened=datetime.now(timezone.utc)-timedelta(days=2);candle=Candle("AUDITTEST","1m",opened,opened+timedelta(minutes=1),100.0,101.0,99.0,100.0,1.0,1)
    await repository.upsert_candle(candle)
    observation=Observation(ObservationKind.REJECTION,"AUDITTEST","1m",candle.close_time,"TEST_ONLY atomicity",50,{"test_only":True},provenance="PUBLIC_MARKET_DATA_DETERMINISTIC",rule_id="bronxc",rule_version="1.0.0",input_hash=candle_input_hash([candle]),observation_id=uuid4())
    case=ResearchCaseEngine().ingest(observation)
    async def fail_case(*args):raise RuntimeError("TEST_ONLY case failure")
    monkeypatch.setattr(repository,"_upsert_case",fail_case)
    try:
        with pytest.raises(RuntimeError,match="case failure"):await repository.save_observation_with_case(observation,case)
        async with database.acquire() as connection:
            assert await connection.fetchval("SELECT count(*) FROM observations WHERE observation_id=$1",observation.observation_id)==0
            assert await connection.fetchval("SELECT count(*) FROM research_cases WHERE case_id=$1",case.case_id)==0
    finally:
        async with database.acquire() as connection:await connection.execute("DELETE FROM candles WHERE symbol='AUDITTEST'")
        await database.close()
