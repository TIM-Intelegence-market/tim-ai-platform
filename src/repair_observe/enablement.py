from __future__ import annotations

import math
from numbers import Real


DEFAULT_THRESHOLDS = {
    "min_events": 1000,
    "max_unknown_rate": 0.20,
    "max_critical_rate": 0.05,
    "max_ingestion_lag_seconds": 300,
    "max_checkpoint_age_seconds": 600,
    "max_pending_tracebacks": 0,
}


def _result(decision: str, reasons: list[str]) -> dict:
    return {
        "decision": decision,
        "reasons": sorted(reasons),
        "auto_repair_enabled": False,
    }


def _is_number(value: object) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def a1_go_no_go(metrics: dict, thresholds: dict | None = None) -> dict:
    if not isinstance(metrics, dict):
        return _result("NO_GO", ["metrics"])

    if thresholds is None:
        active_thresholds = dict(DEFAULT_THRESHOLDS)
    elif isinstance(thresholds, dict):
        if any(not isinstance(key, str) for key in thresholds):
            return _result("NO_GO", ["threshold keys must be strings"])
        unknown = sorted(set(thresholds) - set(DEFAULT_THRESHOLDS))
        if unknown:
            return _result("NO_GO", [f"unknown threshold key: {key}" for key in unknown])
        active_thresholds = dict(DEFAULT_THRESHOLDS)
        active_thresholds.update(thresholds)
    else:
        return _result("NO_GO", ["thresholds"])

    reasons: list[str] = []
    for name, value in active_thresholds.items():
        if not _is_number(value):
            reasons.append(f"threshold {name}")

    numeric_metrics = (
        "events_ingested",
        "unknown_rate",
        "critical_rate",
        "ingestion_lag_seconds",
        "checkpoint_age_seconds",
        "pending_tracebacks",
    )
    for name in numeric_metrics:
        if name not in metrics:
            reasons.append(name)
        elif not _is_number(metrics[name]):
            reasons.append(name)

    if "future_timestamp_observed" not in metrics:
        reasons.append("future_timestamp_observed")
    elif not isinstance(metrics["future_timestamp_observed"], bool):
        reasons.append("future_timestamp_observed")

    if reasons:
        return _result("NO_GO", reasons)

    checks = {
        "events_ingested": metrics["events_ingested"] >= active_thresholds["min_events"],
        "unknown_rate": metrics["unknown_rate"] <= active_thresholds["max_unknown_rate"],
        "critical_rate": metrics["critical_rate"] <= active_thresholds["max_critical_rate"],
        "ingestion_lag_seconds": metrics["ingestion_lag_seconds"] <= active_thresholds["max_ingestion_lag_seconds"],
        "checkpoint_age_seconds": metrics["checkpoint_age_seconds"] <= active_thresholds["max_checkpoint_age_seconds"],
        "pending_tracebacks": metrics["pending_tracebacks"] <= active_thresholds["max_pending_tracebacks"],
        "future_timestamp_observed": metrics["future_timestamp_observed"] is False,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        return _result("NO_GO", failed)
    return _result("GO", [])
