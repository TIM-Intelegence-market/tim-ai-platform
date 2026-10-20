import pytest

from src.collaboration.live_status import validate_live_status
from src.collaboration.snapshot import build_live_status


TIMESTAMPS = {
    "captured_at_utc": "2026-01-01T00:00:05+00:00",
    "published_at_utc": "2026-01-01T00:00:10Z",
}


def test_only_allowlisted_fields_appear():
    result = build_live_status(
        {
            "collectors": {"running": 2, "extra": 99},
            "queue": {"pending": 1},
            "unexpected": {"value": 3},
        },
        **TIMESTAMPS,
    )
    assert set(result) == {
        "schema_version",
        "published_at_utc",
        "captured_at_utc",
        "collectors",
        "queue",
        "coverage",
        "quality",
        "safety",
    }
    assert set(result["collectors"]) == {"running", "stale", "total"}
    assert "unexpected" not in result


def test_strings_and_nested_values_become_none():
    result = build_live_status(
        {
            "quality": {
                "unknown_rate": "0.1",
                "critical_incidents": {"count": 1},
                "last_check_ok": True,
            }
        },
        **TIMESTAMPS,
    )
    assert result["quality"] == {
        "unknown_rate": None,
        "critical_incidents": None,
        "last_check_ok": True,
    }


def test_forbidden_extra_keys_never_appear():
    result = build_live_status({"trades": 4, "collectors": {"trades": 2}}, **TIMESTAMPS)
    assert "trades" not in result
    assert "trades" not in result["collectors"]


def test_result_validates():
    result = build_live_status({}, **TIMESTAMPS)
    assert validate_live_status(result) == {"ok": True, "errors": []}
    assert result["safety"] == {"observe_only": True, "trading_actions_emitted": 0}


@pytest.mark.parametrize(
    "field,value",
    [
        ("captured_at_utc", "not-a-timestamp"),
        ("published_at_utc", "2026-01-01T00:00:10"),
    ],
)
def test_invalid_timestamps_raise_value_error(field, value):
    timestamps = dict(TIMESTAMPS)
    timestamps[field] = value
    with pytest.raises(ValueError):
        build_live_status({}, **timestamps)
