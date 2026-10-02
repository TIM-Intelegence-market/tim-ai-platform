from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.research.case_builder import ACTIVE_STATUSES, assess


def _assessed(item: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    try:
        assessment = assess(item, as_of)
    except (TypeError, ValueError, KeyError) as exc:  # malformed stored case stays visible, never hidden
        assessment = {"error": f"assessment unavailable: {type(exc).__name__}", "data_quality_status": "DEFECT",
                      "review_status": "BLOCKED", "gap_exposure": [], "maturity": "UNKNOWN"}
    return {**item, "assessment": assessment}


def _research_case_detail(item: dict[str, Any], as_of: datetime | None = None) -> dict[str, Any]:
    """Case fields plus lifecycle, timeline, assessment and provenance (read-only)."""
    as_of = as_of or datetime.now(timezone.utc)
    detail = _assessed(dict(item), as_of)
    detail["timeline"] = sorted((dict(ev) for ev in item.get("evidence", []) or []), key=lambda ev: (str(ev.get("observed_at", "")), str(ev.get("observation_id", ""))))
    detail["lifecycle"] = list(item.get("review_history", []) or [])
    detail["provenance"] = "PUBLIC_MARKET_DATA_DETERMINISTIC"
    detail["mode"] = "OBSERVE / READ-ONLY"
    return detail


def _research_cases_collection(snapshot: dict[str, Any], query: dict[str, list[str]], stats_only: bool = False, as_of: datetime | None = None) -> dict[str, Any]:
    """Read-only Research Case collection: filters (no implicit CONFIRMED
    restriction), real per-status stats, cursor pagination. OBSERVE-only."""
    as_of = as_of or datetime.now(timezone.utc)
    cases = [_assessed(dict(item), as_of) for item in snapshot.get("research_cases", [])]
    by_status: dict[str, int] = {}
    for item in cases:
        key = str(item.get("status") or "OPEN").upper()
        by_status[key] = by_status.get(key, 0) + 1
    missing: dict[str, int] = {}
    for item in cases:
        for reason in item.get("missing_evidence", []) or []:
            missing[str(reason)] = missing.get(str(reason), 0) + 1
    stats = {"total": len(cases), "by_status": dict(sorted(by_status.items())),
             "confirmed": by_status.get("CONFIRMED", 0),
             "pending_outcome": sum(1 for item in cases if not item.get("outcome")),
             "missing_evidence": dict(sorted(missing.items())),
             "active": sum(by_status.get(key, 0) for key in ACTIVE_STATUSES),
             "gap_exposure": sum(1 for item in cases if item["assessment"].get("gap_exposure")),
             "by_data_quality": _count(item["assessment"].get("data_quality_status") for item in cases),
             "by_review_status": _count(item["assessment"].get("review_status") for item in cases),
             "by_maturity": _count(item["assessment"].get("maturity") for item in cases),
             "as_of": as_of.isoformat()}
    if stats_only:
        return {"stats": stats, "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC"}
    status = (query.get("status", [""])[0] or "").upper()
    if status == "ACTIVE":
        cases = [item for item in cases if str(item.get("status") or "OPEN").upper() in ACTIVE_STATUSES]
    elif status and status != "ALL":
        cases = [item for item in cases if str(item.get("status") or "").upper() == status]
    timeframe = (query.get("timeframe", [""])[0] or "")
    if timeframe:
        cases = [item for item in cases if str(item.get("timeframe", "")) == timeframe]
    otype = (query.get("observation_type", [""])[0] or "")
    if otype:
        cases = [item for item in cases if any(str(ev.get("kind", "")) == otype for ev in item.get("evidence", []) or [])]
    rule = (query.get("rule_version", [""])[0] or "")
    if rule:
        cases = [item for item in cases if rule in set(str(v) for v in (item.get("rule_versions", {}) or {}).values())]
    instrument = (query.get("instrument", [""])[0] or "")
    if instrument:
        cases = [item for item in cases if str(item.get("symbol", "")) == instrument]
    quality = (query.get("data_quality_status", [""])[0] or "").upper()
    if quality:
        cases = [item for item in cases if str(item["assessment"].get("data_quality_status", "")).upper() == quality]
    review = (query.get("review_status", [""])[0] or "").upper()
    if review:
        cases = [item for item in cases if str(item["assessment"].get("review_status", "")).upper() == review]
    try:
        limit = max(1, min(200, int((query.get("limit", ["50"])[0] or "50"))))
    except ValueError:
        limit = 50
    cursor = (query.get("cursor", [""])[0] or "")
    start = 0
    if cursor:
        for index, item in enumerate(cases):
            if str(item.get("case_id")) == cursor:
                start = index + 1
                break
    window = cases[start:start + limit]
    return {"cases": window, "stats": stats,
            "pagination": {"limit": limit, "returned": len(window), "total_matching": len(cases),
                           "next_cursor": str(window[-1].get("case_id", "")) if len(window) == limit and start + limit < len(cases) else None},
            "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC"}


def _count(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))
