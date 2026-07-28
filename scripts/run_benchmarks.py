from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from src.benchmark.suite import BenchmarkSuite
def main()->int:
    result=BenchmarkSuite(ROOT/"benchmarks/market_cases_v1.json").run();out=ROOT/"data/benchmarks/latest.json";out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2));return 0 if result["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
