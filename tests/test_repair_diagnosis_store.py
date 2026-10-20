import hashlib
import json

import pytest

from src.repair_diagnosis.store import (
    MAX_RECORD_BYTES,
    DiagnosisStoreError,
    list_diagnoses,
    load_diagnosis,
    save_diagnosis,
)


def request():
    return {
        "incident_id": "inc-1",
        "category": "network",
        "component": "collector",
        "fingerprint": "a" * 64,
        "normalized_error": "TimeoutError: network timeout",
        "stack": "line 1",
        "reproduction": None,
        "code_paths": [],
        "tests": [],
    }


def bridge(outcome="PROPOSAL", hypothesis="retry the request"):
    return {
        "provider": "fake",
        "outcome": outcome,
        "attempts": 1,
        "result": {
            "hypothesis": hypothesis,
            "proposed_actions": ["inspect timeout"],
            "confidence": 0.5,
        },
    }


def test_save_then_load_preserves_fields(tmp_path):
    path = save_diagnosis(
        tmp_path, request(), bridge(), recorded_at="2026-01-01T00:00:00+00:00", provider_model="qwen"
    )
    loaded = load_diagnosis(path)
    assert loaded["outcome"] == "PROPOSAL"
    assert loaded["provider"] == "fake"
    assert loaded["provider_model"] == "qwen"
    assert loaded["request_sha256"]


def test_redacts_secret(tmp_path):
    path = save_diagnosis(
        tmp_path,
        request(),
        bridge(hypothesis="pass" + "word=" + "hun" + "ter2"),
        recorded_at="2026-01-01T00:00:00+00:00",
    )
    assert b"password=hunter2" not in path.read_bytes()


def test_editing_outcome_is_rejected(tmp_path):
    path = save_diagnosis(tmp_path, request(), bridge(), recorded_at="2026-01-01T00:00:00+00:00")
    data = json.loads(path.read_text())
    data["body"]["outcome"] = "PROVIDER_FAILED"
    path.write_text(json.dumps(data))
    with pytest.raises(DiagnosisStoreError):
        load_diagnosis(path)


def test_can_mark_fixed_is_rejected_even_with_new_digest(tmp_path):
    path = save_diagnosis(tmp_path, request(), bridge(), recorded_at="2026-01-01T00:00:00+00:00")
    data = json.loads(path.read_text())
    data["body"]["can_mark_fixed"] = True
    body = json.dumps(data["body"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    data["sha256"] = hashlib.sha256(body).hexdigest()
    path.write_text(json.dumps(data))
    with pytest.raises(DiagnosisStoreError):
        load_diagnosis(path)


def test_naive_timestamp_is_rejected(tmp_path):
    with pytest.raises(DiagnosisStoreError):
        save_diagnosis(tmp_path, request(), bridge(), recorded_at="2026-01-01T00:00:00")


def test_symlinked_directory_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(DiagnosisStoreError):
        save_diagnosis(link, request(), bridge(), recorded_at="2026-01-01T00:00:00+00:00")


def test_oversized_file_is_rejected(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * (MAX_RECORD_BYTES + 1))
    with pytest.raises(DiagnosisStoreError):
        load_diagnosis(path)


def test_list_filters_and_orders(tmp_path):
    save_diagnosis(tmp_path, request(), bridge(), recorded_at="2026-01-02T00:00:00+00:00")
    other = request()
    other["incident_id"] = "inc-2"
    save_diagnosis(tmp_path, other, bridge("PROVIDER_FAILED"), recorded_at="2026-01-01T00:00:00+00:00")
    save_diagnosis(tmp_path, request(), bridge("PROVIDER_FAILED"), recorded_at="2026-01-01T00:00:00+00:00")
    result = list_diagnoses(tmp_path, "inc-1")
    assert len(result) == 2
    assert [item["recorded_at"] for item in result] == sorted(item["recorded_at"] for item in result)
