from datetime import datetime,timedelta,timezone
import os
from uuid import uuid4

import asyncpg
import pytest

@pytest.mark.asyncio
async def test_observation_id_is_globally_unique_across_timestamps():
    database_url = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("isolated durable-ingestion PostgreSQL URL not provided")
    connection=await asyncpg.connect(database_url)
    transaction=connection.transaction();await transaction.start()
    observation_id=uuid4();at=datetime.now(timezone.utc)-timedelta(minutes=2)
    sql="""INSERT INTO observations(observation_id,observed_at,created_at,kind,symbol,timeframe,summary,confidence,evidence,source,provenance,observation_version,rule_id,rule_version,input_hash)
    VALUES($1,$2,$2,'REJECTION','BTCUSDT','1m','TEST_ONLY uniqueness',50,'{}'::jsonb,'test','PUBLIC_MARKET_DATA_DETERMINISTIC',1,'bronxc','1.0.0',$3)"""
    try:
        await connection.execute(sql,observation_id,at,"a"*64)
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(sql,observation_id,at+timedelta(seconds=1),"b"*64)
    finally:
        await transaction.rollback();await connection.close()
