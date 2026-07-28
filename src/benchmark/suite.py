from __future__ import annotations
import hashlib,json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any
from src.assistant.short_term import ShortTermAssistant
from src.models.market_data import Candle,Observation,ObservationKind
from src.observation.engine import ObservationEngine

class BenchmarkSuite:
    def __init__(self,dataset:Path)->None:self.dataset=dataset
    def run(self)->dict[str,Any]:
        raw=self.dataset.read_bytes();payload=json.loads(raw);results=[]
        for case in payload["cases"]:
            start=datetime(2026,1,1,tzinfo=timezone.utc);candles=[]
            for index,row in enumerate(case["candles"]):
                open_,high,low,close,volume=row;candles.append(Candle("BTCUSDT",case["timeframe"],start+timedelta(minutes=index),start+timedelta(minutes=index+1),open_,high,low,close,volume,10))
            actual=sorted({item.kind.value for item in ObservationEngine().evaluate(candles)});expected=sorted(case["expected"]);results.append({"case_id":case["case_id"],"expected":expected,"actual":actual,"passed":all(item in actual for item in expected)})
        for case in payload.get("assistant_cases",[]):
            at=datetime(2026,1,1,tzinfo=timezone.utc);observations=[Observation(ObservationKind(kind),"BTCUSDT",timeframe,at,kind,60,{}) for kind,timeframe in case["observations"]];report=ShortTermAssistant().explain(observations);actual=bool(report.conflicts);results.append({"case_id":case["case_id"],"expected_conflict":case["expected_conflict"],"actual_conflict":actual,"passed":actual==case["expected_conflict"]})
        return {"timestamp":datetime.now(timezone.utc).isoformat(),"dataset":str(self.dataset),"dataset_sha256":hashlib.sha256(raw).hexdigest(),"version":payload["version"],"total":len(results),"passed":sum(item["passed"] for item in results),"failed":sum(not item["passed"] for item in results),"cases":results,"status":"PASS" if all(item["passed"] for item in results) else "FAIL"}
