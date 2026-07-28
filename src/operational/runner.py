from __future__ import annotations
import asyncio,json,os,signal,subprocess,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any
from config.settings import settings
from src.benchmark.suite import BenchmarkSuite
from src.operational.health import HealthChecker
from src.operational.logging import StructuredLog
from src.operational.metrics import MetricsCollector
from src.operational.research_cycle_check import ResearchCycleChecker

class OperationalValidator:
    def __init__(self,root:Path,duration_seconds:int=259200,interval_seconds:int=60)->None:
        self.root=root;self.duration_seconds=duration_seconds;self.interval_seconds=max(5,interval_seconds);self.base=root/"data/operational";self.base.mkdir(parents=True,exist_ok=True);self.state_path=self.base/"state.json";self.report_path=self.base/"validation_report.json";self.metrics_path=self.base/"metrics.jsonl";self.log=StructuredLog(self.base/"events.jsonl");self.stop_requested=False
        self.state=self._load()
    def _load(self)->dict[str,Any]:
        try:
            state=json.loads(self.state_path.read_text())
            if str(state.get("status","")).upper()=="COMPLETED":
                return state
            state["restart_count"]=int(state.get("restart_count",0))+1;state["status"]="RUNNING";state.pop("completed_at",None);state.pop("last_acceptance_check_at",None);return state
        except (OSError,ValueError,TypeError):
            now=datetime.now(timezone.utc);return {"status":"RUNNING","started_at":now.isoformat(),"deadline":(now+timedelta(seconds=self.duration_seconds)).isoformat(),"cycles":0,"restart_count":0,"database_healthy_cycles":0,"dashboard_healthy_cycles":0,"benchmark_failures":0,"max_rss_mb":0.0,"max_cpu_percent":0.0,"mode":"OBSERVE"}
    def _write(self,path:Path,value:Any)->None:
        temp=path.with_suffix(".tmp");temp.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n");os.replace(temp,path)
    def _acceptance_due(self,now:datetime,final:bool=False)->bool:
        if final:return True
        try:last=datetime.fromisoformat(self.state["last_acceptance_check_at"])
        except (KeyError,ValueError,TypeError):return True
        interval=900 if self.state.get("health_monitor",{}).get("level") in {"YELLOW","RED"} else 3600
        return (now-last).total_seconds()>=interval
    async def _run_acceptance(self,final:bool=False)->dict[str,Any]:
        now=datetime.now(timezone.utc)
        if not self._acceptance_due(now,final):return self.state.get("acceptance",{})
        process=await asyncio.create_subprocess_exec(sys.executable,str(self.root/"scripts/acceptance_check.py"),cwd=self.root,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await process.communicate()
        try:result=json.loads(stdout)
        except (ValueError,TypeError):result={"status":"error","reason":stderr.decode(errors="replace")[-1000:] or "empty acceptance output"}
        matrix=result.get("health_matrix")
        if isinstance(matrix,dict) and matrix:
            self.state["health_monitor"]=matrix
        else:
            matrix=self.state.get("health_monitor",{})
        self.state["last_acceptance_check_at"]=now.isoformat();self.state["acceptance"]={"status":result.get("status","error"),"deadline_reached":result.get("result",{}).get("deadline_reached",False),"score":result.get("result",{}).get("total_score"),"report_path":result.get("path"),"checked_at":now.isoformat()};self._write(self.state_path,self.state)
        failed=process.returncode!=0 or result.get("status")=="error" or (result.get("status")=="complete" and not result.get("result",{}).get("passed"))
        severity="ERROR" if failed or matrix.get("level")=="RED" else "WARNING" if matrix.get("level")=="YELLOW" else "INFO"
        self.log.write("HOURLY_HEALTH_CHECK",severity=severity,final=final,return_code=process.returncode,result=self.state["acceptance"],health_matrix=matrix)
        if result.get("status")=="complete":
            message="TIM 72h Acceptance abgeschlossen: "+("GO" if result.get("result",{}).get("passed") else "NO-GO")
            subprocess.run(["osascript","-e",f'display notification "{message}" with title "TIM Acceptance"'],check=False,timeout=5)
        return self.state["acceptance"]
    def _run_research_check(self,checker:ResearchCycleChecker,next_cycle:int)->dict[str,Any]:
        try:
            checker.validator_cycle=next_cycle
            summary=checker.run_full_check()
            research=summary["health"]
            self.state["research_health"]=summary["overall_status"]
            self.state["research_last_check"]=summary["check_timestamp"]
            return research
        except Exception as error:
            checked_at=datetime.now(timezone.utc).isoformat()
            self.state["research_health"]="CRITICAL"
            self.state["research_last_check"]=checked_at
            self.log.write("RESEARCH_CYCLE_CHECK_FAILED",severity="ERROR",cycle=next_cycle,error_type=type(error).__name__,error=str(error))
            return {"status":"DEGRADED","level":"RED","checked_at":checked_at,"next_check_seconds":30,"warnings":[],"critical":["research_cycle_check_failed"],"checks":{},"mode":"OBSERVE","isolated":True}
    async def _run_scientific_snapshot(self)->None:
        now=datetime.now(timezone.utc)
        try:last=datetime.fromisoformat(self.state.get("last_scientific_snapshot_at",""))
        except (ValueError,TypeError):last=None
        if last is not None and (now-last).total_seconds()<3600:return
        process=await asyncio.create_subprocess_exec(sys.executable,str(self.root/"scripts/research_infrastructure_review.py"),cwd=self.root,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await process.communicate();self.state["last_scientific_snapshot_at"]=now.isoformat();self.state["scientific_snapshot_status"]="PASS" if process.returncode==0 else "FAIL";self._write(self.state_path,self.state)
        self.log.write("SCIENTIFIC_SNAPSHOT",severity="INFO" if process.returncode==0 else "ERROR",return_code=process.returncode,output=stdout.decode(errors="replace")[-1000:],error=stderr.decode(errors="replace")[-1000:],mode="OBSERVE")
    async def run(self)->dict[str,Any]:
        if str(self.state.get("status","")).upper()=="COMPLETED":
            return self.report()
        collector=MetricsCollector(self.root);health=HealthChecker(settings.database_url);research_cycle=ResearchCycleChecker(self.root,settings.ollama_url);self.log.write("VALIDATION_STARTED",duration_seconds=self.duration_seconds,restart_count=self.state["restart_count"])
        while not self.stop_requested and datetime.now(timezone.utc)<datetime.fromisoformat(self.state["deadline"]):
            cycle_started=time.monotonic();metrics=collector.collect();database,dashboard=await asyncio.gather(health.database(),health.dashboard());next_cycle=self.state["cycles"]+1;research=self._run_research_check(research_cycle,next_cycle);files=health.files([self.root/"src/database/schema.sql",self.root/"benchmarks/market_cases_v1.json",self.root/"main.py"]);benchmark=BenchmarkSuite(self.root/"benchmarks/market_cases_v1.json").run()
            isolation=self.root/"data/research/isolation.json"
            if research.get("level")=="RED":self._write(isolation,{"isolated":True,"reason":research.get("critical",[]),"at":research.get("checked_at")})
            elif isolation.exists():isolation.unlink()
            self.state["cycles"]+=1;self.state["last_cycle_at"]=datetime.now(timezone.utc).isoformat();self.state["database_healthy_cycles"]+=int(database["status"]=="HEALTHY");self.state["dashboard_healthy_cycles"]+=int(dashboard["status"]=="HEALTHY");self.state["benchmark_failures"]+=int(benchmark["status"]!="PASS");self.state["max_rss_mb"]=max(self.state["max_rss_mb"],metrics.rss_mb);self.state["max_cpu_percent"]=max(self.state["max_cpu_percent"],metrics.cpu_percent);self.state["latest_health"]={"database":database,"dashboard":dashboard,"research":research,"files":files,"benchmark":benchmark["status"]}
            with self.metrics_path.open("a") as handle:handle.write(json.dumps({**metrics.to_dict(),"database":database["status"],"dashboard":dashboard["status"],"research":research["status"],"benchmark":benchmark["status"]})+"\n")
            self._write(self.state_path,self.state);self._write(self.report_path,self.report());self.log.write("VALIDATION_CYCLE",cycle=self.state["cycles"],health=self.state["latest_health"]);await self._run_acceptance();await self._run_scientific_snapshot()
            interval=30 if research.get("level") in {"YELLOW","RED"} else self.interval_seconds
            await asyncio.sleep(max(0,interval-(time.monotonic()-cycle_started)))
        if not self.stop_requested:await self._run_acceptance(final=True)
        self.state["status"]="STOPPED" if self.stop_requested else "COMPLETED";self.state["completed_at"]=datetime.now(timezone.utc).isoformat();self._write(self.state_path,self.state);report=self.report();self._write(self.report_path,report);self.log.write("VALIDATION_FINISHED",status=self.state["status"]);return report
    def report(self)->dict[str,Any]:
        cycles=max(1,self.state["cycles"]);return {"timestamp":datetime.now(timezone.utc).isoformat(),"status":self.state["status"],"mode":"OBSERVE","started_at":self.state["started_at"],"deadline":self.state["deadline"],"cycles":self.state["cycles"],"restart_count":self.state["restart_count"],"database_health_percent":round(self.state["database_healthy_cycles"]/cycles*100,2),"dashboard_health_percent":round(self.state["dashboard_healthy_cycles"]/cycles*100,2),"benchmark_failures":self.state["benchmark_failures"],"max_rss_mb":self.state["max_rss_mb"],"max_cpu_percent":self.state["max_cpu_percent"],"latest_health":self.state.get("latest_health",{}),"constraints":{"live_trading":False,"orders":False,"deterministic":True},"limitations":["A completed 72-hour claim is emitted only after the real deadline."]}
