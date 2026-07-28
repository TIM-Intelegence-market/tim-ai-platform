from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable, Any

from src.models.market_data import Candle, Observation, Trade


class Severity(StrEnum):
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    freshness_seconds: int = 3600
    future_tolerance_seconds: int = 0
    detect_candle_gaps: bool = True

    def __post_init__(self) -> None:
        if self.freshness_seconds < 0 or self.future_tolerance_seconds < 0:
            raise ValueError("Quality time thresholds cannot be negative")


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    severity: Severity
    record_type: str
    record_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class QualityReport:
    generated_at: datetime
    records_checked: int
    valid_records: int
    duplicate_records: int
    issues: tuple[QualityIssue, ...]
    provenance_counts: dict[str, int]
    quality_score: int
    input_hash: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self);result["generated_at"] = self.generated_at.isoformat();result["issues"] = [{**asdict(item), "severity": item.severity.value} for item in self.issues];return result


class DataQualityFramework:
    """Deterministic validation for TIM records. It never repairs or infers data."""

    def __init__(self, policy: QualityPolicy | None = None) -> None:
        self.policy = policy or QualityPolicy()

    def validate(self, records: Iterable[Trade | Candle | Observation], *, as_of: datetime | None = None) -> QualityReport:
        as_of = as_of or datetime.now(timezone.utc)
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        items = list(records);issues=[];seen=set();duplicates=0;provenance_counts={}
        serialized=[]
        for index, record in enumerate(items):
            record_type=type(record).__name__;record_id=self._identity(record);serialized.append(self._serialize(record))
            if record_id in seen:
                duplicates+=1;issues.append(QualityIssue("DUPLICATE_RECORD",Severity.ERROR,record_type,record_id,"Deterministic identity already occurred in this batch."))
            seen.add(record_id)
            timestamp=self._timestamp(record)
            if timestamp.tzinfo is None:issues.append(QualityIssue("NAIVE_TIMESTAMP",Severity.ERROR,record_type,record_id,"Timestamp lacks timezone information."))
            elif timestamp > as_of + timedelta(seconds=self.policy.future_tolerance_seconds):issues.append(QualityIssue("FUTURE_TIMESTAMP",Severity.ERROR,record_type,record_id,"Timestamp is later than the explicit report time."))
            elif as_of - timestamp > timedelta(seconds=self.policy.freshness_seconds):issues.append(QualityIssue("STALE_RECORD",Severity.WARNING,record_type,record_id,"Record exceeds the configured freshness threshold."))
            provenance=str(getattr(record,"provenance","BINANCE_PUBLIC" if isinstance(record,(Trade,Candle)) else ""))
            if not provenance:issues.append(QualityIssue("MISSING_PROVENANCE",Severity.ERROR,record_type,record_id,"Provenance is required."))
            else:provenance_counts[provenance]=provenance_counts.get(provenance,0)+1
            issues.extend(self._record_checks(record,record_id))
        if self.policy.detect_candle_gaps:issues.extend(self._candle_gap_checks(items))
        invalid_ids={item.record_id for item in issues if item.severity is Severity.ERROR};score=max(0,100-round(len([x for x in issues if x.severity is Severity.ERROR])/max(1,len(items))*25)-round(len([x for x in issues if x.severity is Severity.WARNING])/max(1,len(items))*5))
        digest=hashlib.sha256(json.dumps(serialized,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
        return QualityReport(as_of,len(items),len(items)-len(invalid_ids),duplicates,tuple(issues),provenance_counts,score,digest)

    @staticmethod
    def _identity(record: Trade | Candle | Observation) -> str:
        if isinstance(record,Trade):return f"trade:{record.symbol}:{record.trade_id if record.trade_id is not None else record.event_time.isoformat()+':'+str(record.price)+':'+str(record.quantity)}"
        if isinstance(record,Candle):return f"candle:{record.symbol}:{record.timeframe}:{record.open_time.isoformat()}"
        return f"observation:{record.observation_id}"

    @staticmethod
    def _timestamp(record: Trade | Candle | Observation) -> datetime:
        return record.event_time if isinstance(record,Trade) else record.open_time if isinstance(record,Candle) else record.observed_at

    @staticmethod
    def _serialize(record: Trade | Candle | Observation) -> dict[str,Any]:
        if isinstance(record,Observation):return record.to_dict()
        return {key:str(value) if isinstance(value,datetime) else value for key,value in asdict(record).items()}

    @staticmethod
    def _record_checks(record: Trade | Candle | Observation,record_id:str)->list[QualityIssue]:
        issues=[];kind=type(record).__name__
        if not record.symbol.strip():issues.append(QualityIssue("MISSING_SYMBOL",Severity.ERROR,kind,record_id,"Symbol is required."))
        if isinstance(record,(Candle,Observation)) and not record.timeframe.strip():issues.append(QualityIssue("MISSING_TIMEFRAME",Severity.ERROR,kind,record_id,"Timeframe is required."))
        if isinstance(record,Candle) and not record.closed:issues.append(QualityIssue("UNFINISHED_CANDLE",Severity.WARNING,kind,record_id,"Open candle is context only and must not drive closed-candle rules."))
        if isinstance(record,Observation):
            if not record.input_hash:issues.append(QualityIssue("MISSING_INPUT_HASH",Severity.WARNING,kind,record_id,"Observation is not yet tied to a reproducible input hash."))
            if record.rule_id=="unassigned":issues.append(QualityIssue("UNASSIGNED_RULE",Severity.WARNING,kind,record_id,"Observation rule metadata is incomplete."))
        return issues

    @staticmethod
    def _timeframe_delta(value:str)->timedelta|None:
        if len(value)<2 or not value[:-1].isdigit():return None
        units={"s":"seconds","m":"minutes","h":"hours","d":"days"};unit=units.get(value[-1].lower())
        return timedelta(**{unit:int(value[:-1])}) if unit else None

    @classmethod
    def _candle_gap_checks(cls,records:list[Trade|Candle|Observation])->list[QualityIssue]:
        groups:dict[tuple[str,str],list[Candle]]={}
        for record in records:
            if isinstance(record,Candle):groups.setdefault((record.symbol,record.timeframe),[]).append(record)
        issues=[]
        for (symbol,timeframe),candles in sorted(groups.items()):
            expected=cls._timeframe_delta(timeframe)
            if expected is None:
                issues.append(QualityIssue("UNSUPPORTED_TIMEFRAME",Severity.WARNING,"Candle",f"series:{symbol}:{timeframe}","Gap detection cannot parse this timeframe."));continue
            ordered=sorted(candles,key=lambda item:item.open_time)
            for previous,current in zip(ordered,ordered[1:]):
                if current.open_time>previous.open_time+expected:
                    missing=int((current.open_time-previous.open_time)/expected)-1
                    issues.append(QualityIssue("CANDLE_GAP",Severity.ERROR,"Candle",f"series:{symbol}:{timeframe}:{previous.open_time.isoformat()}",f"{missing} expected candle interval(s) missing before {current.open_time.isoformat()}."))
        return issues
