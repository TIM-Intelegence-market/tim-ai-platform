"""Pure helpers for incident-observation quality metrics."""

from numbers import Real

_REQUIRED_KEYS = (
    "incidents_created",
    "events_ingested",
    "occurrences_deduplicated",
    "unknown_incidents",
    "active_incidents",
    "critical_incidents",
    "ingestion_lag_seconds",
    "checkpoint_age_seconds",
    "future_timestamp_observed",
    "pending_tracebacks",
)


def _number(status: dict, key: str, *, allow_none: bool = False) -> Real | None:
    if key not in status:
        raise ValueError(f"missing key: {key}")
    value = status[key]
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"invalid value for key: {key}")
    return value


def quality_metrics(status: dict) -> dict:
    """Return quality metrics derived from an IncidentStore status mapping."""
    values = {
        key: _number(
            status,
            key,
            allow_none=key in {"ingestion_lag_seconds", "checkpoint_age_seconds"},
        )
        for key in _REQUIRED_KEYS
        if key != "future_timestamp_observed"
    }

    if "future_timestamp_observed" not in status:
        raise ValueError("missing key: future_timestamp_observed")
    future_timestamp_observed = status["future_timestamp_observed"]
    if not isinstance(future_timestamp_observed, bool):
        raise ValueError("invalid value for key: future_timestamp_observed")

    incidents_created = values["incidents_created"]
    events_ingested = values["events_ingested"]

    return {
        "unknown_rate": (
            None
            if incidents_created == 0
            else values["unknown_incidents"] / incidents_created
        ),
        "dedup_ratio": (
            None
            if events_ingested == 0
            else values["occurrences_deduplicated"] / events_ingested
        ),
        "critical_rate": (
            None
            if incidents_created == 0
            else values["critical_incidents"] / incidents_created
        ),
        "ingestion_lag_seconds": values["ingestion_lag_seconds"],
        "checkpoint_age_seconds": values["checkpoint_age_seconds"],
        "future_timestamp_observed": future_timestamp_observed,
        "pending_tracebacks": values["pending_tracebacks"],
        "events_ingested": events_ingested,
    }
