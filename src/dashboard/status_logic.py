"""Current operational status, with explicit freshness and no release authority."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MAX_REPORT_AGE_SECONDS = 300
MAX_CLOCK_SKEW_SECONDS = 30


def current_report(
    report: dict[str, Any], source: str, *, now: datetime,
    status: Any = None,
) -> dict[str, Any]:
    checked_at = next((report.get(key) for key in
                       ("checked_at", "timestamp", "computed_at_utc") if report.get(key)), None)
    age = None
    try:
        checked = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
        if checked.tzinfo is not None:
            age = (now - checked).total_seconds()
    except (TypeError, ValueError, OverflowError):
        pass
    raw_status = str(status if status is not None else report.get("status", "UNAVAILABLE")).upper()
    normalized = {
        "GREEN": "PASS", "PASS": "PASS", "RED": "FAIL", "FAIL": "FAIL",
        "ERROR": "FAIL", "ATTENTION_REQUIRED": "FAIL", "YELLOW": "WARN", "WARN": "WARN",
    }.get(raw_status, "UNAVAILABLE")
    if age is None or age < -MAX_CLOCK_SKEW_SECONDS:
        normalized = "UNAVAILABLE"
    elif age > MAX_REPORT_AGE_SECONDS:
        normalized = "STALE"
    return {
        "status": normalized, "reported_status": raw_status,
        "checked_at": checked_at, "age_seconds": round(age, 1) if age is not None else None,
        "max_age_seconds": MAX_REPORT_AGE_SECONDS, "source": source,
    }


def build_current_status(
    server: dict[str, Any], rolling: dict[str, Any], maintenance: dict[str, Any],
    watchdog: dict[str, Any], *, sources: dict[str, str], now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    checks = server.get("checks")
    runtime_check = checks.get("runtime") if isinstance(checks, dict) else None
    runtime_check = runtime_check if isinstance(runtime_check, dict) else {}
    runtime = current_report(server, sources["runtime"], now=now, status=runtime_check.get("status", "UNAVAILABLE"))
    data = current_report(rolling, sources["data"], now=now)
    # A green count must describe a valid window; zero/invalid counts cannot
    # substantiate complete candle coverage, even if the producer says PASS.
    observed, expected = rolling.get("valid_observations"), rolling.get("expected_observations")
    valid_counts = (type(observed) is int and type(expected) is int
                    and expected > 0 and 0 <= observed <= expected)
    if data["status"] == "PASS" and not valid_counts:
        data["status"] = "UNAVAILABLE"
    data.update({"valid_observations": observed, "expected_observations": expected,
                 "coverage_percent": rolling.get("coverage_percent"),
                 "window_start_utc": rolling.get("window_start_utc"),
                 "window_end_utc": rolling.get("window_end_utc")})
    repair = current_report(maintenance, sources["maintenance"], now=now)
    if repair["status"] == "PASS" and any(
        key in maintenance for key in ("gap_verification_error", "lease_recovery_error")
    ):
        repair["status"] = "WARN"
    repair["verified_current_gaps"] = maintenance.get("verified_current_gaps", {})
    watchdog_status = current_report(watchdog, sources["watchdog"], now=now)
    watchdog_checks = watchdog.get("checks")
    watchdog_status["findings"] = [
        {"check": name, "status": check.get("status"), "value": check.get("value"), "reason": check.get("reason")}
        for name, check in (watchdog_checks.items() if isinstance(watchdog_checks, dict) else ())
        if isinstance(check, dict) and check.get("status") in {"RED", "YELLOW", "FAIL", "WARN"}
    ]
    return {
        "runtime": runtime, "data": data, "maintenance": repair,
        "watchdog": watchdog_status,
        "demo": {"status": "DISABLED", "activation_allowed": False,
                 "reason": "OBSERVE mode; demo activation requires a separate readiness check."},
        "historical": {"status": "ARCHIVED", "affects_current_runtime": False},
    }
