from __future__ import annotations

from typing import Any


def evaluate_observe_alerts(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Return deterministic OBSERVE-only alerts; never initiate an action."""
    alerts: list[dict[str, str]] = []

    def add(code: str, severity: str, reason: str) -> None:
        alerts.append({"code": code, "severity": severity, "reason": reason, "action": "OBSERVE_ONLY_NO_TRADING_ACTION"})

    if float(snapshot.get("coverage", 0.0)) < 0.95:
        add("COVERAGE_BELOW_TARGET", "P1", "Authoritative closed-1m coverage is below 0.95")
    if int(snapshot.get("open_p0_gaps", 0)):
        add("OPEN_P0_GAP", "P0", "At least one critical data-integrity gap is open")
    if int(snapshot.get("open_p1_gaps", 0)):
        add("OPEN_P1_GAP", "P1", "At least one material coverage or replay gap is open")
    if int(snapshot.get("data_age_seconds", 10**9)) > int(snapshot.get("stale_after_seconds", 180)):
        add("STALE_DATA", "P1", "Latest persisted public market observation is stale")
    if str(snapshot.get("collector_status", "UNKNOWN")).upper() not in {"GREEN", "RUNNING"}:
        add("COLLECTOR_DOWN", "P1", "Collector is not reporting a healthy state")
    if int(snapshot.get("persistence_invalid_rows", 0)):
        add("PERSISTENCE_VALIDATION_FAILURE", "P0", "Invalid persisted rows were detected")
    if int(snapshot.get("clock_skew_rows", 0)):
        add("CLOCK_SKEW", "P1", "Persisted source timestamps exceed ingest timestamps")
    if str(snapshot.get("dashboard_bind", "UNKNOWN")) != "LOOPBACK_ONLY":
        add("PUBLIC_DASHBOARD_BIND", "P0", "Dashboard loopback confinement is not proven")
    if snapshot.get("execution_active") is not False:
        add("EXECUTION_COMPONENT_ACTIVE_OR_UNKNOWN", "P0", "Execution inactivity is not proven")
    return sorted(alerts, key=lambda item: (item["severity"], item["code"]))
