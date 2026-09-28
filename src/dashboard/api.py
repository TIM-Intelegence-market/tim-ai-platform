from __future__ import annotations

from typing import Any


def _research_cases_collection(snapshot: dict[str, Any], query: dict[str, list[str]], stats_only: bool = False) -> dict[str, Any]:
    """Read-only Research Case collection: filters (no implicit CONFIRMED
    restriction), real per-status stats, cursor pagination. OBSERVE-only."""
    cases = [dict(item) for item in snapshot.get("research_cases", [])]
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
             "missing_evidence": dict(sorted(missing.items()))}
    if stats_only:
        return {"stats": stats, "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC"}
    status = (query.get("status", [""])[0] or "").upper()
    if status and status != "ALL":
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
