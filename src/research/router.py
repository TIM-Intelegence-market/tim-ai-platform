from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any

from src.research.config import ResearchConfig,research_config
from src.research.module_a.agent import LocalResearchAgent
from src.research.module_b.agent import run_deep_research


class ResearchType(StrEnum):
    QUICK="quick";DEEP="deep";PATTERN="pattern";REPORT="report"


class ResearchRouter:
    """Deterministic router. It never enables sources or models implicitly."""
    MAX_WORDS_QUICK=500;MAX_WORDS_DEEP=2000;TIMEOUT_QUICK=60;TIMEOUT_DEEP=300
    def __init__(self,config:ResearchConfig=research_config)->None:self.config=config;self.module_a=LocalResearchAgent(config)

    def select(self,query:str,requested_type:str|None=None,urgency:str="normal",depth_required:bool=False)->ResearchType:
        if not query or not query.strip():raise ValueError("query is required")
        if urgency not in {"critical","normal","background"}:raise ValueError("unsupported urgency")
        if requested_type:
            try:return ResearchType(requested_type)
            except ValueError as exc:raise ValueError(f"unknown research type: {requested_type}") from exc
        if urgency=="critical":return ResearchType.QUICK
        if depth_required or len(query)>200:return ResearchType.DEEP
        return ResearchType.QUICK

    async def aroute(self,query:str,evidence:list[dict[str,Any]],*,requested_type:str|None=None,urgency:str="normal",depth_required:bool=False,context:dict[str,Any]|None=None)->dict[str,Any]:
        selected=self.select(query,requested_type,urgency,depth_required)
        if selected in {ResearchType.QUICK,ResearchType.PATTERN}:
            result=self.module_a.analyze(query,evidence)
            return {"selected_type":selected.value,"module":"A","result":result}
        local_context={**(context or {}),"evidence":evidence}
        try:
            result=await asyncio.wait_for(run_deep_research(query,local_context,reports_dir=self.config.report_root,report_type="deep" if selected==ResearchType.DEEP else "research_report"),timeout=self.TIMEOUT_DEEP)
            return {"selected_type":selected.value,"module":"B","result":result,"fallback":False}
        except (OSError,ValueError,TypeError,TimeoutError):
            fallback=self.module_a.analyze(query,evidence)
            return {"selected_type":selected.value,"module":"A","result":fallback,"fallback":True,"fallback_reason":"module_b_unavailable"}

    def route(self,query:str,evidence:list[dict[str,Any]],*,requested_type:str|None=None,urgency:str="normal",depth_required:bool=False,deep:bool|None=None,context:dict[str,Any]|None=None)->Any:
        """Synchronous boundary for CLI callers; async applications use aroute."""
        if deep is not None:depth_required=deep
        try:asyncio.get_running_loop()
        except RuntimeError:return asyncio.run(self.aroute(query,evidence,requested_type=requested_type,urgency=urgency,depth_required=depth_required,context=context))
        raise RuntimeError("route() cannot run inside an event loop; await aroute()")

    @staticmethod
    def get_capabilities()->dict[str,Any]:
        return {
            "module_a":{"name":"TIM Local Research","available":True,"strengths":["fast","deterministic","patterns","read-only"],"use_cases":["pattern validation","TIM evidence review","TA correlation"],"timeout_seconds":60,"model":"deterministic core; optional qwen2.5:7b","external_search":False},
            "module_b":{"name":"TIM Local Cited Reports","available":True,"strengths":["cited","reproducible","markdown","local evidence"],"use_cases":["market reports","evidence audits","documented reviews"],"timeout_seconds":300,"model":"deterministic report renderer","external_search":False,"multi_agent":False},
        }


def quick_research(query:str,evidence:list[dict[str,Any]],*,config:ResearchConfig=research_config)->dict[str,Any]:
    return ResearchRouter(config).route(query,evidence,requested_type="quick")


def deep_research(query:str,evidence:list[dict[str,Any]],*,context:dict[str,Any]|None=None,config:ResearchConfig=research_config)->dict[str,Any]:
    return ResearchRouter(config).route(query,evidence,requested_type="deep",context=context)
