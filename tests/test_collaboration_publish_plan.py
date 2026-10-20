import json

import pytest

from src.collaboration import publish_plan
from src.collaboration.publish_plan import SNAPSHOT_PATH, plan_publish


def _doc(captured="2026-01-01T00:00:00Z", published="2026-01-01T00:01:00Z", status="ok"):
    return {
        "captured_at_utc": captured,
        "published_at_utc": published,
        "status": status,
    }


def _text(doc):
    return json.dumps(doc, sort_keys=True, indent=2) + "\n"


@pytest.fixture(autouse=True)
def _valid_by_default(monkeypatch):
    monkeypatch.setattr(publish_plan, "validate_live_status", lambda doc: [])


def test_publishes_when_content_changed():
    plan = plan_publish(_doc(status="new"), _text(_doc(status="old")), [SNAPSHOT_PATH])
    assert plan["action"] == "publish"
    assert plan["stage"] == [SNAPSHOT_PATH]
    assert plan["commit_message"] == "chore(collaboration): live status 2026-01-01T00:00:00Z"


def test_publishes_when_no_changed_paths_reported_and_content_differs():
    plan = plan_publish(_doc(status="new"), _text(_doc(status="old")), [])
    assert plan["action"] == "publish"
    assert plan["stage"] == [SNAPSHOT_PATH]


def test_skips_when_only_timestamps_differ():
    previous = _text(_doc(captured="2025-12-31T00:00:00Z", published="2025-12-31T00:01:00Z"))
    plan = plan_publish(_doc(), previous, [SNAPSHOT_PATH])
    assert plan["action"] == "skip"
    assert plan["stage"] == []


def test_safe_stop_for_invalid_doc(monkeypatch):
    monkeypatch.setattr(publish_plan, "validate_live_status", lambda doc: ["bad field"])
    plan = plan_publish(_doc(), "", [SNAPSHOT_PATH])
    assert plan["action"] == "safe_stop"
    assert plan["reasons"] == ["bad field"]
    assert plan["stage"] == []


def test_safe_stop_for_foreign_changed_paths():
    plan = plan_publish(_doc(), "", [SNAPSHOT_PATH, "src/other.py"])
    assert plan["action"] == "safe_stop"
    assert "unexpected changed paths" in plan["reasons"]
    assert plan["stage"] == []


def test_unparsable_previous_text_counts_as_changed():
    plan = plan_publish(_doc(), "{not json", [SNAPSHOT_PATH])
    assert plan["action"] == "publish"
    assert plan["stage"] == [SNAPSHOT_PATH]


def test_validator_exception_yields_safe_stop(monkeypatch):
    def boom(doc):
        raise RuntimeError("x")

    monkeypatch.setattr(publish_plan, "validate_live_status", boom)
    plan = plan_publish(_doc(), "", [])
    assert plan["action"] == "safe_stop"
    assert plan["stage"] == []


@pytest.mark.parametrize(
    "previous, paths",
    [
        ("", []),
        ("{bad", [SNAPSHOT_PATH]),
        (_text(_doc()), [SNAPSHOT_PATH]),
        (_text(_doc(status="old")), ["."]),
        (None, ["-A"]),
    ],
)
def test_stage_is_always_empty_or_snapshot_only(previous, paths):
    plan = plan_publish(_doc(), previous, paths)
    assert plan["stage"] in ([], [SNAPSHOT_PATH])
