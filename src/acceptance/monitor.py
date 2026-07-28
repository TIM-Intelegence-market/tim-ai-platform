from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable


class EventCategory(StrEnum):
    CONTROLLED_API_FAILURE = "CONTROLLED_API_FAILURE"
    UNCONTROLLED_API_FAILURE = "UNCONTROLLED_API_FAILURE"
    VALIDATOR_RECOVERY = "VALIDATOR_RECOVERY"
    DATA_GAP = "DATA_GAP"


@dataclass(slots=True)
class Criterion:
    key: str
    label: str
    weight: float
    checker: str
    passed: bool | None = None
    evidence: str = "Not evaluated"


class AcceptanceMonitor:
    """Deterministic evaluator. It never advances time or fabricates evidence."""

    def __init__(self, root: Path | None = None, *, as_of: datetime | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2]
        self.as_of = as_of or datetime.now(timezone.utc)
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        self.state = self._read_json(self.root / "data/operational/state.json")
        self.metrics = self._read_jsonl(self.root / "data/operational/metrics.jsonl")
        self.events = self._read_jsonl(self.root / "data/operational/events.jsonl")
        self.start_time = self._time(self.state.get("started_at"))
        self.deadline = self._time(self.state.get("deadline"))
        self.criteria = [
            Criterion("runtime", "72h echte Laufzeit", .20, "_check_runtime"),
            Criterion("validator", "Validator durchgehend gesund", .10, "_check_validator_health"),
            Criterion("database", "Datenbankkonsistenz", .10, "_check_database"),
            Criterion("candles", "Candle-Zuwachs", .10, "_check_candle_growth"),
            Criterion("observations", "Deterministische Beobachtungen", .10, "_check_observations"),
            Criterion("cases", "Research Cases", .10, "_check_research_cases"),
            Criterion("api", "API-Verfügbarkeit", .10, "_check_api_availability"),
            Criterion("dashboard", "Dashboard Auto-Refresh", .05, "_check_dashboard"),
            Criterion("observe", "OBSERVE-only", .10, "_check_observe_only"),
            Criterion("provenance", "Deterministische Provenance", .05, "_check_provenance"),
        ]

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        try:
            output=[]
            for line in path.read_text().splitlines():
                try:
                    value=json.loads(line)
                    if isinstance(value,dict):output.append(value)
                except (ValueError,TypeError):continue
            return output
        except OSError:return []

    @staticmethod
    def _time(value: Any) -> datetime | None:
        try:
            parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
            return parsed if parsed.tzinfo else None
        except (ValueError,TypeError):return None

    def check_deadline(self) -> bool:
        return self.deadline is not None and self.as_of >= self.deadline

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any]:
        for criterion in self.criteria:
            criterion.passed,criterion.evidence=getattr(self,criterion.checker)(context)
        score=round(sum(item.weight for item in self.criteria if item.passed),4)
        all_required=all(item.passed for item in self.criteria)
        return {"passed":self.check_deadline() and all_required and score>=.95,"deadline_reached":self.check_deadline(),"total_score":score,"criteria":[{"key":item.key,"label":item.label,"weight":item.weight,"passed":item.passed,"evidence":item.evidence} for item in self.criteria]}

    def health_matrix(self, context: dict[str, Any]) -> dict[str, Any]:
        """Evaluate the current operational hour without fabricating evidence."""
        cutoff=self.as_of.timestamp()-3600
        recent=[m for m in self.metrics if (self._time(m.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp()>=cutoff]
        recent_events=[e for e in self.events if (self._time(e.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp()>=cutoff]
        controlled=sum(e.get("category")==EventCategory.CONTROLLED_API_FAILURE.value for e in recent_events)
        unavailable=sum(m.get("dashboard")!="HEALTHY" for m in recent);uncontrolled=max(0,unavailable-controlled)
        checks={
            "validator_running":self.state.get("status")=="RUNNING",
            "validator_cycle_growth":len(recent)>=1,
            "validator_healthy":bool(recent) and sum(not (m.get("database")=="HEALTHY" and m.get("dashboard")=="HEALTHY" and m.get("benchmark")=="PASS" and m.get("research","HEALTHY")=="HEALTHY") for m in recent)<=controlled,
            "api_http_200":context.get("api_http_status")==200,
            "api_under_500ms":float(context.get("api_latency_ms",999999))<500,
            "api_error_rate_under_1pct":uncontrolled/max(1,len(recent))<.01,
            "state_readable":bool(self.state),
            "candle_sequence_gap_free":int(context.get("candle_gaps",0))==0,
            "last_write_under_5m":float(context.get("last_candle_age_seconds",999999))<300,
            "candle_stream_active":context.get("candle_stream_active") is True,
            "candle_timestamps_monotonic":context.get("candle_timestamps_monotonic") is True,
            "candle_rate":float(context.get("candles_last_hour",0))>=12,
            "provenance_deterministic":int(context.get("provenance_total",0))>0 and context.get("provenance_total")==context.get("provenance_valid"),
            "observe_mode":self.state.get("mode")=="OBSERVE",
            "no_execution_events":not any(str(e.get("event","")).upper() in {"TRADE_EXECUTED","ORDER_CREATED","BUY","SELL","LONG","SHORT"} for e in self.events),
            "dashboard_polling":context.get("dashboard_auto_refresh") is True,
            "countdown_synchronized":context.get("countdown_synchronized") is True,
        }
        critical=[];warnings=[]
        if not checks["candle_sequence_gap_free"]:critical.append("DATA_GAP")
        if uncontrolled:critical.append("UNCONTROLLED_API_FAILURE")
        for key,value in checks.items():
            if not value and key not in {"candle_sequence_gap_free","api_error_rate_under_1pct"}:warnings.append(key)
        level="RED" if critical else ("YELLOW" if warnings else "GREEN")
        return {"level":level,"checks":checks,"warnings":warnings,"critical":critical,"controlled_api_failures":controlled,"uncontrolled_api_failures":uncontrolled,"checked_at":self.as_of.isoformat(),"next_check_minutes":60 if level=="GREEN" else 15}

    def _check_runtime(self,_:dict)->tuple[bool,str]:
        if not self.start_time or not self.deadline:return False,"Start or deadline missing"
        hours=(self.as_of-self.start_time).total_seconds()/3600
        return self.check_deadline(),f"{hours:.3f} real hours elapsed; deadline {self.deadline.isoformat()}"

    def _check_validator_health(self,_:dict)->tuple[bool,str]:
        unhealthy=[row for row in self.metrics if row.get("benchmark")!="PASS" or row.get("database")!="HEALTHY" or row.get("dashboard")!="HEALTHY"]
        controlled=sum(1 for event in self.events if event.get("category")==EventCategory.CONTROLLED_API_FAILURE.value)
        effective=max(0,len(unhealthy)-controlled)
        return bool(self.metrics) and effective==0,f"{len(self.metrics)-len(unhealthy)}/{len(self.metrics)} healthy samples; {effective} uncontrolled unhealthy; {controlled} controlled events"

    def _check_database(self,ctx:dict)->tuple[bool,str]:
        passed=ctx.get("database_consistent") is True
        return passed,"Consistency queries passed" if passed else "Database consistency not proven"

    def _check_candle_growth(self,ctx:dict)->tuple[bool,str]:
        count=int(ctx.get("acceptance_candles",0));minutes=max(0,float(ctx.get("acceptance_minutes",0)));required=int(minutes//5)
        return count>=required,f"{count} candles; minimum {required} for {minutes:.1f} minutes"

    def _check_observations(self,ctx:dict)->tuple[bool,str]:
        total=int(ctx.get("observations",0));distinct=int(ctx.get("distinct_observations",-1));deterministic=ctx.get("observations_deterministic") is True
        return total==distinct and deterministic,f"{distinct}/{total} unique; deterministic={deterministic}"

    def _check_research_cases(self,ctx:dict)->tuple[bool,str]:
        total=int(ctx.get("research_cases",0));with_provenance=int(ctx.get("cases_with_provenance",0))
        return total>=10 and total==with_provenance,f"{total} cases; {with_provenance} with provenance"

    def _check_api_availability(self,ctx:dict)->tuple[bool,str]:
        samples=max(1,len(self.metrics));controlled=sum(1 for e in self.events if e.get("category")==EventCategory.CONTROLLED_API_FAILURE.value);unhealthy=sum(1 for row in self.metrics if row.get("dashboard")!="HEALTHY");effective=max(0,unhealthy-controlled);ratio=effective/samples
        return ratio<.01,f"{effective}/{samples} uncontrolled unavailable samples ({ratio:.3%}); {controlled} controlled"

    def _check_dashboard(self,ctx:dict)->tuple[bool,str]:
        passed=ctx.get("dashboard_auto_refresh") is True
        return passed,"Auto-refresh regression passed" if passed else "Auto-refresh not proven"

    def _check_observe_only(self,ctx:dict)->tuple[bool,str]:
        forbidden={"TRADE_EXECUTED","ORDER_CREATED","BUY","SELL","LONG","SHORT"};found=[e for e in self.events if str(e.get("type",e.get("event",""))).upper() in forbidden]
        return not found,f"{len(found)} execution events"

    def _check_provenance(self,ctx:dict)->tuple[bool,str]:
        total=int(ctx.get("provenance_total",0));valid=int(ctx.get("provenance_valid",0))
        return total>0 and total==valid,f"{valid}/{total} deterministic provenance records"

    def generate_report(self, context: dict[str, Any]) -> str:
        if not self.check_deadline():
            raise RuntimeError("72-hour deadline has not been reached")
        result=self.evaluate(context);decision="GO" if result["passed"] else "NO-GO"
        rows="\n".join(f"| {item['label']} | {'PASS' if item['passed'] else 'FAIL'} | {item['evidence']} |" for item in result["criteria"])
        return f"""# TIM 72h Acceptance Report
## Executive Summary
Decision: **{decision}**. Score: {result['total_score']:.0%}.

## System Architecture
Deterministic public-data observation pipeline with PostgreSQL persistence and read-only dashboard.

## Operational Metrics (72h)
Samples: {len(self.metrics)}. Validator cycles: {self.state.get('cycles',0)}.

## Akzeptanzkriterien
| Criterion | Status | Evidence |
|---|---|---|
{rows}

## Resilience Testing
Event classifications: CONTROLLED_API_FAILURE, UNCONTROLLED_API_FAILURE, VALIDATOR_RECOVERY, DATA_GAP.

## Data Quality Audit
Provenance: PUBLIC_MARKET_DATA_DETERMINISTIC

## Compliance Check (OBSERVE-only)
No execution event is permitted.

## Known Limitations
Only evidence inside the acceptance window is evaluated.

## Go/No-Go Recommendation
**{decision}**
"""


def run_acceptance_check(root: Path, context: dict[str, Any], *, as_of: datetime | None = None) -> dict[str, Any]:
    monitor=AcceptanceMonitor(root,as_of=as_of)
    matrix=monitor.health_matrix(context)
    if not monitor.check_deadline():
        return {"status":"monitoring","deadline":monitor.deadline.isoformat() if monitor.deadline else None,"health_matrix":matrix,"result":monitor.evaluate(context)}
    report=monitor.generate_report(context);path=root/"docs/TIM_72H_ACCEPTANCE_REPORT.md";path.write_text(report)
    return {"status":"complete","path":str(path),"health_matrix":matrix,"result":monitor.evaluate(context)}
