import copy

import pytest

from src.bugfixer import processing
from src.collaboration import live_status
from src.collaboration.live_status import SCHEMA_VERSION, validate_live_status


def _doc():
    return {
        "schema_version": SCHEMA_VERSION,
        "published_at_utc": "2026-01-01T00:00:10Z",
        "captured_at_utc": "2026-01-01T00:00:05+00:00",
        "collectors": {"active": 3, "names": ["a", "b"], "detail": {"ok": True}},
        "queue": {"depth": 0, "lag": 1.5, "note": None},
        "coverage": {"ratio": 0.9},
        "quality": {"grade": "good"},
        "safety": {"observe_only": True, "trading_actions_emitted": 0},
    }


def _errors(doc):
    result = validate_live_status(doc)
    assert result["ok"] is False
    assert result["errors"] == sorted(result["errors"])
    return result["errors"]


def test_valid_document_passes():
    assert validate_live_status(_doc()) == {"ok": True, "errors": []}


@pytest.mark.parametrize("bad", [None, [], "x", 3])
def test_non_dict_never_raises(bad):
    assert _errors(bad) == ["document must be an object"]


def test_missing_key_rejected():
    doc = _doc()
    del doc["queue"]
    assert "queue: missing required key" in _errors(doc)


def test_unexpected_key_rejected():
    doc = _doc()
    doc["extra"] = 1
    assert "extra: unexpected top-level key" in _errors(doc)


def test_wrong_schema_version_rejected():
    doc = _doc()
    doc["schema_version"] = "other"
    assert "schema_version: unsupported value" in _errors(doc)


@pytest.mark.parametrize("value", ["2026-01-01T00:00:10", "2026-01-01T00:00:10+01:00", "nope", 5])
def test_bad_timestamp_rejected(value):
    doc = _doc()
    doc["published_at_utc"] = value
    assert any(e.startswith("published_at_utc") for e in _errors(doc))


def test_captured_after_published_rejected():
    doc = _doc()
    doc["captured_at_utc"] = "2026-01-01T00:01:00Z"
    assert "captured_at_utc: must not be after published_at_utc" in _errors(doc)


def test_section_nesting_depth_three_rejected():
    doc = _doc()
    doc["queue"] = {"a": {"b": {"c": 1}}}
    assert any("nesting deeper" in e for e in _errors(doc))


def test_section_must_be_dict():
    doc = _doc()
    doc["coverage"] = [1]
    assert "coverage: must be an object" in _errors(doc)


def test_list_with_non_scalar_rejected():
    doc = _doc()
    doc["quality"] = {"items": [{"a": 1}]}
    assert "quality.items: list must contain only scalars" in _errors(doc)


def test_list_over_100_items_rejected():
    doc = _doc()
    doc["quality"] = {"items": list(range(101))}
    assert "quality.items: list longer than 100" in _errors(doc)


def test_list_of_100_items_allowed():
    doc = _doc()
    doc["quality"] = {"items": list(range(100))}
    assert validate_live_status(doc)["ok"] is True


@pytest.mark.parametrize(
    "safety",
    [
        {"observe_only": False, "trading_actions_emitted": 0},
        {"observe_only": True, "trading_actions_emitted": 1},
        {"observe_only": True, "trading_actions_emitted": False},
        {"observe_only": True},
        {"observe_only": True, "trading_actions_emitted": 0, "extra": 1},
    ],
)
def test_unsafe_safety_block_rejected(safety):
    doc = _doc()
    doc["safety"] = safety
    assert _errors(doc)


def test_redactable_value_rejected(monkeypatch):
    monkeypatch.setattr(
        processing, "redact_text", lambda text: text.replace("SECRET", "[REDACTED]")
    )
    doc = _doc()
    doc["quality"] = {"note": "has SECRET inside"}
    assert _errors(doc) == ["doc.quality.note: contains redactable content"]


def test_redactable_key_rejected(monkeypatch):
    monkeypatch.setattr(
        processing, "redact_text", lambda text: text.replace("SECRET", "[REDACTED]")
    )
    doc = _doc()
    doc["quality"] = {"SECRET": 1}
    assert _errors(doc) == ["doc.quality.SECRET (key): contains redactable content"]


def test_redact_failure_is_reported_not_raised(monkeypatch):
    def boom(text):
        raise RuntimeError("x")

    monkeypatch.setattr(processing, "redact_text", boom)
    assert any("redaction check failed" in e for e in _errors(_doc()))


def test_traceback_rejected():
    doc = _doc()
    doc["quality"] = {"note": "Traceback (most recent call last):\n x"}
    assert "doc.quality.note: contains traceback" in _errors(doc)


@pytest.mark.parametrize(
    "path", ["/Users/me/x", "/home/me/x", "/root/x", "C:\\Users\\me"]
)
def test_local_path_rejected(path):
    doc = _doc()
    doc["quality"] = {"p": path}
    assert "doc.quality.p: contains local path" in _errors(doc)


@pytest.mark.parametrize("dsn", ["postgres://h/db", "postgresql://h/db"])
def test_dsn_rejected(dsn):
    doc = _doc()
    doc["quality"] = {"dsn": dsn}
    assert "doc.quality.dsn: contains database DSN" in _errors(doc)


@pytest.mark.parametrize("key", ["trades", "raw_trades", "rows", "exception"])
def test_forbidden_key_rejected(key):
    doc = _doc()
    doc["collectors"] = {key: 1}
    assert f"doc.collectors.{key}: forbidden key" in _errors(doc)


def test_forbidden_key_in_nested_dict_rejected():
    doc = _doc()
    doc["collectors"] = {"inner": {"rows": 1}}
    assert "doc.collectors.inner.rows: forbidden key" in _errors(doc)


def test_input_not_mutated():
    doc = _doc()
    before = copy.deepcopy(doc)
    validate_live_status(doc)
    assert doc == before


def test_schema_constant():
    assert live_status.SCHEMA_VERSION == "tim.collaboration.live_status.v1"
