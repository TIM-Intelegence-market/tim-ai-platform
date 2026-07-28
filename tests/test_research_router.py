from src.research.router import ResearchRouter,ResearchType
import pytest


def test_router_policy_and_capabilities()->None:
    router=ResearchRouter()
    assert router.select("urgent",urgency="critical")==ResearchType.QUICK
    assert router.select("background",depth_required=True)==ResearchType.DEEP
    capabilities=router.get_capabilities()
    assert capabilities["module_a"]["external_search"] is False
    assert capabilities["module_b"]["multi_agent"] is False


@pytest.mark.asyncio
async def test_router_falls_back_to_module_a(monkeypatch,tmp_path)->None:
    import src.research.router as module
    async def broken(*args,**kwargs):raise OSError("unavailable")
    monkeypatch.setattr(module,"run_deep_research",broken)
    from src.research.config import ResearchConfig
    router=ResearchRouter(ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports"))
    result=await router.aroute("deep review",[],requested_type="deep")
    assert result["module"]=="A" and result["fallback"] is True
