from __future__ import annotations

import hashlib,json,os
from dataclasses import asdict,dataclass,is_dataclass
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

from src.research.config import ResearchConfig,research_config
from src.research.module_a.prompts import PLANNER_PROMPT,REFLECTION_PROMPT


def _plain(value:Any)->Any:
    if is_dataclass(value):return _plain(asdict(value))
    if isinstance(value,dict):return {str(k):_plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_plain(v) for v in value]
    if isinstance(value,datetime):return value.isoformat()
    if value is None or isinstance(value,(str,int,float,bool)):return value
    return str(value)


@dataclass(frozen=True,slots=True)
class ResearchResult:
    research_id:str;created_at:str;module:str;mode:str;question:str;summary:str
    patterns:list[str];missing_evidence:list[str];citations:list[dict];provenance:str;input_hash:str


class LocalResearchAgent:
    """Deterministic local researcher. No network, LLM, or database writes."""
    def __init__(self,config:ResearchConfig=research_config)->None:self.config=config

    def analyze(self,question:str,evidence:list[dict[str,Any]],*,created_at:datetime|None=None)->ResearchResult:
        clean=_plain(evidence);payload=json.dumps({"question":question.strip(),"evidence":clean},sort_keys=True,separators=(",",":"));digest=hashlib.sha256(payload.encode()).hexdigest()
        concepts=[]
        text=json.dumps(clean,sort_keys=True).lower()
        for concept in ("break of structure","rejection","failed continuation","conflict","absorption"):
            if concept in text:concepts.append(concept)
        citations=[{"index":i,"source":item.get("source","TIM_DATABASE"),"timestamp":item.get("observed_at") or item.get("open_time"),"provenance":item.get("provenance",self.config.provenance)} for i,item in enumerate(clean) if isinstance(item,dict)]
        result=ResearchResult(research_id=f"tim-a-{digest[:16]}",created_at=(created_at or datetime.now(timezone.utc)).isoformat(),module="A",mode="OBSERVE",question=question.strip(),summary=f"Deterministic review of {len(clean)} supplied evidence records.",patterns=concepts,missing_evidence=[] if clean else ["No evidence supplied"],citations=citations,provenance=self.config.provenance,input_hash=digest)
        self._cache(result);return result

    def _cache(self,result:ResearchResult)->None:
        path=self.config.cache_path;path.parent.mkdir(parents=True,exist_ok=True);row=json.dumps(asdict(result),sort_keys=True)
        existing=set()
        try:existing={json.loads(line).get("input_hash") for line in path.read_text().splitlines() if line.strip()}
        except (OSError,ValueError):pass
        if result.input_hash in existing:return
        with path.open("a") as handle:handle.write(row+"\n");handle.flush();os.fsync(handle.fileno())


class ModuleAResearchAgent:
    """Async TIM-data workflow with optional local Ollama planning.

    No singleton is created: callers must inject the read-only repository and
    explicitly opt into an LLM client or external source policy.
    """
    def __init__(self,repository:Any,*,llm:Any|None=None,config:ResearchConfig=research_config,max_loops:int=3)->None:
        if max_loops<1 or max_loops>5:raise ValueError("max_loops must be between 1 and 5")
        self.repository=repository;self.llm=llm;self.config=config;self.max_loops=max_loops;self.local=LocalResearchAgent(config)

    async def _json(self,prompt:str,fallback:dict)->dict:
        if self.llm is None:return fallback
        try:
            value=await self.llm.generate_json(prompt)
            return value if isinstance(value,dict) else fallback
        except (OSError,ValueError,TypeError,TimeoutError):return fallback

    async def research(self,topic:str,*,symbol:str="BTCUSDT",timeframe:str="5m") -> dict[str,Any]:
        candles=await self.repository.recent_candles(symbol,timeframe,50);observations=await self.repository.recent_observations(symbol,20)
        candle_rows=[_plain(c) for c in candles];observation_rows=[_plain(o) for o in observations]
        evidence=[{"kind":"candle",**row} for row in candle_rows]+[{"kind":"observation",**row} for row in observation_rows]
        queries=[];gaps=[];iteration=0
        while iteration<self.max_loops:
            plan=await self._json(PLANNER_PROMPT.format(topic=topic,candles_count=len(candle_rows),observations=len(observation_rows),iteration=iteration),{"queries":[topic]})
            queries=[str(q) for q in plan.get("queries",[]) if str(q).strip()][:5] or [topic];iteration+=1
            deterministic=self.local.analyze(topic,evidence)
            reflection=await self._json(REFLECTION_PROMPT.format(topic=topic,summary=deterministic.summary),{"gaps":deterministic.missing_evidence})
            gaps=[str(g) for g in reflection.get("gaps",[]) if str(g).strip()][:10]
            if not gaps:break
        return {"topic":topic,"summary":deterministic.summary,"patterns":deterministic.patterns,"sources":deterministic.citations,"queries":queries,"iterations":iteration,"gaps_remaining":gaps,"timestamp":deterministic.created_at,"provenance":deterministic.provenance,"module":"A","mode":"OBSERVE","external_search_used":False,"input_hash":deterministic.input_hash}
