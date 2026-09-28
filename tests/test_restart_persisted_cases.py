from datetime import datetime,timedelta,timezone

import pytest

from main import TIMApplication
from src.dashboard.app import DashboardState
from src.memory.market_memory import MarketMemory
from src.observation.engine import ObservationEngine
from src.research.case_engine import ResearchCase,ResearchCaseEngine
from src.data_ingestion.aggregator import CandleAggregator
from src.models.market_data import Candle,Trade


class PersistedRepository:
    def __init__(self,case):self.case=case
    async def recent_candles(self,*args):return []
    async def recent_observations(self,*args):return []
    async def recent_research_cases(self,*args):return [self.case]


@pytest.mark.asyncio
async def test_restart_dashboard_uses_persisted_case_without_reconstruction():
    at=datetime(2026,7,20,tzinfo=timezone.utc)
    case=ResearchCase("case_persisted","BTCUSDT","1m",at,at,status="CLOSED",outcome="documented",documentation="Persisted trigger/module/artifact documentation")
    app=TIMApplication.__new__(TIMApplication);app.repository=PersistedRepository(case);app.history={"1m":[],"5m":[],"15m":[],"1h":[]};app.memory=MarketMemory();app.cases=ResearchCaseEngine();app.observations=ObservationEngine();app.dashboard_state=DashboardState()
    await app.restore_persisted_state()
    assert app.dashboard_state.research_cases==[case.to_dict()]
    assert app.cases.cases[case.case_id].status=="CLOSED"
    assert app.cases.cases[case.case_id].documentation=="Persisted trigger/module/artifact documentation"


class RecoveryRepository(PersistedRepository):
    def __init__(self,case,candles,trades):
        super().__init__(case);self.candles=candles;self.trades=trades;self.recovered=[];self.recovery_since=None
    async def recent_candles(self,_symbol,timeframe,_limit):return list(self.candles.get(timeframe,[]))
    async def agg_trades_since(self,_symbol,since):self.recovery_since=since;return list(self.trades)
    async def upsert_candle(self,candle):self.recovered.append(candle)


@pytest.mark.asyncio
async def test_restart_replays_from_persisted_boundary_and_flushes_raw_bucket():
    at=datetime(2026,7,20,12,tzinfo=timezone.utc)
    case=ResearchCase("case_persisted","BTCUSDT","1m",at,at,status="CLOSED",outcome="documented")
    persisted=Candle("BTCUSDT","1m",at,at+timedelta(minutes=1),100,100,100,100,1,1)
    trades=[
        Trade("BTCUSDT",101,1,at+timedelta(minutes=1,seconds=10),1,False),
        Trade("BTCUSDT",102,1,at+timedelta(minutes=2,seconds=1),2,False),
    ]
    repo=RecoveryRepository(case,{"1m":[persisted]},trades)
    app=TIMApplication.__new__(TIMApplication);app.repository=repo;app.aggregator=CandleAggregator(("1m",));app.history={"1m":[]};app.memory=MarketMemory();app.cases=ResearchCaseEngine();app.observations=ObservationEngine();app.dashboard_state=DashboardState()
    await app.restore_persisted_state()
    assert repo.recovery_since==at
    assert [(item.open_time,item.close,item.trade_count) for item in repo.recovered]==[(at+timedelta(minutes=1),101,1)]
