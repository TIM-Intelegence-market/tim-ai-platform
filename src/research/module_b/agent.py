from __future__ import annotations

import hashlib,json,os,re
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

from src.research.module_b.config import ModuleBConfig


ALLOWED_REPORT_TYPES={"research_report","deep"}
ALLOWED_SOURCES={"local"}
ALLOWED_TONES={"analytical","formal","conversational"}
REPORT_SCHEMA_VERSION="1.0.0"
REPORT_GENERATOR_VERSION="1.0.0"


@dataclass(frozen=True,slots=True)
class ReportMetadata:
    report_id:str;query:str;report_type:str;report_source:str;tone:str
    sources:int;word_count:int;file:str;metadata_file:str;timestamp:str
    provenance:str;module:str;mode:str;input_hash:str;artifact_hash:str
    schema_version:str;generator_version:str


class ReportResearchAgent:
    """Local, citation-preserving Module B report generator.

    GPT Researcher and web retrieval remain unavailable until an explicit
    source policy is configured. Construction never mutates process secrets.
    """
    def __init__(self,query:str|None=None,report_type:str="research_report",report_source:str="local",tone:str="analytical",doc_path:str|None=None,*,config:ModuleBConfig|None=None,reports_dir:Path|None=None)->None:
        self.query=(query or "").strip();self.report_type=report_type;self.report_source=report_source;self.tone=tone;self.doc_path=doc_path;self.config=config or ModuleBConfig();self.reports_dir=reports_dir or Path("data/research/module_b_reports")
        if not self.query:raise ValueError("query is required")
        if report_type not in ALLOWED_REPORT_TYPES:raise ValueError("unsupported report_type")
        if report_source not in ALLOWED_SOURCES:raise ValueError("only the local report source is authorized")
        if tone not in ALLOWED_TONES:raise ValueError("unsupported tone")

    async def generate_report(self,context:dict[str,Any]|None=None,*,created_at:datetime|None=None)->dict[str,Any]:
        context=context or {};evidence=context.get("evidence",[])
        if not isinstance(evidence,list):raise ValueError("context.evidence must be a list")
        normalized=[self._evidence(item,index) for index,item in enumerate(evidence)]
        payload=json.dumps({"query":self.query,"context":context,"report_type":self.report_type,"tone":self.tone},sort_keys=True,default=str,separators=(",",":"));digest=hashlib.sha256(payload.encode()).hexdigest();report_id=f"tim-b-{digest[:16]}";now=created_at or datetime.now(timezone.utc)
        report=self._markdown(normalized,context);self.reports_dir.mkdir(parents=True,exist_ok=True);filename=f"{report_id}_{self.report_type}.md";path=self.reports_dir/filename;meta_path=self.reports_dir/f"{filename}.json"
        self._atomic_write(path,report)
        metadata=ReportMetadata(report_id=report_id,query=self.query,report_type=self.report_type,report_source="local",tone=self.tone,sources=len(normalized),word_count=len(report.split()),file=str(path),metadata_file=str(meta_path),timestamp=now.isoformat(),provenance="TIM_LOCAL_EVIDENCE_DETERMINISTIC",module="B",mode="OBSERVE",input_hash=digest,artifact_hash=hashlib.sha256(report.encode()).hexdigest(),schema_version=REPORT_SCHEMA_VERSION,generator_version=REPORT_GENERATOR_VERSION)
        self._atomic_write(meta_path,json.dumps(asdict(metadata),indent=2,sort_keys=True)+"\n");return asdict(metadata)

    def _evidence(self,item:Any,index:int)->dict[str,Any]:
        if not isinstance(item,dict):raise ValueError(f"evidence[{index}] must be an object")
        source=str(item.get("source","")).strip();provenance=str(item.get("provenance","")).strip()
        if not source or not provenance:raise ValueError(f"evidence[{index}] requires source and provenance")
        return {"index":index+1,"source":source,"provenance":provenance,"timestamp":item.get("timestamp") or item.get("observed_at") or item.get("open_time"),"content":str(item.get("content") or item.get("summary") or "").strip()}

    def _markdown(self,evidence:list[dict[str,Any]],context:dict[str,Any])->str:
        findings="\n".join(f"- [{item['index']}] {item['content'] or 'No textual content supplied'}" for item in evidence) or "- No evidence supplied."
        citations="\n".join(f"[{item['index']}]: {item['source']} | {item['timestamp'] or 'timestamp unavailable'} | {item['provenance']}" for item in evidence) or "No citations available."
        limitations=[]
        if len(evidence)<3:limitations.append("Fewer than three cited evidence records were supplied.")
        if not evidence:limitations.append("No evidence-backed conclusion can be produced.")
        return f"""# TIM Research Report

## Research Question
{self.query}

## Executive Summary
This OBSERVE-only report organizes {len(evidence)} explicitly supplied TIM evidence records. It does not perform web research or produce trading instructions.

## Evidence Review
{findings}

## Market Context
Symbol: {context.get('symbol','not supplied')}  
Timeframe: {context.get('timeframe','not supplied')}

## Limitations and Missing Evidence
{chr(10).join(f'- {item}' for item in limitations) or '- No structural limitation detected beyond the supplied evidence scope.'}

## Citations
{citations}

## Compliance
Mode: OBSERVE. No orders, execution, position sizing, targets, or recommendations.
"""

    @staticmethod
    def _atomic_write(path:Path,content:str)->None:
        temp=path.with_suffix(path.suffix+".tmp");temp.write_text(content,encoding="utf-8");os.replace(temp,path)

    @classmethod
    def get_recent_reports(cls,limit:int=10,*,reports_dir:Path|None=None)->list[dict[str,Any]]:
        root=reports_dir or Path("data/research/module_b_reports");output=[]
        for path in sorted(root.glob("*.md.json"),key=lambda item:item.stat().st_mtime,reverse=True)[:max(0,min(limit,100))]:
            try:
                value=json.loads(path.read_text());
                if isinstance(value,dict):output.append(value)
            except (OSError,ValueError):continue
        return output


ModuleBResearchAgent=ReportResearchAgent


async def run_deep_research(topic:str,context:dict[str,Any]|None=None,output_format:str="markdown",*,reports_dir:Path|None=None,report_type:str="research_report")->dict[str,Any]:
    if output_format!="markdown":raise ValueError("Only markdown is currently supported; PDF/DOCX require explicit export")
    return await ReportResearchAgent(query=topic,report_type=report_type,report_source="local",tone="analytical",reports_dir=reports_dir).generate_report(context)
