from src.collaboration.live_status import SCHEMA_VERSION, validate_live_status


ALLOWED_FIELDS = {
    "collectors": ("running", "stale", "total"),
    "queue": ("pending", "blocked", "oldest_age_seconds"),
    "coverage": ("symbols", "complete_minutes_24h", "missing_minutes_24h"),
    "quality": ("unknown_rate", "critical_incidents", "last_check_ok"),
}


def build_live_status(observed, *, captured_at_utc, published_at_utc):
    if not isinstance(observed, dict):
        raise ValueError("observed must be an object")

    document = {
        "schema_version": SCHEMA_VERSION,
        "published_at_utc": published_at_utc,
        "captured_at_utc": captured_at_utc,
        "collectors": {},
        "queue": {},
        "coverage": {},
        "quality": {},
        "safety": {"observe_only": True, "trading_actions_emitted": 0},
    }

    for section, fields in ALLOWED_FIELDS.items():
        source = observed.get(section)
        if not isinstance(source, dict):
            source = {}
        document[section] = {
            field: value if isinstance(value, (int, float, bool)) or value is None else None
            for field in fields
            for value in [source.get(field)]
        }

    validation = validate_live_status(document)
    if not validation["ok"]:
        raise ValueError("; ".join(validation["errors"]))
    return document
