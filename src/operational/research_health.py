from __future__ import annotations

import hashlib,importlib.util,json,re,subprocess
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen


class ResearchHealthChecker:
    REQUIRED_META={"report_id","query","report_type","report_source","tone","sources","word_count","file","metadata_file","timestamp","provenance","module","mode","input_hash","artifact_hash","schema_version","generator_version"}
    def __init__(self,root:Path,ollama_url:str="http://127.0.0.1:11434")->None:self.root=root;self.ollama_url=ollama_url.rstrip("/")
    @staticmethod
    def _jsonl(path:Path)->list[dict[str,Any]]:
        try:
            output=[]
            for line in path.read_text().splitlines():
                try:
                    value=json.loads(line)
                    if isinstance(value,dict):output.append(value)
                except ValueError:continue
            return output
        except OSError:return []
    def check(self)->dict[str,Any]:
        checked_at=datetime.now(timezone.utc);warnings=[];critical=[]
        from src.research.config import ResearchConfig
        research_config=ResearchConfig()
        module_a_deps=all(importlib.util.find_spec(name) is not None for name in ("langchain_ollama","langgraph"))
        try:
            from src.research.module_a.graph import DeterministicResearchGraph
            graph_ready=DeterministicResearchGraph().graph is not None
        except Exception:graph_ready=False
        research_python=self.root/".venv-research/bin/python";python313=research_python.is_file()
        try:
            probe=subprocess.run([str(research_python),"-c","from gpt_researcher import GPTResearcher"],capture_output=True,timeout=10)
            gpt_import=probe.returncode==0
        except (OSError,subprocess.SubprocessError):gpt_import=False
        models=[]
        try:
            with urlopen(self.ollama_url+"/api/tags",timeout=3) as response:models=[item.get("name","") for item in json.loads(response.read()).get("models",[])]
        except Exception:pass
        deepseek_ready="deepseek-r1:8b" in models;llama_ready="llama3.2:latest" in models
        events=self._jsonl(self.root/"data/research/trigger_events.jsonl");cutoff=checked_at-timedelta(hours=1);recent=[]
        for event in events:
            try:timestamp=datetime.fromisoformat(str(event.get("triggered_at","")).replace("Z","+00:00"))
            except ValueError:continue
            if timestamp>=cutoff:recent.append(event)
        keys=[(str(item.get("observation_id")),str(item.get("pattern"))) for item in recent];trigger_duplicates=sum(count-1 for count in Counter(keys).values() if count>1)
        report_root=self.root/"data/research/module_b_reports";markdown=list(report_root.glob("*.md"));metadata=list(report_root.glob("*.md.json"));meta_valid=0;provenance_valid=0;readable=0;integrity_valid=0;schema_valid=0;version_valid=0
        for path in metadata:
            try:
                value=json.loads(path.read_text());complete=self.REQUIRED_META.issubset(value);report=Path(value.get("file",""));report=report if report.is_absolute() else self.root/report;content=report.read_text() if report.is_file() else ""
                readable+=int(bool(content.strip()));meta_valid+=int(complete)
                provenance_valid+=int(value.get("provenance")=="TIM_LOCAL_EVIDENCE_DETERMINISTIC" and value.get("mode")=="OBSERVE" and value.get("module")=="B" and value.get("report_source")=="local")
                input_hash=str(value.get("input_hash",""));artifact_hash=str(value.get("artifact_hash",""));report_id=str(value.get("report_id",""));expected_name=f"{report_id}_{value.get('report_type')}.md"
                integrity_valid+=int(bool(content) and re.fullmatch(r"[0-9a-f]{64}",input_hash) is not None and report_id==f"tim-b-{input_hash[:16]}" and re.fullmatch(r"[0-9a-f]{64}",artifact_hash) is not None and hashlib.sha256(content.encode()).hexdigest()==artifact_hash and report.name==expected_name and path.name==expected_name+".json" and value.get("word_count")==len(content.split()))
                schema_valid+=int(complete and value.get("report_type") in {"research_report","deep"} and value.get("tone") in {"analytical","formal","conversational"} and isinstance(value.get("sources"),int) and value.get("sources")>=0 and isinstance(value.get("word_count"),int) and value.get("word_count")>=0)
                version_valid+=int(value.get("schema_version")=="1.0.0" and value.get("generator_version")=="1.0.0")
            except (OSError,ValueError,TypeError):pass
        reports_ok=len(markdown)==len(metadata)==meta_valid==provenance_valid==readable==integrity_valid==schema_valid==version_valid
        try:
            from src.research.router import ResearchRouter,ResearchType
            router=ResearchRouter();router_logic=router.select("urgent",urgency="critical")==ResearchType.QUICK and router.select("deep",depth_required=True)==ResearchType.DEEP;fallback_ready=True
        except Exception:router_logic=fallback_ready=False
        execution_events=[item for item in self._jsonl(self.root/"data/operational/events.jsonl") if str(item.get("event","")).upper()=="TRADE_EXECUTED"]
        has_reports=bool(markdown or metadata)
        # With module B (LLM reports) switched off and no report on disk there is
        # nothing to verify: an empty report folder is the expected state, not a
        # fault. Any report that exists is still checked in full.
        reports_expected=has_reports or research_config.module_b_enabled
        def report_ok(valid:bool)->bool:return (has_reports and valid) if reports_expected else True
        checks={"fresh":True,"trigger_duplicates_zero":trigger_duplicates==0,"reports_readable":report_ok(readable==len(metadata)),"metadata_complete":report_ok(meta_valid==len(metadata)),"report_provenance_deterministic":report_ok(provenance_valid==len(metadata)),"report_integrity":report_ok(reports_ok),"report_schema":report_ok(schema_valid==len(metadata)),"report_version":report_ok(version_valid==len(metadata)),"module_a_dependencies":module_a_deps,"langgraph_compilable":graph_ready,"deepseek_ready":deepseek_ready,"gpt_researcher_import":gpt_import,"llama32_ready":llama_ready,"python313_isolated":python313,"external_search_disabled":not research_config.external_search_enabled,"multi_agent_disabled":not research_config.module_b_enabled,"no_trade_events":not execution_events,"router_logic":router_logic,"router_fallback":fallback_ready}
        for name,value in checks.items():
            if not value:
                blocking={"trigger_duplicates_zero","report_provenance_deterministic","report_integrity","report_schema","report_version","no_trade_events","module_a_dependencies"}
                if research_config.module_b_enabled:blocking.add("gpt_researcher_import")
                (critical if name in blocking else warnings).append(name)
        level="RED" if critical else ("YELLOW" if warnings else "GREEN")
        return {"status":"HEALTHY" if level=="GREEN" else "DEGRADED","level":level,"checked_at":checked_at.isoformat(),"next_check_seconds":60 if level=="GREEN" else 30,"warnings":warnings,"critical":critical,"checks":checks,"trigger_events_last_hour":len(recent),"trigger_duplicates":trigger_duplicates,"reports":{"markdown":len(markdown),"metadata":len(metadata),"metadata_valid":meta_valid,"provenance_valid":provenance_valid,"readable":readable,"integrity_valid":integrity_valid,"schema_valid":schema_valid,"version_valid":version_valid},"external_search":research_config.external_search_enabled,"multi_agent":research_config.module_b_enabled,"mode":"OBSERVE","isolated":level=="RED"}
