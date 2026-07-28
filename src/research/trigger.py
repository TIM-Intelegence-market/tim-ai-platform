from __future__ import annotations

import hashlib,json,os
from dataclasses import asdict,dataclass,is_dataclass
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

from src.models.market_data import Observation
from src.research.router import ResearchRouter


@dataclass(frozen=True,slots=True)
class TriggerResult:
    observation_id:str;pattern:str;research_type:str;urgency:str;module:str
    artifact_id:str;triggered_at:str;status:str="COMPLETED"


class ResearchTrigger:
    """Idempotent observation-to-research bridge."""
    TRIGGER_PATTERNS={
        "BOS_BEARISH":{"type":"quick","urgency":"critical"},
        "FAILED_CONTINUATION":{"type":"quick","urgency":"normal"},
        "WEAK_CONTINUATION":{"type":"pattern","urgency":"normal"},
        "NEW_HIGH":{"type":"deep","urgency":"background"},
    }
    def __init__(self,router:ResearchRouter|None=None,*,state_path:Path=Path("data/research/trigger_state.json"),log_path:Path=Path("data/research/trigger_events.jsonl"))->None:
        self.router=router or ResearchRouter();self.state_path=state_path;self.log_path=log_path;self.processed=self._load()

    def _load(self)->set[str]:
        try:
            value=json.loads(self.state_path.read_text());return {str(item) for item in value.get("processed",[]) }
        except (OSError,ValueError,TypeError):return set()

    async def handle(self,observation:Observation|dict[str,Any])->TriggerResult|None:
        isolation=self.state_path.parent/"isolation.json"
        if isolation.exists():return None
        row=observation.to_dict() if isinstance(observation,Observation) else dict(observation);pattern=str(row.get("kind") or row.get("type") or "").upper();config=self.TRIGGER_PATTERNS.get(pattern)
        if config is None:return None
        observation_id=str(row.get("observation_id") or row.get("id") or "").strip()
        if not observation_id:raise ValueError("trigger observation requires an id")
        identity=hashlib.sha256(f"{observation_id}:{pattern}:{config['type']}".encode()).hexdigest()
        if identity in self.processed:return None
        evidence=[{"source":row.get("source","TIM_DATABASE"),"provenance":row.get("provenance",""),"observed_at":row.get("observed_at"),"summary":row.get("summary") or row.get("details") or pattern,"observation_id":observation_id}]
        if not evidence[0]["provenance"]:raise ValueError("trigger evidence requires provenance")
        routed=await self.router.aroute(f"BTCUSDT {pattern}: {evidence[0]['summary']}",evidence,requested_type=config["type"],urgency=config["urgency"],context={"symbol":row.get("symbol","BTCUSDT"),"timeframe":row.get("timeframe","not supplied")})
        payload=routed["result"]
        if is_dataclass(payload):artifact_id=str(getattr(payload,"research_id",""))
        else:artifact_id=str(payload.get("report_id") or payload.get("research_id") or payload.get("input_hash") or "")
        result=TriggerResult(observation_id,pattern,config["type"],config["urgency"],routed["module"],artifact_id,datetime.now(timezone.utc).isoformat())
        self.processed.add(identity);self._persist();self._log(result);return result

    async def check_and_trigger(self,observations:list[Observation|dict[str,Any]])->list[TriggerResult]:
        output=[]
        for observation in observations:
            result=await self.handle(observation)
            if result is not None:output.append(result)
        return output

    def _persist(self)->None:
        self.state_path.parent.mkdir(parents=True,exist_ok=True);temp=self.state_path.with_suffix(".tmp");temp.write_text(json.dumps({"processed":sorted(self.processed),"updated_at":datetime.now(timezone.utc).isoformat()},indent=2)+"\n");os.replace(temp,self.state_path)

    def _log(self,result:TriggerResult)->None:
        self.log_path.parent.mkdir(parents=True,exist_ok=True)
        with self.log_path.open("a") as handle:handle.write(json.dumps(asdict(result),sort_keys=True)+"\n");handle.flush();os.fsync(handle.fileno())
