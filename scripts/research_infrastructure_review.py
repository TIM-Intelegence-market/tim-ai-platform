#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.database.connection import Database
from src.research_ops import MonthlyResearchSnapshot, ResearchAuditEngine, ResearchQualityEngine


def stable_json(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)


def append_maturity_history(path:Path,snapshot:dict) -> bool:
    """Append one content-addressed observation per unique snapshot."""
    path.parent.mkdir(parents=True,exist_ok=True)
    try:rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except OSError:rows=[]
    if any(row.get("snapshot_hash")==snapshot.get("snapshot_hash") for row in rows):return False
    previous=rows[-1].get("record_hash") if rows else None
    research=snapshot["research_results"];coverage=snapshot["coverage"]
    record={"schema_version":"1.0.0","generator_version":"1.0.0","generation_timestamp":snapshot["generation_timestamp"],"timestamp":snapshot["generation_timestamp"],"mode":"OBSERVE","provenance":"TIM_RESEARCH_SNAPSHOT_DETERMINISTIC","dataset_hash":snapshot["dataset_hash"],"artifact_hash":snapshot["artifact_hash"],"validation_status":snapshot["validation_status"],"snapshot_hash":snapshot["snapshot_hash"],"previous_record_hash":previous,"observations":research["observations"],"fully_validated_cases":research["fully_validated_cases"],"open_cases":research["open_cases"],"validation_coverage_percent":research["validation_coverage_percent"],"temporal_coverage_percent":coverage.get("coverage_percent"),"data_gap_count":len(snapshot["data_quality"].get("known_data_gaps",[])),"historical_limitations":snapshot.get("known_limitations",[]),"replay_status":snapshot["replay"].get("status"),"scientific_health_status":snapshot["scientific_health"]["status"],"versions":snapshot["versions"]}
    record["record_hash"]=hashlib.sha256(json.dumps(record,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    rows.append(record);atomic_write(path,"".join(json.dumps(row,sort_keys=True,ensure_ascii=False)+"\n" for row in rows));return True


def build_readiness(snapshot:dict,history:list[dict],regression:dict,manual_review:dict|None=None)->dict:
    """Report fixed review criteria without approving V2 or changing sources."""
    research=snapshot["research_results"];coverage=snapshot["coverage"];health=snapshot["scientific_health"];manual_review=manual_review or {}
    validated=int(research["fully_validated_cases"]);required=1000;remaining=max(0,required-validated);progress=(Decimal(validated)*100/Decimal(required)).quantize(Decimal("0.001"),rounding=ROUND_HALF_EVEN)
    new_gaps=sum(1 for item in snapshot["data_quality"].get("known_data_gaps",[]) if item.get("timestamp") and history and item["timestamp"]>=history[0]["generation_timestamp"])
    statuses={"validated_cases":"PASS" if validated>=required else "WAITING","continuous_coverage":"PASS" if Decimal(str(coverage.get("continuous_coverage_percent","0")))>=Decimal("95") else "WAITING","unresolved_new_data_gaps":"PASS" if new_gaps==0 else "FAIL","new_artifact_provenance":"PASS" if health["checks"].get("new_artifact_provenance")=="PASS" else "FAIL","replay":"PASS" if health["checks"].get("replay")=="PASS" else "FAIL","hash_consistency":"PASS" if health["checks"].get("dataset_hash")==health["checks"].get("output_hash")=="PASS" else "FAIL","forward_only":"PASS" if health["checks"].get("forward_only")=="PASS" else "FAIL","observe_only":"PASS" if health["checks"].get("observe_only")=="PASS" else "FAIL","regression_tests":"PASS" if regression.get("status")=="PASS" else "WAITING","manual_scientific_review":"PASS" if manual_review.get("status")=="PASS" else "WAITING"}
    rate_hour=rate_day=None;projected=None
    if len(history)>=2:
        first,last=history[0],history[-1];elapsed=(datetime.fromisoformat(last["generation_timestamp"])-datetime.fromisoformat(first["generation_timestamp"])).total_seconds();increase=int(last["fully_validated_cases"])-int(first["fully_validated_cases"])
        if elapsed>=3600 and increase>=0:
            rate_hour=(Decimal(increase)*Decimal(3600)/Decimal(str(elapsed))).quantize(Decimal("0.001"),rounding=ROUND_HALF_EVEN);rate_day=(rate_hour*24).quantize(Decimal("0.001"),rounding=ROUND_HALF_EVEN)
            if rate_hour>0 and remaining:projected=(datetime.fromisoformat(snapshot["generation_timestamp"])+timedelta(hours=float(Decimal(remaining)/rate_hour))).isoformat()
    blockers=sorted(key for key,value in statuses.items() if value!="PASS");overall="ELIGIBLE_FOR_SCIENTIFIC_REVIEW" if not blockers else "NOT_READY_FOR_V2"
    payload={"schema_version":"1.0.0","generator_version":"1.0.0","generated_at":snapshot["generation_timestamp"],"generation_timestamp":snapshot["generation_timestamp"],"mode":"OBSERVE","snapshot_id":snapshot["snapshot_hash"],"dataset_hash":snapshot["dataset_hash"],"output_hash":health.get("output_hash"),"observation_count":research["observations"],"validated_case_count":validated,"open_case_count":research["open_cases"],"required_case_count":required,"validated_case_progress_percent":format(progress,"f"),"remaining_case_count":remaining,"measured_validated_cases_per_hour":format(rate_hour,"f") if rate_hour is not None else None,"measured_validated_cases_per_day":format(rate_day,"f") if rate_day is not None else None,"nonbinding_projected_1000_case_time":projected,"projection_notice":"UNVERBINDLICHE OPERATIVE HOCHRECHNUNG AUS GEMESSENEM VERLAUF" if projected else "INSUFFICIENT_MEASURED_HISTORY","continuous_window_start":coverage.get("continuous_interval_start"),"continuous_window_end":coverage.get("continuous_interval_end"),"continuous_expected_1m_intervals":coverage.get("continuous_expected_intervals"),"continuous_persisted_1m_intervals":coverage.get("continuous_observed_intervals"),"continuous_missing_1m_intervals":coverage.get("continuous_missing_intervals"),"continuous_coverage_percent":coverage.get("continuous_coverage_percent"),"unresolved_new_gap_count":new_gaps,"new_artifact_provenance_status":statuses["new_artifact_provenance"],"replay_status":statuses["replay"],"forward_only_status":statuses["forward_only"],"observe_only_status":statuses["observe_only"],"regression_test_status":statuses["regression_tests"],"scientific_health_status":health["status"],"criteria":statuses,"readiness_status":overall,"blocking_criteria":blockers,"eligible_for_scientific_review":overall=="ELIGIBLE_FOR_SCIENTIFIC_REVIEW","v2_approved":False,"validation_status":"PASS" if not blockers else "OPEN_ISSUES","provenance":"TIM_OPERATIONAL_STATUS_DETERMINISTIC"}
    payload["artifact_hash"]=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest();return payload


def readiness_markdown(value:dict)->str:
    rows="\n".join(f"| {key} | {status} |" for key,status in sorted(value["criteria"].items()))
    return f"# TIM V1 Live Scientific Status\n\n**Generated:** {value['generated_at']}  \n**Mode:** OBSERVE-only  \n**Overall:** {value['readiness_status']}\n\n## Progress\n\n- Observations: {value['observation_count']}\n- Validated cases: {value['validated_case_count']} / {value['required_case_count']} ({value['validated_case_progress_percent']}%)\n- Open cases: {value['open_case_count']}\n- Remaining cases: {value['remaining_case_count']}\n- Continuous coverage: {value['continuous_coverage_percent']}%\n- Measured cases/hour: {value['measured_validated_cases_per_hour']}\n- Measured cases/day: {value['measured_validated_cases_per_day']}\n- Nonbinding projection: {value['nonbinding_projected_1000_case_time']}\n\n## V2 readiness matrix\n\n| Criterion | Status |\n|---|---|\n{rows}\n\nV2 is not approved automatically. Manual Evolution Review remains mandatory.\n"


async def persisted_month_facts(month: str, as_of: datetime) -> tuple[dict[str, int], dict]:
    start = datetime.fromisoformat(month + "-01T00:00:00+00:00")
    if start.month == 12: end = start.replace(year=start.year + 1, month=1)
    else: end = start.replace(month=start.month + 1)
    upper = min(end, as_of.astimezone(timezone.utc))
    database = Database(settings.database_url)
    await database.connect()
    try:
        async with database.acquire() as connection:
            specs = {
                "agg_trades": ("agg_trades", "trade_time"), "candles": ("candles", "open_time"), "observations": ("observations", "observed_at"),
                "orderflow_observations": ("orderflow_observations", "observed_at"), "research_cases": ("research_cases", "opened_at"),
            }
            counts = {name: int(await connection.fetchval(f"SELECT count(*) FROM {table} WHERE {column}>=$1 AND {column}<$2", start, upper)) for name,(table,column) in specs.items()}
            counts["validated_cases"] = int(await connection.fetchval("SELECT count(*) FROM orderflow_validations WHERE complete=true AND observed_at>=$1 AND observed_at<$2", start, upper))
            row = await connection.fetchrow("SELECT min(open_time) AS first,max(open_time) AS last,count(DISTINCT open_time) AS observed FROM candles WHERE symbol=$1 AND timeframe='1m' AND closed=true AND open_time>=$2 AND open_time<$3", settings.symbol, start, upper)
            raw_start = await connection.fetchval("SELECT min(date_trunc('minute',trade_time)) FROM agg_trades WHERE symbol=$1 AND trade_time>=$2 AND trade_time<$3",settings.symbol,start,upper)
            continuous_start=raw_start+timedelta(minutes=1) if raw_start else None
            continuous_observed=int(await connection.fetchval("SELECT count(DISTINCT open_time) FROM candles WHERE symbol=$1 AND timeframe='1m' AND closed=true AND open_time>=$2 AND open_time<=$3",settings.symbol,continuous_start,row["last"]) or 0) if continuous_start and row["last"] and continuous_start<=row["last"] else 0
    finally:
        await database.close()
    first, last, observed = row["first"], row["last"], int(row["observed"] or 0)
    expected = int((last - first).total_seconds() // 60) + 1 if first and last else 0
    percent = (Decimal(observed) * 100 / Decimal(expected)).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN) if expected else Decimal("0")
    continuous_expected=int((last-continuous_start).total_seconds()//60)+1 if continuous_start and last and continuous_start<=last else 0
    continuous_percent=(Decimal(continuous_observed)*100/Decimal(continuous_expected)).quantize(Decimal("0.001"),rounding=ROUND_HALF_EVEN) if continuous_expected else Decimal("0")
    coverage = {"basis":f"{settings.symbol} closed 1m candles","interval_start":first.isoformat() if first else None,"interval_end":last.isoformat() if last else None,"expected_intervals":expected,"observed_intervals":observed,"missing_intervals":max(0,expected-observed),"coverage_percent":format(percent,"f"),"continuous_window_definition":"FIRST_FULL_MINUTE_AFTER_RAW_AGGTRADE_PERSISTENCE","continuous_interval_start":continuous_start.isoformat() if continuous_start else None,"continuous_interval_end":last.isoformat() if last else None,"continuous_expected_intervals":continuous_expected,"continuous_observed_intervals":continuous_observed,"continuous_missing_intervals":max(0,continuous_expected-continuous_observed),"continuous_coverage_percent":format(continuous_percent,"f")}
    return counts, coverage


def get_insights() -> dict:
    with urlopen(f"http://127.0.0.1:{settings.dashboard_port}/api/insights", timeout=10) as response:
        value = json.loads(response.read())
    if not isinstance(value, dict) or value.get("mode") != "OBSERVE": raise ValueError("valid OBSERVE insights response required")
    return value


async def main() -> None:
    as_of = datetime.now(timezone.utc)
    month = as_of.strftime("%Y-%m")
    manifest = json.loads((ROOT / "config/core_manifest.json").read_text())
    audit = ResearchAuditEngine(ROOT).audit(as_of=as_of)
    quality = ResearchQualityEngine().assess(ROOT, audit, as_of=as_of)
    counts, coverage = await persisted_month_facts(month, as_of)
    insights = get_insights()
    state = json.loads((ROOT / "data/operational/state.json").read_text())
    validation_path = ROOT / "data/operational/validation_report.json"
    replay = {"status":state.get("latest_health",{}).get("benchmark","UNKNOWN"),"hash":hashlib.sha256(validation_path.read_bytes()).hexdigest() if validation_path.is_file() else ""}
    snapshot = MonthlyResearchSnapshot().build(month=month,as_of=as_of,manifest=manifest,counts=counts,coverage=coverage,replay=replay,quality=quality,insights=insights)
    atomic_write(ROOT / "data/research/audit/latest.json", stable_json(audit))
    atomic_write(ROOT / "data/research/quality/latest.json", stable_json(quality))
    suffix = ".json" if snapshot["snapshot_status"] == "FINAL" else ".in_progress.json"
    snapshot_path = ROOT / "data/research/snapshots" / f"{month}{suffix}"
    atomic_write(snapshot_path, stable_json(snapshot))
    atomic_write(snapshot_path.with_suffix(".md"), MonthlyResearchSnapshot.to_markdown(snapshot))
    history_path=ROOT/"data/research/snapshots/scientific_maturity_history.jsonl";append_maturity_history(history_path,snapshot)
    history=[json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
    try:regression=json.loads((ROOT/"data/operational/regression_status.json").read_text())
    except (OSError,ValueError,TypeError):regression={}
    try:manual=json.loads((ROOT/"data/research/status/manual_scientific_review.json").read_text())
    except (OSError,ValueError,TypeError):manual={}
    readiness=build_readiness(snapshot,history,regression,manual);atomic_write(ROOT/"data/research/status/tim_v1_readiness.json",stable_json(readiness));atomic_write(ROOT/"docs/TIM_V1_LIVE_STATUS.md",readiness_markdown(readiness))
    print(stable_json({"audit":{"status":audit["status"],"artifacts":audit["artifacts_checked"],"issues":len(audit["issues"]),"hash":audit["audit_hash"]},"quality":{"status":quality["status"],"issues":len(quality["issues"]),"hash":quality["report_hash"]},"snapshot":{"status":snapshot["snapshot_status"],"path":str(snapshot_path),"hash":snapshot["snapshot_hash"],"counts":counts,"coverage":coverage}}))


if __name__ == "__main__": asyncio.run(main())
