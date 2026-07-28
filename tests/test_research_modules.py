from datetime import datetime,timezone
from uuid import UUID

import pytest

from src.research.config import ResearchConfig
from src.research.module_a.agent import LocalResearchAgent,ModuleAResearchAgent
from src.research.module_a.tools import ExternalSearchDisabled,duckduckgo_search
from src.research.router import ResearchRouter,ResearchType,deep_research,quick_research
from src.research.module_a.prompts import PLANNER_PROMPT,REFLECTION_PROMPT
from src.research.module_b.agent import ModuleBResearchAgent,run_deep_research
from src.research.trigger import ResearchTrigger


def test_module_a_is_deterministic_and_deduplicates_cache(tmp_path):
    config=ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports");agent=LocalResearchAgent(config);now=datetime(2026,1,1,tzinfo=timezone.utc);evidence=[{"summary":"Repeated rejection","source":"TIM_DATABASE","provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC"}]
    first=agent.analyze("What repeated?",evidence,created_at=now);second=agent.analyze("What repeated?",evidence,created_at=now)
    assert first==second
    assert len(config.cache_path.read_text().splitlines())==1
    assert first.mode=="OBSERVE" and first.patterns==["rejection"]


def test_external_search_is_closed_by_default():
    with pytest.raises(ExternalSearchDisabled):duckduckgo_search("BTC")


def test_module_a_normalizes_database_identifiers(tmp_path):
    agent=LocalResearchAgent(ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports"))
    result=agent.analyze("id",[{"observation_id":UUID("00000000-0000-0000-0000-000000000001")}])
    assert result.citations


def test_router_refuses_deep_module_without_authorization(tmp_path):
    router=ResearchRouter(ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports"))
    assert router.select("urgent",urgency="critical")==ResearchType.QUICK
    assert router.select("deep",depth_required=True)==ResearchType.DEEP
    with pytest.raises(ValueError,match="unknown"):router.select("report",requested_type="unknown")


def test_finance_prompts_format_as_valid_json_instructions():
    planner=PLANNER_PROMPT.format(topic="structure",candles_count=50,observations=20,iteration=0)
    reflection=REFLECTION_PROMPT.format(summary="documented",topic="structure")
    assert '"queries"' in planner and "BOS" in planner and "keine Websuche" in planner
    assert '"confidence"' in reflection and "Provenance" in reflection


@pytest.mark.asyncio
async def test_async_module_a_uses_only_injected_tim_data(tmp_path):
    class Repository:
        async def recent_candles(self,*args):return []
        async def recent_observations(self,*args):return []
    agent=ModuleAResearchAgent(Repository(),config=ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports"))
    result=await agent.research("BTC structure")
    assert result["module"]=="A" and result["mode"]=="OBSERVE"
    assert result["external_search_used"] is False
    assert result["gaps_remaining"]==["No evidence supplied"]


@pytest.mark.asyncio
async def test_module_b_writes_cited_local_report(tmp_path):
    context={"symbol":"BTCUSDT","timeframe":"5m","evidence":[{"source":"TIM_DATABASE","provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC","observed_at":"2026-01-01T00:00:00Z","summary":"Documented rejection"}]}
    result=await run_deep_research("Review documented structure",context,reports_dir=tmp_path)
    assert result["mode"]=="OBSERVE" and result["report_source"]=="local" and result["sources"]==1
    report=(tmp_path/f"{result['report_id']}_research_report.md").read_text()
    assert "Documented rejection" in report and "TIM_DATABASE" in report


def test_module_b_rejects_web_and_uncited_evidence(tmp_path):
    with pytest.raises(ValueError,match="local"):ModuleBResearchAgent("query",report_source="web",reports_dir=tmp_path)
    agent=ModuleBResearchAgent("query",reports_dir=tmp_path)
    with pytest.raises(ValueError,match="source and provenance"):
        import asyncio
        asyncio.run(agent.generate_report({"evidence":[{"summary":"uncited"}]}))


def test_router_executes_quick_and_deep_with_explicit_evidence(tmp_path):
    config=ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports");evidence=[{"source":"TIM_DATABASE","provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC","summary":"Documented rejection"}]
    quick=quick_research("review",evidence,config=config);deep=deep_research("report",evidence,config=config)
    assert quick["module"]=="A" and quick["selected_type"]=="quick"
    assert deep["module"]=="B" and deep["selected_type"]=="deep"


@pytest.mark.asyncio
async def test_sync_router_rejects_running_event_loop(tmp_path):
    router=ResearchRouter(ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports"))
    with pytest.raises(RuntimeError,match="aroute"):router.route("review",[])
    result=await router.aroute("review",[])
    assert result["module"]=="A"


def test_capabilities_are_truthful():
    capabilities=ResearchRouter.get_capabilities()
    assert capabilities["module_a"]["external_search"] is False
    assert capabilities["module_b"]["multi_agent"] is False


@pytest.mark.asyncio
async def test_trigger_is_idempotent_and_persists_audit(tmp_path):
    config=ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports");trigger=ResearchTrigger(ResearchRouter(config),state_path=tmp_path/"state.json",log_path=tmp_path/"events.jsonl")
    observation={"id":"obs-1","type":"FAILED_CONTINUATION","symbol":"BTCUSDT","timeframe":"5m","details":"documented failure","source":"TIM_DATABASE","provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC"}
    first=await trigger.handle(observation);second=await trigger.handle(observation)
    assert first is not None and first.module=="A" and second is None
    assert len((tmp_path/"events.jsonl").read_text().splitlines())==1
    restored=ResearchTrigger(ResearchRouter(config),state_path=tmp_path/"state.json",log_path=tmp_path/"events.jsonl")
    assert await restored.handle(observation) is None


@pytest.mark.asyncio
async def test_trigger_ignores_unconfigured_pattern(tmp_path):
    trigger=ResearchTrigger(ResearchRouter(ResearchConfig(cache_path=tmp_path/"cache",report_root=tmp_path/"reports")),state_path=tmp_path/"state.json",log_path=tmp_path/"events.jsonl")
    assert await trigger.handle({"id":"obs-2","type":"REJECTION"}) is None
