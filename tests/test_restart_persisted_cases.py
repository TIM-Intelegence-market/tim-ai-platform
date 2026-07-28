from datetime import datetime,timezone

import pytest

from main import TIMApplication
from src.dashboard.app import DashboardState
from src.memory.market_memory import MarketMemory
from src.observation.engine import ObservationEngine
from src.research.case_engine import ResearchCase,ResearchCaseEngine


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
