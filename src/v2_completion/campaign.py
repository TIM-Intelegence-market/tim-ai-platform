"""Start and daily bookkeeping for the prospective V2 qualification campaign.

Pure logic only; the scripts gather evidence and write files. A campaign starts
only from a fresh start-gate report whose gates all PASS for the exact commit the
server runs, plus a named human approval. Daily manifests cover complete UTC days
from the campaign start onwards and are never rewritten.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.v2_completion.qualification import REQUIRED_START_GATES, StartGate

UTC = timezone.utc
MAX_REPORT_AGE = timedelta(minutes=30)
SETTLE = timedelta(minutes=5)
START_GATE_KIND = "V2_QUALIFICATION_START_GATE_EVALUATION"


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def gates_from_report(report: dict[str, Any], *, report_ref: str, head: str, now: datetime,
                      max_age: timedelta = MAX_REPORT_AGE) -> list[StartGate]:
    """Turn a start-gate report into StartGates; refuse stale, foreign or failing reports."""
    if report.get("kind") != START_GATE_KIND:
        raise ValueError("not a start-gate evaluation report")
    evaluated = _parse(report.get("evaluated_at_utc"))
    if evaluated is None or not timedelta(minutes=-1) <= now - evaluated <= max_age:
        raise ValueError("start-gate report is not fresh")
    if (report.get("context") or {}).get("head") != head:
        raise ValueError("start-gate report was taken on a different commit than HEAD")
    if not report.get("all_start_gates_pass") or report.get("blocking_start_gates"):
        raise ValueError("start gates do not all pass: " + ", ".join(report.get("blocking_start_gates") or []))
    by_name = {gate.get("name"): gate for gate in report.get("gates", [])}
    if sorted(by_name) != sorted(REQUIRED_START_GATES):
        raise ValueError("start-gate report does not cover every required gate")
    frozen = (by_name["configuration_and_commit_frozen"].get("evidence") or {}).get("frozen_commit")
    if frozen != head:
        raise ValueError("frozen commit in the report differs from HEAD")
    sha = report.get("report_sha256", "")
    return [StartGate(name, by_name[name]["status"], f"{report_ref} sha256={sha} status={by_name[name]['status']}")
            for name in REQUIRED_START_GATES]


def campaign_start_minute(now: datetime) -> datetime:
    """The next full UTC minute: the campaign never counts time before the start action."""
    return now.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)


def day_window(campaign_start: datetime, day: date) -> tuple[datetime, datetime]:
    midnight = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return max(midnight, campaign_start), midnight + timedelta(days=1)


def pending_days(campaign_start: datetime, now: datetime, written: set[str]) -> list[date]:
    """Complete, settled UTC days since the start without a manifest yet.

    The pre-registered duration is a minimum; manifests continue while the campaign is active."""
    days = []
    day = campaign_start.astimezone(UTC).date()
    while True:
        _, end = day_window(campaign_start, day)
        if end + SETTLE > now:
            break
        if day.isoformat() not in written:
            days.append(day)
        day += timedelta(days=1)
    return days


def daily_metrics(*, day: date, window: tuple[datetime, datetime], coverage: dict[str, Any],
                  gaps: list[dict[str, Any]], cases: dict[str, Any], health: dict[str, Any] | None,
                  security: dict[str, Any], open_gap_incidents: int | None) -> dict[str, Any]:
    """Metrics for one UTC day. Coverage is the day's; cases are cumulative since the start."""
    partitions = coverage["dimensions"]["date_partitions"]
    today = next((item for item in partitions if item["utc_date"] == day.isoformat()), None)
    if today is None:
        raise ValueError(f"audit has no partition for {day}")
    start, end = window
    day_gaps = [gap for gap in gaps if _parse(gap["start_utc"]) < end and _parse(gap["end_utc"]) > start]
    health = health or {}
    runtime_status = {key: health.get(key) for key in ("status", "mode", "trading_actions", "generated_at_utc")}
    if runtime_status["generated_at_utc"] is None:
        runtime_status["generated_at_utc"] = health.get("timestamp")
    return {
        "window_start_utc": start.isoformat().replace("+00:00", "Z"),
        "window_end_utc": end.isoformat().replace("+00:00", "Z"),
        "coverage": today["coverage"],
        "expected_minutes": today["expected"],
        "observed_minutes": today["observed"],
        "missing_minutes": today["missing"],
        "cumulative_coverage": coverage["product_calculation"]["coverage"],
        "cumulative_missing_minutes": coverage["product_calculation"]["missing_observations"],
        "audit_agreement": coverage["audit_agreement"],
        "gap_count": len(day_gaps),
        "incident_ids": [gap["gap_id"] for gap in day_gaps],
        "open_gap_incidents": open_gap_incidents,
        "case_count": cases["raw_complete_validation_rows"],
        "quality_eligible_labels": cases["quality_eligible_labels"],
        "independent_case_count": cases["strict_independent_30m_windows"],
        "independent_case_target": cases["required_independent_cases"],
        "runtime_status": runtime_status,
        "security_status": security,
        "data_manifest_hash": coverage["data_manifest_hash"],
        "database_snapshot": coverage["database_snapshot"],
    }
