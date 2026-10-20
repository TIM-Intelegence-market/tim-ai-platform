import json

import pytest

from src.bugfixer.processing import Event
from src.bugfixer.store import IncidentStore
from src.repair_diagnosis.flow import diagnose_incident, request_from_incident
from src.repair_diagnosis.store import list_diagnoses

RECORDED_AT = "2026-09-09T00:00:00+00:00"


@pytest.fixture
def store(tmp_path):
    store = IncidentStore(tmp_path / "s.db")
    with store.transaction():
        store.iid = store.record(
            Event("2026-09-09T00:00:00+00:00", "collector", "TimeoutError", "network timeout")
        )
    yield store
    store.close()


def valid(payload):
    return json.dumps(
        {
            "incident_id": json.loads(payload)["incident_id"],
            "hypothesis": "h",
            "proposed_actions": ["a"],
            "confidence": 0.4,
        }
    )


def timeout(payload):
    raise TimeoutError("slow")


def broken(payload):
    raise RuntimeError("down")


def test_request_from_incident(store):
    request = request_from_incident(store.inspect(store.iid))
    assert request["incident_id"] == store.iid
    assert request["fingerprint"] == store.iid
    assert request["normalized_error"] == "TimeoutError: network timeout"
    assert request["category"] == "NETWORK"


def test_fallback_provider_saves_proposal(store, tmp_path):
    directory = tmp_path / "d"
    outcome = diagnose_incident(
        store, store.iid, [("slow", timeout), ("good", valid)], directory, recorded_at=RECORDED_AT
    )
    assert outcome["outcome"] == "PROPOSAL"
    assert outcome["can_mark_fixed"] is False
    saved = list_diagnoses(directory, store.iid)
    assert len(saved) == 1
    assert saved[0]["outcome"] == "PROPOSAL"
    assert saved[0]["provider"] == "good"
    assert saved[0]["request_sha256"] == outcome["request_sha256"]


def test_provider_failed_is_saved(store, tmp_path):
    directory = tmp_path / "d"
    outcome = diagnose_incident(
        store, store.iid, [("slow", timeout), ("bad", broken)], directory, recorded_at=RECORDED_AT
    )
    assert outcome["outcome"] == "PROVIDER_FAILED"
    assert outcome["can_mark_fixed"] is False
    saved = list_diagnoses(directory, store.iid)
    assert [item["outcome"] for item in saved] == ["PROVIDER_FAILED"]
    assert [a["status"] for a in saved[0]["attempts"]] == ["timeout", "error"]


def test_unknown_incident_saves_nothing(store, tmp_path):
    directory = tmp_path / "d"
    with pytest.raises(KeyError):
        diagnose_incident(store, "f" * 64, [("good", valid)], directory, recorded_at=RECORDED_AT)
    assert not directory.exists() or not list(directory.iterdir())


def test_incident_is_not_modified(store, tmp_path):
    before = store.inspect(store.iid)
    diagnose_incident(store, store.iid, [("good", valid)], tmp_path / "d", recorded_at=RECORDED_AT)
    diagnose_incident(store, store.iid, [("bad", broken)], tmp_path / "d", recorded_at=RECORDED_AT)
    assert store.inspect(store.iid) == before
