"""Deterministic Research Case builder (Issue #3, Phasen 2-4).

Derives case status, missing evidence, outcome maturity and provenance from
persisted observations and their case container. OBSERVE-only:

- reads observations, candles and gap incidents; never writes them
- derives only research-case fields (status, missing_evidence, outcome,
  review_history); CONFIRMED is never derived, only set by a manual review
  through ``ResearchCaseEngine.confirm``
- every decision depends on ``as_of`` (data time), never on the wall clock;
  same input and same ``as_of`` give byte-identical cases (idempotent)
- outcome labels describe what price did after the case window closed; they
  are research descriptions, never setups, signals or recommendations
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from src.models.market_data import Observation, ObservationKind
from src.research.case_engine import ResearchCase, ResearchCaseEngine

BUILDER_VERSION = "research-case-builder/1.0.0"
SCHEMA_VERSION = 2
CASE_WINDOW = timedelta(minutes=30)
HORIZON_BARS = 12
MIN_OBSERVATIONS = 2
SIDEWAYS_BAND = 0.001

REASON_TOO_FEW = "zu wenige Observations"
REASON_RULE_VERSION = "Rule Version fehlt"
REASON_HORIZON = "Outcome horizon not closed"
REASON_OUTCOME_DATA = "Outcome-Daten unvollständig"
REASON_GAP = "Gap überlappt Case"
REASON_QUALITY = "Data Quality unter Schwelle"
REASON_REVIEW = "Manual Review pending"
CONTEXT_CODES = ("structure_confirmation", "level_reaction_context", "continuation_context")

ACTIVE_STATUSES = ("OPEN", "MONITORING", "COLLECTING_EVIDENCE", "READY_FOR_REVIEW")
# Set by a person or a terminal rule; the builder never moves a case out of these.
LOCKED_STATUSES = frozenset({"CONFIRMED", "REJECTED", "CLOSED", "QUARANTINED", "INVALIDATED"})
OBSERVATION_KINDS = frozenset(kind.value for kind in ObservationKind)


@dataclass(frozen=True, slots=True)
class Gap:
    """Known data gap for a symbol; ``end`` None means still open."""
    gap_id: str
    symbol: str
    start: datetime
    end: datetime | None = None


def parse_timeframe(timeframe: str) -> timedelta | None:
    units = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    try:
        value, unit = int(timeframe[:-1]), timeframe[-1]
    except (ValueError, IndexError):
        return None
    if unit not in units or value <= 0:
        return None
    return timedelta(**{units[unit]: value})


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def is_builder_case(case: Mapping[str, Any] | ResearchCase) -> bool:
    """Observation-engine cases; orderflow cases (``ofcase_``) have their own lifecycle."""
    case_id = case.case_id if isinstance(case, ResearchCase) else str(case.get("case_id", ""))
    return case_id.startswith("case_")


def case_window(opened_at: datetime) -> tuple[datetime, datetime]:
    seconds = CASE_WINDOW.total_seconds()
    start = datetime.fromtimestamp((opened_at.timestamp() // seconds) * seconds, tz=timezone.utc)
    return start, start + CASE_WINDOW


def case_hash(case: Mapping[str, Any]) -> str:
    """Content hash over the case identity and its evidence; independent of ``as_of``."""
    evidence = sorted(
        (str(item.get("observation_id", "")), str(item.get("input_hash", "")), str(item.get("kind", "")), str(item.get("observed_at", "")))
        for item in case.get("evidence", []) or []
    )
    payload = {
        "case_id": str(case.get("case_id", "")),
        "symbol": str(case.get("symbol", "")),
        "timeframe": str(case.get("timeframe", "")),
        "evidence": evidence,
        "rule_versions": dict(sorted((case.get("rule_versions") or {}).items())),
        "builder_version": BUILDER_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evidence_defects(case: Mapping[str, Any], as_of: datetime) -> list[str]:
    """Machine-readable reasons that make the case data defective (quarantine)."""
    defects: list[str] = []
    for item in case.get("evidence", []) or []:
        oid = str(item.get("observation_id", "?"))
        if not item.get("input_hash"):
            defects.append(f"observation {oid}: input_hash fehlt")
        if str(item.get("kind", "")) not in OBSERVATION_KINDS:
            defects.append(f"observation {oid}: unbekannter Typ {item.get('kind')!r}")
        try:
            if _time(item.get("observed_at")) > as_of:
                defects.append(f"observation {oid}: liegt nach as_of (Look-Ahead)")
        except (TypeError, ValueError):
            defects.append(f"observation {oid}: observed_at ungültig")
    return defects


def _gaps_overlapping(case: Mapping[str, Any], start: datetime, end: datetime, gaps: Iterable[Gap]) -> list[str]:
    symbol = str(case.get("symbol", ""))
    return sorted(gap.gap_id for gap in gaps if gap.symbol == symbol and gap.start < end and (gap.end is None or gap.end > start))


def _outcome(candles: list[Mapping[str, Any]], anchor: datetime, due: datetime, step: timedelta) -> tuple[str | None, str | None]:
    """Descriptive price outcome between window end and horizon end.

    Returns (label, None) or (None, reason). Requires every bar of the horizon,
    so a hole in the candles never yields an outcome.
    """
    closes: dict[datetime, float] = {}
    for candle in candles:
        try:
            closes[_time(candle["close_time"])] = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            continue
    anchor_close = max((t for t in closes if t <= anchor), default=None)
    if anchor_close is None or anchor - anchor_close >= step:
        return None, REASON_OUTCOME_DATA
    expected = int((due - anchor) / step)
    covered = [t for t in closes if anchor < t <= due]
    if len(covered) < expected:
        return None, REASON_OUTCOME_DATA
    start_price, end_price = closes[anchor_close], closes[max(covered)]
    if start_price <= 0:
        return None, REASON_QUALITY
    change = (end_price - start_price) / start_price
    if change > SIDEWAYS_BAND:
        return "PRICE_INCREASED", None
    if change < -SIDEWAYS_BAND:
        return "PRICE_DECREASED", None
    return "PRICE_SIDEWAYS", None


def assess(case: Mapping[str, Any], as_of: datetime, *, gaps: Iterable[Gap] = (), candles: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Pure, deterministic assessment of one case at data time ``as_of``."""
    as_of = _time(as_of)
    evidence = list(case.get("evidence", []) or [])
    status = str(case.get("status") or "OPEN").upper()
    base = {
        "schema_version": SCHEMA_VERSION,
        "case_version": BUILDER_VERSION,
        "case_hash": case_hash(case),
        "as_of": as_of.isoformat(),
        "observation_count": len(case.get("observation_ids", []) or []),
        "observation_types": sorted({str(item.get("kind", "")) for item in evidence if item.get("kind")}),
        "lineage": {
            "source": "observations",
            "observation_ids": sorted(str(item) for item in case.get("observation_ids", []) or []),
            "input_hashes": sorted({str(item.get("input_hash")) for item in evidence if item.get("input_hash")}),
            "rule_versions": dict(sorted((case.get("rule_versions") or {}).items())),
        },
    }
    if not is_builder_case(case):
        return {**base, "builder": "external", "derived_status": status, "missing_evidence": list(case.get("missing_evidence", []) or []),
                "maturity": "MATURE" if case.get("outcome") else "PENDING", "outcome": case.get("outcome"),
                "data_quality_status": "UNASSESSED", "gap_exposure": [], "review_status": _review_status(status), "defects": []}
    opened = _time(case.get("opened_at"))
    window_start, window_end = case_window(opened)
    step = parse_timeframe(str(case.get("timeframe", ""))) or timedelta(minutes=1)
    due = window_end + step * HORIZON_BARS
    gap_ids = _gaps_overlapping(case, window_start, due, gaps)
    defects = evidence_defects(case, as_of)
    kinds = set(base["observation_types"])
    missing: list[str] = []
    if base["observation_count"] < MIN_OBSERVATIONS:
        missing.append(REASON_TOO_FEW)
    rules = case.get("rule_versions") or {}
    if not rules or any(not value or key == "unassigned" for key, value in rules.items()):
        missing.append(REASON_RULE_VERSION)
    if not ({ObservationKind.BOS_BULLISH.value, ObservationKind.BOS_BEARISH.value} & kinds):
        missing.append("structure_confirmation")
    if ObservationKind.REJECTION.value not in kinds:
        missing.append("level_reaction_context")
    if not ({ObservationKind.WEAK_CONTINUATION.value, ObservationKind.FAILED_CONTINUATION.value} & kinds):
        missing.append("continuation_context")
    mature = as_of >= due
    outcome = case.get("outcome")
    if status in LOCKED_STATUSES:
        pass
    elif not mature:
        missing.append(REASON_HORIZON)
        outcome = None
    elif gap_ids or defects:
        outcome = None
    elif not outcome:
        if candles is None:
            missing.append(REASON_OUTCOME_DATA)
        else:
            outcome, reason = _outcome(list(candles), window_end, due, step)
            if reason:
                missing.append(reason)
    if gap_ids:
        missing.append(REASON_GAP)
    if defects:
        missing.append(REASON_QUALITY)
    if status in LOCKED_STATUSES:
        derived, reason = status, "status locked by review or terminal rule"
        if status in {"CONFIRMED", "REJECTED", "CLOSED"}:
            missing = [item for item in missing if item != REASON_HORIZON]
    elif defects:
        derived, reason = "QUARANTINED", "; ".join(defects)
    elif base["observation_count"] < MIN_OBSERVATIONS:
        derived, reason = "OPEN", REASON_TOO_FEW
    elif missing:
        derived, reason = "COLLECTING_EVIDENCE", "; ".join(missing)
    else:
        missing.append(REASON_REVIEW)
        derived, reason = "READY_FOR_REVIEW", "alle automatisch prüfbaren Kriterien erfüllt; manuelles Review offen"
    return {
        **base,
        "builder": BUILDER_VERSION,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "outcome_due_at": due.isoformat(),
        "maturity": "MATURE" if mature else "PENDING",
        "outcome": outcome,
        "derived_status": derived,
        "derivation_reason": reason,
        "missing_evidence": missing,
        "data_quality_status": "DEFECT" if defects else "GAP_EXPOSED" if gap_ids else "OK",
        "gap_exposure": gap_ids,
        "review_status": _review_status(derived),
        "defects": defects,
    }


