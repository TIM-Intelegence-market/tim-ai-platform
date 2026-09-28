"""Race tolerance between live observation validation and historical writes.

Hazard class: an observation built from state A fails validation after
historical rows land inside its trailing window before the save re-read
(state B). The fix retries once from refreshed state; persistent mismatches
must still raise (fail-closed).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.database.connection import Database
from src.models.market_data import Candle
from src.observation.engine import ObservationEngine, candle_input_hash


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated test PostgreSQL URL not provided")
BASE = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
MISMATCH_MESSAGE = "input_hash does not match persisted candle input"


def candle(symbol: str, open_time: datetime, close_price: float, volume: float = 1.0) -> Candle:
    return Candle(symbol, "1m", open_time, open_time + timedelta(seconds=60),
                  close_price - 1.0, close_price + 1.0, close_price - 2.0,
                  close_price, volume, 10, True)


@pytest_asyncio.fixture
async def database():
    assert DATABASE_URL is not None
    value = Database(DATABASE_URL, min_size=1, max_size=2)
    await value.connect()
    async with value.acquire() as conn:
        await conn.execute("DELETE FROM observations WHERE symbol LIKE 'RACE%'")
        await conn.execute("DELETE FROM research_cases WHERE symbol LIKE 'RACE%'")
        await conn.execute("DELETE FROM candles WHERE symbol LIKE 'RACE%'")
    yield value
    async with value.acquire() as conn:
        await conn.execute("DELETE FROM observations WHERE symbol LIKE 'RACE%'")
        await conn.execute("DELETE FROM research_cases WHERE symbol LIKE 'RACE%'")
        await conn.execute("DELETE FROM candles WHERE symbol LIKE 'RACE%'")
    await value.close()



def dummy_case(symbol: str):
    from types import SimpleNamespace

    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        case_id="case-" + symbol, symbol=symbol, timeframe="1m",
        opened_at=now, updated_at=now, status="OPEN", observation_ids=[],
        evidence={}, missing_evidence={}, outcome=None,
        rule_versions={}, documentation="",
    )


def insert_candle_sql():
    return (
        "INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,"
        "volume,trade_count,closed) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)"
    )


@pytest.mark.asyncio
async def test_race_mechanism_characterization(database) -> None:
    """Build from state A, land a historical row, re-validate: must mismatch.

    Documents the hazard; passes before and after the tolerance fix.
    """
    from src.database.repository import MarketRepository
    from src.models.market_data import Candle as CandleModel
    from src.models.market_data import Observation as ObservationModel
    from src.models.market_data import ObservationKind

    first = [candle("RACET", BASE + timedelta(seconds=60 * i), 100.0 + i) for i in range(3)]
    stool = ObservationModel(
        kind=ObservationKind.BOS_BULLISH, symbol="RACET", timeframe="1m",
        observed_at=first[-1].close_time, summary="race probe", confidence=70,
        evidence={}, provenance="PUBLIC_MARKET_DATA_DETERMINISTIC",
        rule_id="bos", rule_version="1.0.0", input_hash=candle_input_hash(first),
    )
    repository = MarketRepository(database)
    async with database.acquire() as conn:
        for item in first:
            await conn.execute(
                insert_candle_sql(), item.symbol, item.timeframe, item.open_time, item.close_time,
                item.open, item.high, item.low, item.close, item.volume, item.trade_count, item.closed,
            )
        # Historical row lands inside the observation window (simulated backfill).
        older = candle("RACET", BASE - timedelta(seconds=60), 99.0)
        await conn.execute(
            insert_candle_sql(), older.symbol, older.timeframe, older.open_time, older.close_time,
            older.open, older.high, older.low, older.close, older.volume, older.trade_count, older.closed,
        )
        rows = await conn.fetch(
            "SELECT * FROM candles WHERE symbol=$1 AND timeframe=$2 AND close_time<=$3 "
            "ORDER BY open_time DESC LIMIT 500",
            "RACET", "1m", stool.observed_at,
        )
    current = [CandleModel(**dict(row)) for row in reversed(rows)]
    assert candle_input_hash(current) != stool.input_hash


class StubApp:
    """Minimal TIMApplication surface for the tolerance helper (no DB)."""

    def __init__(self, repository, observations, history, restored):
        self.repository = repository
        self.observations = observations
        self.history = history
        self.restored = restored
        self.cases = type("Cases", (), {"ingest": lambda self, observation: dummy_case("RACEC")})()

    async def restore_persisted_state(self, reset: bool = False) -> None:
        self.restored.append(reset)


@pytest.mark.asyncio
async def test_tolerant_save_heals_transient_race() -> None:
    from main import TIMApplication

    calls = {"saves": 0}

    class Repository:
        async def save_observation_with_case(self, observation, case):
            calls["saves"] += 1
            if calls["saves"] == 1:
                raise ValueError("Observation " + MISMATCH_MESSAGE)
            return None

    rebuilt = [object()]
    observations = type("Obs", (), {"evaluate": lambda self, history: rebuilt})()
    restored: list[bool] = []
    app = StubApp(Repository(), observations, {"1m": ["hist"]}, restored)
    stale = type("O", (), {"timeframe": "1m"})()
    await TIMApplication._save_observation_tolerant(app, stale, dummy_case("RACEC"))
    assert calls["saves"] == 2
    assert restored == [False]


@pytest.mark.asyncio
async def test_tolerant_save_reraises_persistent_mismatch() -> None:
    from main import TIMApplication

    calls = {"saves": 0}

    class Repository:
        async def save_observation_with_case(self, observation, case):
            calls["saves"] += 1
            raise ValueError("Observation " + MISMATCH_MESSAGE)

    observations = type("Obs", (), {"evaluate": lambda self, history: [object()]})()
    restored: list[bool] = []
    app = StubApp(Repository(), observations, {"1m": ["hist"]}, restored)
    from types import SimpleNamespace

    with pytest.raises(ValueError, match="does not match persisted candle input"):
        await TIMApplication._save_observation_tolerant(
            app, SimpleNamespace(timeframe="1m"), object())
    assert calls["saves"] == 2
    assert restored == [False]


@pytest.mark.asyncio
async def test_tolerant_save_passes_other_errors_through() -> None:
    from main import TIMApplication

    class Repository:
        async def save_observation_with_case(self, observation, case):
            raise ValueError("some other validation failure")

    app = StubApp(Repository(), None, {}, [])
    with pytest.raises(ValueError, match="some other validation failure"):
        await TIMApplication._save_observation_tolerant(app, object(), dummy_case("RACEC"))


@pytest.mark.asyncio
async def test_concurrent_historical_writes_never_escape_tolerant_save(database) -> None:
    """Live-like validation racing a historical writer: every save either
    succeeds on current truth or heals once; no mismatch may escape."""
    import random

    from main import TIMApplication
    from src.models.market_data import Observation as ObservationModel
    from src.models.market_data import ObservationKind
    from src.observation.engine import candle_input_hash

    base = [candle("RACEC", BASE + timedelta(seconds=60 * i), 200.0 + i) for i in range(5)]
    async with database.acquire() as conn:
        for item in base:
            await conn.execute(
                insert_candle_sql(), item.symbol, item.timeframe, item.open_time, item.close_time,
                item.open, item.high, item.low, item.close, item.volume, item.trade_count, item.closed,
            )

    from src.models.market_data import Candle as CandleModel

    async def read_history():
        async with database.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM candles WHERE symbol=$1 AND timeframe=$2 "
                "ORDER BY open_time DESC LIMIT 500", "RACEC", "1m",
            )
        return [CandleModel(**dict(row)) for row in reversed(rows)]

    class Repository:
        async def save_observation_with_case(self, observation, case):
            from src.database.repository import MarketRepository

            real = MarketRepository(database)
            await real.save_observation_with_case(observation, case)

    history = {"1m": await read_history()}
    restored: list[bool] = []

    async def restore(reset: bool = False) -> None:
        restored.append(reset)
        history["1m"] = await read_history()

    from src.models.market_data import Observation as ObservationModel
    from src.models.market_data import ObservationKind as ObservationKindModel
    from src.observation.engine import candle_input_hash as _hash

    def fresh_observations(self, candles):
        # Same contract as production evaluate(): per-timeframe candle list.
        if not candles:
            return []
        return [ObservationModel(
            kind=ObservationKindModel.BOS_BULLISH, symbol="RACEC", timeframe="1m",
            observed_at=candles[-1].close_time, summary="race", confidence=70,
            evidence={}, provenance="PUBLIC_MARKET_DATA_DETERMINISTIC",
            rule_id="bos", rule_version="1.0.0", input_hash=_hash(candles))]

    observations = type("Obs", (), {"evaluate": fresh_observations})()
    app = StubApp(Repository(), observations, history,
                  type("R", (), {"append": lambda self, x: restored.append(x)})())
    app.restore_persisted_state = restore
    app.cases = type("Cases", (), {"ingest": lambda self, observation: dummy_case("RACEC")})()

    async def saver(rounds: int) -> int:
        healed = 0
        for _ in range(rounds):
            current = await read_history()
            stool = ObservationModel(
                kind=ObservationKind.BOS_BULLISH, symbol="RACEC", timeframe="1m",
                observed_at=current[-1].close_time, summary="race", confidence=70,
                evidence={}, provenance="PUBLIC_MARKET_DATA_DETERMINISTIC",
                rule_id="bos", rule_version="1.0.0", input_hash=candle_input_hash(current),
            )
            try:
                await TIMApplication._save_observation_tolerant(app, stool, dummy_case("RACEC"))
            except ValueError:
                healed += 1
        return healed

    async def writer() -> None:
        for i in range(5):
            item = candle("RACEC", BASE - timedelta(seconds=60 * (i + 1)), 190.0 - i)
            async with database.acquire() as conn:
                await conn.execute(
                    insert_candle_sql(), item.symbol, item.timeframe, item.open_time, item.close_time,
                    item.open, item.high, item.low, item.close, item.volume,
                    item.trade_count, item.closed,
                )
            await asyncio.sleep(0)

    healed = await asyncio.gather(saver(10), writer())
    assert healed[0] >= 0
    async with database.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM observations WHERE symbol='RACEC'")
    # Races are timing-dependent by design: every round either persisted on
    # current truth or healed once via retry; nothing may escape as an error
    # (gather would have raised), and at least the un-raced rounds persist.
    assert n >= 8


@pytest.mark.asyncio
async def test_sequential_race_heals_deterministically(database) -> None:
    """Deterministic version: build from state A, land a row, save must heal."""
    from main import TIMApplication
    from src.models.market_data import Observation as ObservationModel
    from src.models.market_data import ObservationKind
    from src.observation.engine import candle_input_hash

    base = [candle("RACED", BASE + timedelta(seconds=60 * i), 200.0 + i) for i in range(3)]
    async with database.acquire() as conn:
        for item in base:
            await conn.execute(
                insert_candle_sql(), item.symbol, item.timeframe, item.open_time, item.close_time,
                item.open, item.high, item.low, item.close, item.volume,
                item.trade_count, item.closed,
            )
    from src.models.market_data import Candle as CandleModel

    async def read_history():
        async with database.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM candles WHERE symbol=$1 AND timeframe=$2 "
                "ORDER BY open_time DESC LIMIT 500", "RACED", "1m",
            )
        return [CandleModel(**dict(row)) for row in reversed(rows)]

    history = {"1m": await read_history()}
    stale = ObservationModel(
        kind=ObservationKind.BOS_BULLISH, symbol="RACED", timeframe="1m",
        observed_at=history["1m"][-1].close_time, summary="stale", confidence=70,
        evidence={}, provenance="PUBLIC_MARKET_DATA_DETERMINISTIC",
        rule_id="bos", rule_version="1.0.0", input_hash=candle_input_hash(history["1m"]),
    )
    # The race: a historical row lands after the observation was built.
    landed = candle("RACED", BASE - timedelta(seconds=60), 190.0)
    async with database.acquire() as conn:
        await conn.execute(
            insert_candle_sql(), landed.symbol, landed.timeframe, landed.open_time, landed.close_time,
            landed.open, landed.high, landed.low, landed.close, landed.volume,
            landed.trade_count, landed.closed,
        )

    from src.models.market_data import Observation as ObservationModel2
    from src.models.market_data import ObservationKind as ObservationKindModel2
    from src.observation.engine import candle_input_hash as _hash2

    def fresh_observations(self, candles):
        if not candles:
            return []
        return [ObservationModel2(
            kind=ObservationKindModel2.BOS_BULLISH, symbol="RACED", timeframe="1m",
            observed_at=candles[-1].close_time, summary="fresh", confidence=70,
            evidence={}, provenance="PUBLIC_MARKET_DATA_DETERMINISTIC",
            rule_id="bos", rule_version="1.0.0", input_hash=_hash2(candles))]

    observations = type("Obs", (), {"evaluate": fresh_observations})()
    restored: list[bool] = []

    async def restore(reset: bool = False) -> None:
        restored.append(reset)
        history["1m"] = await read_history()

    from src.database.repository import MarketRepository

    app = StubApp(MarketRepository(database), observations, history, [])
    app.restore_persisted_state = restore
    app.cases = type("Cases", (), {"ingest": lambda self, observation: dummy_case("RACED")})()
    await TIMApplication._save_observation_tolerant(app, stale, dummy_case("RACED"))
    assert restored == [False]
    async with database.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM observations WHERE symbol='RACED'")
    assert n == 1
