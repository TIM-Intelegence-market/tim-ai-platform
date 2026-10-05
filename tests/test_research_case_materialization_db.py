"""Observation -> Builder -> Persistence (isolated test PostgreSQL only).

Skipped unless TIM_DURABLE_TEST_DATABASE_URL points at an isolated test DB.
Proves: real pipeline writes cases, materialization leaves observations
untouched, a second apply changes nothing and validate finds 0 differences.
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from src.database.connection import Database
from src.database.repository import MarketRepository
from src.models.market_data import Candle
from src.observation.engine import ObservationEngine
from src.research.case_engine import ResearchCaseEngine

SYMBOL = "MATTEST"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/materialize_research_cases.py"


def _script():
    spec = importlib.util.spec_from_file_location("materialize_research_cases", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_materialization_against_isolated_database_is_idempotent_and_read_only() -> None:
    url = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("isolated durable-ingestion PostgreSQL URL not provided")
    script = _script()
    db = Database(url)
    await db.connect()
    try:
        async with db.acquire() as con:
            await con.execute((Path(__file__).resolve().parents[1] / "src/database/schema.sql").read_text(encoding="utf-8"))
            for table in ("research_cases", "observations", "candles"):
                await con.execute(f"DELETE FROM {table} WHERE symbol=$1", SYMBOL)
        repo = MarketRepository(db)
        engine, live_cases, cumulative = ObservationEngine(), ResearchCaseEngine(), []
        start = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=3)
        for offset, values in enumerate(script.FIXTURE_WINDOWS):
            base = start + timedelta(days=offset)
            candles = [Candle(SYMBOL, "1m", base + timedelta(minutes=i), base + timedelta(minutes=i + 1), float(o), float(h), float(low), float(c), 10.0, 10)
                       for i, (o, h, low, c) in enumerate(values[1])]
            for candle in candles:
                await repo.upsert_candle(candle)
            cumulative.extend(candles)
            for observation in engine.evaluate(list(cumulative)):
                await repo.save_observation_with_case(observation, live_cases.ingest(observation))
        as_of = start + timedelta(days=3)
        before = await repo.observations_fingerprint(SYMBOL)
        assert before["observations"] >= 3

        result, existing = await script.build_from_db(repo, SYMBOL, as_of)
        assert len(existing) == len(result.cases) >= 3
        first = await repo.apply_research_cases(result.cases)
        assert first["inserted"] == 0 and first["updated"] + first["unchanged"] == len(result.cases)
        assert await repo.observations_fingerprint(SYMBOL) == before

        again, persisted = await script.build_from_db(repo, SYMBOL, as_of)
        assert await repo.apply_research_cases(again.cases) == {"inserted": 0, "updated": 0, "unchanged": len(again.cases), "skipped_newer": 0}
        earlier = await repo.apply_research_cases(again.cases, as_of=start)
        assert earlier["skipped_newer"] == len(again.cases) and earlier["updated"] == 0
        assert {c.case_id: c.to_dict() for c in persisted} == {c.case_id: c.to_dict() for c in again.cases}
        assert again.manifest()["manifest_hash"] == result.manifest()["manifest_hash"]
        assert all(case.status != "CONFIRMED" for case in persisted)
        assert all(case.missing_evidence for case in persisted)

        # A stale opened_at (kept by live upserts) must be repaired by apply, not reported forever.
        victim = persisted[0]
        async with db.acquire() as con:
            await con.execute("UPDATE research_cases SET opened_at=opened_at-interval '10 minutes' WHERE case_id=$1", victim.case_id)
        assert (await repo.apply_research_cases(again.cases))["updated"] == 1
        assert await repo.apply_research_cases(again.cases) == {"inserted": 0, "updated": 0, "unchanged": len(again.cases), "skipped_newer": 0}
        repaired = {c.case_id: c.to_dict() for c in await repo.observation_research_cases(SYMBOL)}
        assert repaired == {c.case_id: c.to_dict() for c in again.cases}

        # The live runtime keeps appending: a row created after the cutoff must not trip the check.
        cutoff = datetime.now(timezone.utc)
        pinned = await repo.observations_fingerprint(SYMBOL, cutoff)
        assert pinned == before
        template = (await repo.observations_until(SYMBOL, as_of))[0]
        async with db.acquire() as con:  # raw insert: a late runtime row, even one observed inside the window
            await repo._insert_observation(con, replace(template, observation_id=uuid4(), created_at=datetime.now(timezone.utc)))
        assert await repo.observations_fingerprint(SYMBOL, cutoff) == pinned
        assert (await repo.observations_fingerprint(SYMBOL))["observations"] == before["observations"] + 1
    finally:
        async with db.acquire() as con:
            for table in ("research_cases", "observations", "candles"):
                await con.execute(f"DELETE FROM {table} WHERE symbol=$1", SYMBOL)
        await db.close()