def _review_status(status: str) -> str:
    if status in {"CONFIRMED", "REJECTED"}:
        return "REVIEWED"
    if status == "READY_FOR_REVIEW":
        return "PENDING"
    if status == "QUARANTINED":
        return "BLOCKED"
    return "NOT_READY"


def refresh_case(case: ResearchCase, as_of: datetime, *, gaps: Iterable[Gap] = (), candles: Iterable[Mapping[str, Any]] | None = None) -> bool:
    """Apply the assessment to a case in place; returns True when anything changed.

    Status changes are recorded in ``review_history`` with the builder version
    and the reason, stamped with ``as_of`` so reruns stay idempotent.
    """
    if not is_builder_case(case):
        return False
    result = assess(case.to_dict(), as_of, gaps=gaps, candles=candles)
    before = (case.status, list(case.missing_evidence), case.outcome)
    if result["derived_status"] != case.status:
        case.review_history.append({"at": result["as_of"], "from": case.status, "to": result["derived_status"],
                                    "reason": f"{BUILDER_VERSION}: {result['derivation_reason']}", "by": "case_builder"})
        case.status = result["derived_status"]
    case.missing_evidence = list(result["missing_evidence"])
    case.outcome = result["outcome"]
    return before != (case.status, case.missing_evidence, case.outcome)


@dataclass(slots=True)
class MaterializationResult:
    as_of: datetime
    cases: list[ResearchCase]
    excluded: list[dict[str, str]]
    observations_read: int

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.status] = counts.get(case.status, 0) + 1
        return dict(sorted(counts.items()))

    def manifest(self) -> dict[str, Any]:
        rows = [case.to_dict() for case in self.cases]
        digest = hashlib.sha256(json.dumps([[row["case_id"], case_hash(row), row["status"], row["missing_evidence"], row["outcome"]] for row in rows],
                                           sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {
            "builder_version": BUILDER_VERSION, "schema_version": SCHEMA_VERSION, "as_of": self.as_of.isoformat(),
            "observations_read": self.observations_read, "observations_excluded": len(self.excluded),
            "cases": len(rows), "status_counts": self.status_counts(), "case_ids": [row["case_id"] for row in rows],
            "manifest_hash": digest,
        }


def materialize(
    observations: Iterable[Observation],
    as_of: datetime,
    *,
    existing: Iterable[ResearchCase] = (),
    gaps: Iterable[Gap] = (),
    candles_by_key: Mapping[tuple[str, str], list[Mapping[str, Any]]] | None = None,
) -> MaterializationResult:
    """Build all observation cases from scratch, then keep locked review states.

    Observations after ``as_of`` are excluded (no look-ahead). Existing cases
    contribute only their review-locked status, outcome and review history;
    everything else is rebuilt from the observations.
    """
    as_of = _time(as_of)
    gaps = list(gaps)
    ordered = sorted(observations, key=lambda item: (item.observed_at, str(item.observation_id)))
    engine = ResearchCaseEngine(case_window=CASE_WINDOW)
    excluded: list[dict[str, str]] = []
    for observation in ordered:
        if observation.observed_at > as_of:
            excluded.append({"observation_id": str(observation.observation_id), "reason": "observed_after_as_of"})
            continue
        engine.ingest(observation)
    previous = {case.case_id: case for case in existing}
    for case_id, case in engine.cases.items():
        old = previous.get(case_id)
        if old is None:
            continue
        case.review_history = [dict(item) for item in old.review_history]
        case.status = old.status if old.status in LOCKED_STATUSES or old.status in ACTIVE_STATUSES else case.status
        if old.status in LOCKED_STATUSES:
            case.outcome = old.outcome
        case.documentation = old.documentation or case.documentation
    for case in engine.cases.values():
        key = (case.symbol, case.timeframe)
        refresh_case(case, as_of, gaps=gaps, candles=None if candles_by_key is None else candles_by_key.get(key, []))
    cases = sorted(engine.cases.values(), key=lambda item: item.case_id)
    return MaterializationResult(as_of=as_of, cases=cases, excluded=excluded, observations_read=len(ordered))
